import time

import pandas as pd
import streamlit as st

from data_loader.core.models import MySQLParams, CHParams, GPParams
from data_loader.core.ui_log import ui_log, render_logs
from data_loader.adapters.mysql_adapter import MySQLAdapter
from data_loader.adapters.ch_adapter import CHAdapter
from data_loader.adapters.gp_adapter import GPAdapter
from data_loader.pipeline.file_source import read_uploaded_file_to_df
from data_loader.pipeline.mapping import build_mapping_ui, apply_mapping_df
from data_loader.pipeline.ch_cast import cast_df_to_ch_schema
from data_loader.pipeline.query_source import (
    mysql_query_preview, mysql_stream_cursor,
    gp_query_preview, gp_stream_cursor,
    ch_query_preview, ch_iter_chunks_df,
)


st.set_page_config(page_title="Data Loader", layout="wide")
st.title("Data Loader — File → DB / Query(DB) → DB")

# Флаги управления длительными операциями (загрузка/прерывание)
if "is_loading" not in st.session_state:
    st.session_state["is_loading"] = False
if "cancel_requested" not in st.session_state:
    st.session_state["cancel_requested"] = False


if st.button("Очистить логи"):
    st.session_state["logs"] = []

# Streamlit умеет прерывать текущий прогон скрипта при нажатии кнопки (делается rerun).
# Мы используем это как "ручное прерывание" длительных заливок.
if st.session_state.get("is_loading", False):
    if st.button("Остановить загрузку"):
        st.session_state["cancel_requested"] = True
        st.session_state["is_loading"] = False
        ui_log("Пользователь запросил остановку загрузки.")
        st.rerun()


mode = st.radio("Режим", ["File → DB", "Query(DB) → DB"], horizontal=True)
st.divider()

st.subheader("Destination (куда заливаем)")
dst_type = st.selectbox("Destination DB", ["MySQL", "ClickHouse", "Greenplum"], key="dst_type")

dst_table = st.text_input("Destination table", placeholder="Для GP: schema.table (например dev_db.table_test)")
clear_before = st.checkbox("Очистить таблицу перед заливкой (опасно)", value=False)

force_lower_gp = True
if dst_type == "Greenplum":
    force_lower_gp = st.checkbox("force lower-case columns for GP (рекомендую)", value=True)

# Destination params
dst_params_mysql = None
dst_params_ch = None
dst_params_gp = None

if dst_type == "MySQL":
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: dst_host = st.text_input("Host", key="dst_host_mysql")
    with c2: dst_port = st.number_input("Port", min_value=1, max_value=65535, value=3306, key="dst_port_mysql")
    with c3: dst_user = st.text_input("User", key="dst_user_mysql")
    with c4: dst_password = st.text_input("Password", type="password", key="dst_pass_mysql")
    with c5: dst_db = st.text_input("Database", value="bukmaker", key="dst_db_mysql")
    dst_params_mysql = MySQLParams(dst_host, int(dst_port), dst_user, dst_password, dst_db)

elif dst_type == "ClickHouse":
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: dst_host = st.text_input("Host", key="dst_host_ch")
    with c2: dst_port = st.number_input("Port", min_value=1, max_value=65535, value=8123, key="dst_port_ch")
    with c3: dst_user = st.text_input("User", key="dst_user_ch")
    with c4: dst_password = st.text_input("Password", type="password", key="dst_pass_ch")
    with c5: dst_db = st.text_input("Database", value="analytics_tmp", key="dst_db_ch")
    dst_params_ch = CHParams(dst_host, int(dst_port), dst_user, dst_password, dst_db)

else:
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: dst_host = st.text_input("Host", key="dst_host_gp")
    with c2: dst_port = st.number_input("Port", min_value=1, max_value=65535, value=5432, key="dst_port_gp")
    with c3: dst_db = st.text_input("DB name", value="dwh", key="dst_db_gp")
    with c4: dst_user = st.text_input("User", key="dst_user_gp")
    with c5: dst_password = st.text_input("Password", type="password", key="dst_pass_gp")
    dst_params_gp = GPParams(dst_host, int(dst_port), dst_db, dst_user, dst_password)


def make_dst_adapter():
    if dst_type == "MySQL":
        return MySQLAdapter(dst_params_mysql)
    if dst_type == "ClickHouse":
        return CHAdapter(dst_params_ch)
    return GPAdapter(dst_params_gp)


dst_adapter = make_dst_adapter()

if st.button("Test destination"):
    ok, msg = dst_adapter.test()
    if ok:
        st.success("Destination: OK")
        ui_log("Destination connection: OK")
    else:
        st.error(f"Destination error: {msg}")
        ui_log(f"Destination connection error: {msg}")

st.divider()

st.subheader("Настройки загрузки")
cc1, cc2, cc3 = st.columns(3)
with cc1:
    batch_size = st.number_input("Batch size", min_value=1, max_value=500000, value=5000)
with cc2:
    preview_n = st.number_input("Preview rows", min_value=1, max_value=5000, value=100)
with cc3:
    insert_mode = "insert"
    if dst_type == "MySQL":
        insert_mode = st.selectbox("MySQL insert mode", ["insert", "insert ignore", "replace"], index=0)

st.divider()

# Source in query mode
src_type = None
src_params_mysql = None
src_params_gp = None
src_params_ch = None

if mode == "Query(DB) → DB":
    st.subheader("Source (откуда читаем)")
    src_type = st.selectbox("Source DB", ["MySQL", "Greenplum", "ClickHouse"], key="src_type")

    if src_type == "MySQL":
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1: src_host = st.text_input("Host", key="src_host_mysql")
        with s2: src_port = st.number_input("Port", min_value=1, max_value=65535, value=3306, key="src_port_mysql")
        with s3: src_user = st.text_input("User", key="src_user_mysql")
        with s4: src_password = st.text_input("Password", type="password", key="src_pass_mysql")
        with s5: src_db = st.text_input("Database", value="bukmaker", key="src_db_mysql")
        src_params_mysql = MySQLParams(src_host, int(src_port), src_user, src_password, src_db)

        if st.button("Test source"):
            ok, msg = MySQLAdapter(src_params_mysql).test()
            if ok:
                st.success("Source: OK")
                ui_log("Source connection: OK")
            else:
                st.error(f"Source error: {msg}")
                ui_log(f"Source connection error: {msg}")

    elif src_type == "Greenplum":
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1: src_host = st.text_input("Host", key="src_host_gp")
        with s2: src_port = st.number_input("Port", min_value=1, max_value=65535, value=5432, key="src_port_gp")
        with s3: src_db = st.text_input("DB name", value="dwh", key="src_db_gp")
        with s4: src_user = st.text_input("User", key="src_user_gp")
        with s5: src_password = st.text_input("Password", type="password", key="src_pass_gp")
        src_params_gp = GPParams(src_host, int(src_port), src_db, src_user, src_password)

        if st.button("Test source"):
            ok, msg = GPAdapter(src_params_gp).test()
            if ok:
                st.success("Source: OK")
                ui_log("Source connection: OK")
            else:
                st.error(f"Source error: {msg}")
                ui_log(f"Source connection error: {msg}")

    else:  # ClickHouse
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1: src_host = st.text_input("Host", key="src_host_ch")
        with s2: src_port = st.number_input("Port", min_value=1, max_value=65535, value=8123, key="src_port_ch")
        with s3: src_user = st.text_input("User", key="src_user_ch")
        with s4: src_password = st.text_input("Password", type="password", key="src_pass_ch")
        with s5: src_db = st.text_input("Database", value="analytics_tmp", key="src_db_ch")
        src_params_ch = CHParams(src_host, int(src_port), src_user, src_password, src_db)

        if st.button("Test source"):
            ok, msg = CHAdapter(src_params_ch).test()
            if ok:
                st.success("Source: OK")
                ui_log("Source connection: OK")
            else:
                st.error(f"Source error: {msg}")
                ui_log(f"Source connection error: {msg}")

    st.divider()


def load_destination_schema():
    if not dst_table:
        raise ValueError("Не указана Destination table.")

    if dst_type == "MySQL":
        cols = dst_adapter.get_columns(dst_table)
        return cols, {}

    if dst_type == "ClickHouse":
        schema = dst_adapter.get_schema(dst_table)
        return list(schema.keys()), schema

    cols = dst_adapter.get_columns(dst_table)
    return cols, {}


# File → DB
if mode == "File → DB":
    st.subheader("Источник: файл (Excel/CSV)")
    file_kind = st.selectbox("Тип файла", ["Excel (.xlsx)", "CSV (.csv)"])
    uploaded = st.file_uploader("Выбери файл", type=["xlsx", "csv"])

    excel_sheet = None
    csv_sep = ","
    if file_kind == "Excel (.xlsx)":
        excel_sheet = st.text_input("Лист Excel (пусто = первый)", value="").strip() or None
    else:
        csv_sep = st.text_input("CSV separator", value=",")

    if st.button("Прочитать файл и показать preview"):
        try:
            df_src = read_uploaded_file_to_df(uploaded, file_kind, excel_sheet, csv_sep)
            st.session_state["df_src_file"] = df_src
            st.success(f"Файл прочитан. Строк: {len(df_src)} | Колонок: {len(df_src.columns)}")
            ui_log(f"File loaded: rows={len(df_src)} cols={list(df_src.columns)}")
            st.dataframe(df_src.head(int(preview_n)))
        except Exception as e:
            st.error(str(e))
            ui_log(f"File read error: {e}")

    df_src = st.session_state.get("df_src_file")

    if df_src is not None:
        try:
            dst_target_cols, dst_ch_schema = load_destination_schema()
            st.info(f"Колонки назначения ({len(dst_target_cols)}): {dst_target_cols}")
        except Exception as e:
            st.error(str(e))
            ui_log(f"Destination schema error: {e}")
            dst_target_cols, dst_ch_schema = [], {}

        if dst_target_cols:
            mapping = build_mapping_ui(list(df_src.columns), dst_target_cols, key_prefix="file")
            st.divider()

            if st.button("START: загрузить файл → destination"):
                try:
                    # НОВОЕ: START_SET_FLAGS
                    st.session_state["is_loading"] = True
                    st.session_state["cancel_requested"] = False
                    # НОВОЕ: DST_TEST_GUARD
                    ok, msg = dst_adapter.test()
                    if not ok:
                        raise ValueError("Destination test failed:\n" + msg)

                    if not mapping:
                        raise ValueError("Маппинг пустой — выбери хотя бы одну колонку (не skip).")

                    df_load = apply_mapping_df(df_src, mapping)
                    ui_log(f"Prepared df for load: rows={len(df_load)} cols={list(df_load.columns)}")

                    prog = st.progress(0)

                    def progress_cb(done: int, total: int) -> None:
                        prog.progress(min(1.0, done / max(total, 1)))

                    t0 = time.time()

                    if clear_before:
                        if dst_type == "MySQL":
                            ui_log("MySQL: clear_before → DELETE FROM table")
                            dst_adapter.delete_all(dst_table)
                        elif dst_type == "ClickHouse":
                            ui_log("ClickHouse: clear_before → TRUNCATE TABLE")
                            dst_adapter.truncate(dst_table)
                        else:
                            ui_log("Greenplum: clear_before → TRUNCATE TABLE")
                            dst_adapter.truncate(dst_table)

                    if dst_type == "MySQL":
                        inserted = dst_adapter.insert_df(dst_table, df_load, int(batch_size), insert_mode, progress_cb=progress_cb)
                    elif dst_type == "ClickHouse":
                        df_cast, bad = cast_df_to_ch_schema(df_load, dst_ch_schema)
                        if bad:
                            ui_log(f"ClickHouse cast removed rows: {bad}")
                            st.warning(f"Некоторые строки выкинуты (не проходят типы CH): {bad}")
                        if df_cast.empty:
                            raise ValueError("После приведения типов под ClickHouse не осталось строк.")
                        inserted = dst_adapter.insert_df(dst_table, df_cast)
                    else:
                        target_cols_selected = list(mapping.keys())
                        inserted = dst_adapter.copy_df(dst_table, df_load, target_cols_selected, force_lower_gp)

                    dt = time.time() - t0
                    prog.progress(1.0)
                    st.success(f"Готово. Залили строк: {inserted}. Время: {dt:.1f}s")
                    ui_log(f"Done. Inserted={inserted}, time={dt:.1f}s")

                    # НОВОЕ: END_CLEAR_FLAGS
                    st.session_state["is_loading"] = False

                except Exception as e:
                    st.error(str(e))
                    ui_log(f"Load error: {e}")
                    # НОВОЕ: END_CLEAR_FLAGS
                    st.session_state["is_loading"] = False

    st.divider()
    render_logs()


# Query(DB) → DB
if mode == "Query(DB) → DB":
    st.subheader("Источник: SQL запрос → Destination")
    sql = st.text_area("SQL", height=180, placeholder="Например: select ...")

    if st.button("Preview query"):
        try:
            if not sql.strip():
                raise ValueError("SQL пустой.")
            if src_type == "MySQL":
                src_ad = MySQLAdapter(src_params_mysql)
                cnx = src_ad.connect()
                df_prev = mysql_query_preview(cnx, sql, int(preview_n))
                cnx.close()
            elif src_type == "Greenplum":
                src_ad = GPAdapter(src_params_gp)
                cnx = src_ad.connect()
                df_prev = gp_query_preview(cnx, sql, int(preview_n))
                cnx.close()
            else:  # ClickHouse
                src_ad = CHAdapter(src_params_ch)
                client = src_ad.connect()
                df_prev = ch_query_preview(client, sql, int(preview_n))
                client.close()

            st.session_state["df_prev_query"] = df_prev
            st.success(f"Preview OK. Rows: {len(df_prev)}")
            st.dataframe(df_prev)
            ui_log(f"Query preview ok. cols={list(df_prev.columns)} rows={len(df_prev)}")

        except Exception as e:
            st.error(str(e))
            ui_log(f"Query preview error: {e}")

    df_prev = st.session_state.get("df_prev_query")

    if df_prev is not None and not df_prev.empty:
        try:
            dst_target_cols, dst_ch_schema = load_destination_schema()
            st.info(f"Колонки назначения ({len(dst_target_cols)}): {dst_target_cols}")
        except Exception as e:
            st.error(str(e))
            ui_log(f"Destination schema error: {e}")
            dst_target_cols, dst_ch_schema = [], {}

        if dst_target_cols:
            mapping = build_mapping_ui(list(df_prev.columns), dst_target_cols, key_prefix="query")

            limit_for_test = st.number_input(
                "Ограничить заливку первыми N строк (0 = без ограничения)",
                min_value=0,
                max_value=50_000_000,
                value=0,
            )

            if st.button("START: выполнить query → destination"):
                try:
                    # НОВОЕ: START_SET_FLAGS
                    st.session_state["is_loading"] = True
                    st.session_state["cancel_requested"] = False
                    # НОВОЕ: DST_TEST_GUARD
                    ok, msg = dst_adapter.test()
                    if not ok:
                        raise ValueError("Destination test failed:\n" + msg)

                    if not mapping:
                        raise ValueError("Маппинг пустой — выбери хотя бы одну колонку (не skip).")

                    target_cols_selected = list(mapping.keys())
                    source_cols_selected = [mapping[t] for t in target_cols_selected]

                    prog = st.progress(0)
                    t0 = time.time()

                    done = 0
                    cap = int(limit_for_test) if int(limit_for_test) > 0 else None

                    # Open source cursor
                    if src_type == "MySQL":
                        src_ad = MySQLAdapter(src_params_mysql)
                        src_cnx = src_ad.connect()
                        src_cur = mysql_stream_cursor(src_cnx, sql)
                        src_fetch = lambda n: src_cur.fetchmany(n)
                        src_close = lambda: (src_cur.close(), src_cnx.close())
                        src_cols = list(src_cur.column_names)
                    elif src_type == "Greenplum":
                        src_ad = GPAdapter(src_params_gp)
                        src_cnx = src_ad.connect()
                        src_cur = gp_stream_cursor(src_cnx, sql, int(batch_size))
                        src_fetch = lambda n: src_cur.fetchmany(n)
                        src_close = lambda: (src_cur.close(), src_cnx.close())
                        src_cols = [d[0] for d in src_cur.description]
                    else:  # ClickHouse
                        src_ad = CHAdapter(src_params_ch)
                        src_client = src_ad.connect()
                        # Для проверки наличия колонок берём 1 строку
                        _df_cols = ch_query_preview(src_client, sql, 1)
                        src_cols = list(_df_cols.columns)
                        src_iter = ch_iter_chunks_df(src_client, sql, int(batch_size))

                        def src_fetch(_n: int):
                            try:
                                return next(src_iter)
                            except StopIteration:
                                return None

                        src_close = lambda: src_client.close()

                    missing = [c for c in source_cols_selected if c not in src_cols]
                    if missing:
                        src_close()
                        raise ValueError(f"В результате запроса нет колонок: {missing}")

                    try:
                        if clear_before:
                            if dst_type == "MySQL":
                                ui_log("MySQL: clear_before → DELETE FROM table")
                                dst_adapter.delete_all(dst_table)
                            elif dst_type == "ClickHouse":
                                ui_log("ClickHouse: clear_before → TRUNCATE TABLE")
                                dst_adapter.truncate(dst_table)
                            else:
                                ui_log("Greenplum: clear_before → TRUNCATE TABLE")
                                dst_adapter.truncate(dst_table)

                        while True:
                            # НОВОЕ: CANCEL_CHECK
                            if st.session_state.get("cancel_requested", False):
                                ui_log("Остановка: cancel_requested=True")
                                break

                            chunk = src_fetch(int(batch_size))
                            if chunk is None:
                                break

                            # НОВОЕ: FIX_EMPTY_CHUNK_BREAK
                            # mysql/greenplum fetchmany() возвращает [] в конце, не None.
                            if src_type in ("MySQL", "Greenplum") and not chunk:
                                break
                            if src_type == "ClickHouse" and hasattr(chunk, "empty") and chunk.empty:
                                break

                            if cap is not None:
                                remaining = cap - done
                                if remaining <= 0:
                                    break
                                if src_type in ("MySQL", "Greenplum"):
                                    if len(chunk) > remaining:
                                        chunk = chunk[:remaining]
                                else:
                                    # ClickHouse chunk уже DataFrame
                                    if len(chunk) > remaining:
                                        chunk = chunk.head(remaining)

                            if src_type == "MySQL":
                                df_chunk = pd.DataFrame(chunk)
                            elif src_type == "Greenplum":
                                df_chunk = pd.DataFrame(chunk, columns=src_cols)
                            else:
                                df_chunk = chunk

                            df_load = apply_mapping_df(df_chunk, mapping)

                            if dst_type == "MySQL":
                                inserted = dst_adapter.insert_df(dst_table, df_load, int(batch_size), insert_mode)
                            elif dst_type == "ClickHouse":
                                df_cast, bad = cast_df_to_ch_schema(df_load, dst_ch_schema)
                                if bad:
                                    ui_log(f"ClickHouse cast removed rows: {bad}")
                                if df_cast.empty:
                                    done += len(df_chunk)
                                    continue
                                inserted = dst_adapter.insert_df(dst_table, df_cast)
                            else:
                                inserted = dst_adapter.copy_df(dst_table, df_load, target_cols_selected, force_lower_gp)

                            done += len(df_chunk)

                            if cap:
                                prog.progress(min(1.0, done / max(cap, 1)))
                            else:
                                prog.progress((done % 100000) / 100000)

                            ui_log(f"Loaded rows: {done}")

                            if cap is not None and done >= cap:
                                break

                    finally:
                        src_close()

                    prog.progress(1.0)
                    dt = time.time() - t0
                    st.success(f"Готово. Прочитали строк: {done}. Время: {dt:.1f}s")
                    ui_log(f"Done. Read={done}, time={dt:.1f}s")

                    # НОВОЕ: END_CLEAR_FLAGS
                    st.session_state["is_loading"] = False

                except Exception as e:
                    st.error(str(e))
                    ui_log(f"Query load error: {e}")
                    st.session_state["is_loading"] = False

    st.divider()
    render_logs()
