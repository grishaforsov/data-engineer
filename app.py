import time
from typing import Any

import pandas as pd
import streamlit as st

from data_loader.adapters.ch_adapter import CHAdapter
from data_loader.adapters.gp_adapter import GPAdapter
from data_loader.adapters.mysql_adapter import MySQLAdapter
from data_loader.core.audit import audit_event
from data_loader.core.auth import ensure_auth, load_auth_config, require_role
from data_loader.core.guardrails import (
    enforce_allowlist,
    load_guardrails,
    role_limits,
    require_clear_confirm,
    validate_cap,
    validate_sql,
)
from data_loader.core.models import CHParams, GPParams, MySQLParams
from data_loader.core.ui_log import render_logs, ui_log
from data_loader.pipeline.ch_cast import cast_df_to_ch_schema
from data_loader.pipeline.file_source import read_uploaded_file_to_df
from data_loader.pipeline.mapping import apply_mapping_df, build_mapping_ui
from data_loader.pipeline.query_source import (
    ch_iter_chunks_df,
    ch_query_preview,
    gp_query_preview,
    gp_stream_cursor,
    mysql_query_preview,
    mysql_stream_cursor,
)


st.set_page_config(page_title="Data Loader", layout="wide")
st.title("Data Loader - File -> DB / Query(DB) -> DB")

if "is_loading" not in st.session_state:
    st.session_state["is_loading"] = False
if "cancel_requested" not in st.session_state:
    st.session_state["cancel_requested"] = False

auth = load_auth_config()
actor, role = ensure_auth(auth)
guards = load_guardrails()
limits = role_limits(role)

st.sidebar.subheader("Session")
st.sidebar.write(f"User: `{actor}`")
st.sidebar.write(f"Role: `{role}`")
if limits.max_rows is None:
    st.sidebar.caption("Guardrails: role=admin, no row/time limits")
else:
    st.sidebar.caption(
        f"Guardrails: role=loader, max_rows={limits.max_rows}, max_seconds={limits.max_seconds}"
    )

if st.button("Clear logs"):
    st.session_state["logs"] = []

if st.session_state.get("is_loading", False):
    if st.button("Stop load"):
        st.session_state["cancel_requested"] = True
        st.session_state["is_loading"] = False
        ui_log("Stop requested by user.")
        audit_event("load_stop_requested", {"user": actor, "role": role})
        st.rerun()


def with_audit(event: str, **payload: Any) -> None:
    base = {"user": actor, "role": role}
    base.update(payload)
    audit_event(event, base)


def destination_identity(dst_type: str, p_mysql, p_ch, p_gp) -> tuple[str, str]:
    if dst_type == "MySQL":
        return p_mysql.host, p_mysql.database
    if dst_type == "ClickHouse":
        return p_ch.host, p_ch.database
    return p_gp.host, p_gp.dbname


def source_identity(src_type: str, p_mysql, p_ch, p_gp) -> tuple[str, str]:
    if src_type == "MySQL":
        return p_mysql.host, p_mysql.database
    if src_type == "ClickHouse":
        return p_ch.host, p_ch.database
    return p_gp.host, p_gp.dbname


mode = st.radio("Mode", ["File -> DB", "Query(DB) -> DB"], horizontal=True)
st.divider()

st.subheader("Destination")
dst_type = st.selectbox("Destination DB", ["MySQL", "ClickHouse", "Greenplum"], key="dst_type")
dst_table = st.text_input("Destination table", placeholder="For GP use schema.table")

if role == "admin":
    clear_before = st.checkbox("Clear destination table before load (dangerous)", value=False)
else:
    clear_before = False
    st.caption("Clear-before is available only for admin role.")

clear_confirm = ""
if clear_before:
    clear_confirm = st.text_input("Type destination table name to confirm clear operation", value="")

force_lower_gp = True
if dst_type == "Greenplum":
    force_lower_gp = st.checkbox("Force lower-case destination columns (recommended for GP)", value=True)

dst_params_mysql = None
dst_params_ch = None
dst_params_gp = None

if dst_type == "MySQL":
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        dst_host = st.text_input("Host", key="dst_host_mysql")
    with c2:
        dst_port = st.number_input("Port", min_value=1, max_value=65535, value=3306, key="dst_port_mysql")
    with c3:
        dst_user = st.text_input("User", key="dst_user_mysql")
    with c4:
        dst_password = st.text_input("Password", type="password", key="dst_pass_mysql")
    with c5:
        dst_db = st.text_input("Database", value="bukmaker", key="dst_db_mysql")
    dst_params_mysql = MySQLParams(dst_host, int(dst_port), dst_user, dst_password, dst_db)
elif dst_type == "ClickHouse":
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        dst_host = st.text_input("Host", key="dst_host_ch")
    with c2:
        dst_port = st.number_input("Port", min_value=1, max_value=65535, value=8123, key="dst_port_ch")
    with c3:
        dst_user = st.text_input("User", key="dst_user_ch")
    with c4:
        dst_password = st.text_input("Password", type="password", key="dst_pass_ch")
    with c5:
        dst_db = st.text_input("Database", value="analytics_tmp", key="dst_db_ch")
    dst_params_ch = CHParams(dst_host, int(dst_port), dst_user, dst_password, dst_db)
else:
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        dst_host = st.text_input("Host", key="dst_host_gp")
    with c2:
        dst_port = st.number_input("Port", min_value=1, max_value=65535, value=5432, key="dst_port_gp")
    with c3:
        dst_db = st.text_input("DB name", value="dwh", key="dst_db_gp")
    with c4:
        dst_user = st.text_input("User", key="dst_user_gp")
    with c5:
        dst_password = st.text_input("Password", type="password", key="dst_pass_gp")
    dst_params_gp = GPParams(dst_host, int(dst_port), dst_db, dst_user, dst_password)


def make_dst_adapter():
    if dst_type == "MySQL":
        return MySQLAdapter(dst_params_mysql)
    if dst_type == "ClickHouse":
        return CHAdapter(dst_params_ch)
    return GPAdapter(dst_params_gp)


def check_destination_policy() -> None:
    host, db_name = destination_identity(dst_type, dst_params_mysql, dst_params_ch, dst_params_gp)
    enforce_allowlist("Destination host", host, guards.allowed_dst_hosts)
    enforce_allowlist("Destination database", db_name, guards.allowed_dst_dbs)


dst_adapter = make_dst_adapter()

if st.button("Test destination"):
    try:
        check_destination_policy()
        ok, msg = dst_adapter.test()
        with_audit("dst_test", db=dst_type, ok=ok, message=msg)
        if ok:
            st.success("Destination: OK")
            ui_log("Destination connection: OK")
        else:
            st.error(f"Destination error: {msg}")
            ui_log(f"Destination connection error: {msg}")
    except Exception as e:
        st.error(str(e))
        ui_log(f"Destination policy error: {e}")
        with_audit("dst_policy_reject", db=dst_type, message=str(e))

st.divider()

st.subheader("Load settings")
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

src_type = None
src_params_mysql = None
src_params_gp = None
src_params_ch = None

if mode == "Query(DB) -> DB":
    st.subheader("Source")
    src_type = st.selectbox("Source DB", ["MySQL", "Greenplum", "ClickHouse"], key="src_type")

    if src_type == "MySQL":
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            src_host = st.text_input("Host", key="src_host_mysql")
        with s2:
            src_port = st.number_input("Port", min_value=1, max_value=65535, value=3306, key="src_port_mysql")
        with s3:
            src_user = st.text_input("User", key="src_user_mysql")
        with s4:
            src_password = st.text_input("Password", type="password", key="src_pass_mysql")
        with s5:
            src_db = st.text_input("Database", value="bukmaker", key="src_db_mysql")
        src_params_mysql = MySQLParams(src_host, int(src_port), src_user, src_password, src_db)
    elif src_type == "Greenplum":
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            src_host = st.text_input("Host", key="src_host_gp")
        with s2:
            src_port = st.number_input("Port", min_value=1, max_value=65535, value=5432, key="src_port_gp")
        with s3:
            src_db = st.text_input("DB name", value="dwh", key="src_db_gp")
        with s4:
            src_user = st.text_input("User", key="src_user_gp")
        with s5:
            src_password = st.text_input("Password", type="password", key="src_pass_gp")
        src_params_gp = GPParams(src_host, int(src_port), src_db, src_user, src_password)
    else:
        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            src_host = st.text_input("Host", key="src_host_ch")
        with s2:
            src_port = st.number_input("Port", min_value=1, max_value=65535, value=8123, key="src_port_ch")
        with s3:
            src_user = st.text_input("User", key="src_user_ch")
        with s4:
            src_password = st.text_input("Password", type="password", key="src_pass_ch")
        with s5:
            src_db = st.text_input("Database", value="analytics_tmp", key="src_db_ch")
        src_params_ch = CHParams(src_host, int(src_port), src_user, src_password, src_db)

    def check_source_policy() -> None:
        host, db_name = source_identity(src_type, src_params_mysql, src_params_ch, src_params_gp)
        enforce_allowlist("Source host", host, guards.allowed_src_hosts)
        enforce_allowlist("Source database", db_name, guards.allowed_src_dbs)

    if st.button("Test source"):
        try:
            check_source_policy()
            if src_type == "MySQL":
                ok, msg = MySQLAdapter(src_params_mysql).test()
            elif src_type == "Greenplum":
                ok, msg = GPAdapter(src_params_gp).test()
            else:
                ok, msg = CHAdapter(src_params_ch).test()
            with_audit("src_test", db=src_type, ok=ok, message=msg)
            if ok:
                st.success("Source: OK")
                ui_log("Source connection: OK")
            else:
                st.error(f"Source error: {msg}")
                ui_log(f"Source connection error: {msg}")
        except Exception as e:
            st.error(str(e))
            ui_log(f"Source policy error: {e}")
            with_audit("src_policy_reject", db=src_type, message=str(e))

    st.divider()


def load_destination_schema():
    if not dst_table:
        raise ValueError("Destination table is empty.")

    if dst_type == "MySQL":
        cols = dst_adapter.get_columns(dst_table)
        return cols, {}

    if dst_type == "ClickHouse":
        schema = dst_adapter.get_schema(dst_table)
        return list(schema.keys()), schema

    cols = dst_adapter.get_columns(dst_table)
    return cols, {}


def maybe_clear_destination() -> None:
    if not clear_before:
        return
    require_role(role, {"admin"})
    require_clear_confirm(clear_before, dst_table, clear_confirm)

    if dst_type == "MySQL":
        ui_log("MySQL clear_before -> DELETE FROM")
        dst_adapter.delete_all(dst_table)
    elif dst_type == "ClickHouse":
        ui_log("ClickHouse clear_before -> TRUNCATE TABLE")
        dst_adapter.truncate(dst_table)
    else:
        ui_log("Greenplum clear_before -> TRUNCATE TABLE")
        dst_adapter.truncate(dst_table)


if mode == "File -> DB":
    st.subheader("Source: file (Excel/CSV)")
    file_kind = st.selectbox("File type", ["Excel (.xlsx)", "CSV (.csv)"])
    uploaded = st.file_uploader("Choose file", type=["xlsx", "csv"])

    excel_sheet = None
    csv_sep = ","
    if file_kind == "Excel (.xlsx)":
        excel_sheet = st.text_input("Excel sheet (empty = first)", value="").strip() or None
    else:
        csv_sep = st.text_input("CSV separator", value=",")

    if st.button("Read file and show preview"):
        try:
            df_src = read_uploaded_file_to_df(uploaded, file_kind, excel_sheet, csv_sep)
            st.session_state["df_src_file"] = df_src
            st.success(f"File loaded. Rows: {len(df_src)} | Cols: {len(df_src.columns)}")
            ui_log(f"File loaded: rows={len(df_src)} cols={list(df_src.columns)}")
            with_audit("file_preview", rows=len(df_src), cols=list(df_src.columns))
            st.dataframe(df_src.head(int(preview_n)))
        except Exception as e:
            st.error(str(e))
            ui_log(f"File read error: {e}")
            with_audit("file_preview_error", message=str(e))

    df_src = st.session_state.get("df_src_file")

    if df_src is not None:
        try:
            check_destination_policy()
            dst_target_cols, dst_ch_schema = load_destination_schema()
            st.info(f"Destination columns ({len(dst_target_cols)}): {dst_target_cols}")
        except Exception as e:
            st.error(str(e))
            ui_log(f"Destination schema error: {e}")
            dst_target_cols, dst_ch_schema = [], {}

        if dst_target_cols:
            mapping = build_mapping_ui(list(df_src.columns), dst_target_cols, key_prefix="file")
            st.divider()

            dry_run = st.button("Dry run: validate file -> destination")
            start_load = st.button("START: load file -> destination")
            if dry_run or start_load:
                try:
                    require_role(role, {"loader", "admin"})
                    st.session_state["is_loading"] = True
                    st.session_state["cancel_requested"] = False

                    ok, msg = dst_adapter.test()
                    if not ok:
                        raise ValueError("Destination test failed:\n" + msg)

                    if not mapping:
                        raise ValueError("Mapping is empty. Select at least one column.")

                    df_load = apply_mapping_df(df_src, mapping)
                    ui_log(f"Prepared df: rows={len(df_load)} cols={list(df_load.columns)}")

                    if dst_type == "ClickHouse":
                        df_cast, bad = cast_df_to_ch_schema(df_load, dst_ch_schema)
                        if bad:
                            ui_log(f"ClickHouse cast removed rows: {bad}")
                        effective_rows = len(df_cast)
                    else:
                        effective_rows = len(df_load)

                    if limits.max_rows is not None and effective_rows > limits.max_rows:
                        raise ValueError(
                            f"Rows exceed loader limit: {effective_rows} > {limits.max_rows}"
                        )

                    if dry_run:
                        st.success(f"Dry run OK. Rows ready for load: {effective_rows}")
                        with_audit(
                            "file_dry_run",
                            dst_type=dst_type,
                            table=dst_table,
                            rows=effective_rows,
                        )
                    else:
                        maybe_clear_destination()
                        prog = st.progress(0)
                        status = st.empty()

                        t0 = time.time()
                        with_audit("file_load_start", dst_type=dst_type, table=dst_table, rows=effective_rows)
                        inserted = 0
                        total = effective_rows
                        target_cols_selected = list(mapping.keys())

                        work_df = df_load
                        if dst_type == "ClickHouse":
                            if df_cast.empty:
                                raise ValueError("No rows left after ClickHouse casting.")
                            work_df = df_cast

                        for i in range(0, len(work_df), int(batch_size)):
                            if st.session_state.get("cancel_requested", False):
                                ui_log("Stop: cancel_requested=True")
                                break

                            if limits.max_seconds is not None and (time.time() - t0) > limits.max_seconds:
                                raise TimeoutError(f"File load exceeded timeout ({limits.max_seconds}s).")

                            chunk = work_df.iloc[i : i + int(batch_size)]
                            if chunk.empty:
                                continue

                            if dst_type == "MySQL":
                                dst_adapter.insert_df(
                                    dst_table,
                                    chunk,
                                    len(chunk),
                                    insert_mode,
                                )
                            elif dst_type == "ClickHouse":
                                dst_adapter.insert_df(dst_table, chunk)
                            else:
                                dst_adapter.copy_df(dst_table, chunk, target_cols_selected, force_lower_gp)

                            inserted += len(chunk)
                            prog.progress(min(1.0, inserted / max(total, 1)))
                            status.info(f"Loaded rows: {inserted}/{total}")

                        dt = time.time() - t0
                        prog.progress(1.0)
                        status.info(f"Loaded rows total: {inserted}/{total}")
                        st.success(f"Done. Inserted rows: {inserted}. Time: {dt:.1f}s")
                        ui_log(f"Done. Inserted={inserted}, time={dt:.1f}s")
                        with_audit(
                            "file_load_done",
                            dst_type=dst_type,
                            table=dst_table,
                            inserted=inserted,
                            seconds=round(dt, 1),
                        )

                    st.session_state["is_loading"] = False
                except Exception as e:
                    st.error(str(e))
                    ui_log(f"File load error: {e}")
                    with_audit("file_load_error", dst_type=dst_type, table=dst_table, message=str(e))
                    st.session_state["is_loading"] = False

    st.divider()
    render_logs()


if mode == "Query(DB) -> DB":
    st.subheader("Source: SQL query -> destination")
    sql_raw = st.text_area("SQL", height=180, placeholder="Example: select ...")
    ch_sort_key = None
    if src_type == "ClickHouse":
        ch_sort_key = st.text_input(
            "ClickHouse keyset column (optional, recommended for large loads)",
            value="",
            help="If set, query will use keyset pagination instead of LIMIT/OFFSET.",
        ).strip() or None

    query_cap = st.number_input(
        "Max rows to load in this run (0 = no cap for admin, loader capped by role)",
        min_value=0,
        max_value=max(limits.max_rows or guards.max_query_rows, 1),
        value=min(200000, limits.max_rows or guards.max_query_rows),
    )

    if st.button("Preview query"):
        try:
            check_source_policy()
            sql = validate_sql(sql_raw, guards.allow_only_select)
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
            else:
                src_ad = CHAdapter(src_params_ch)
                client = src_ad.connect()
                df_prev = ch_query_preview(client, sql, int(preview_n))
                client.close()

            st.session_state["df_prev_query"] = df_prev
            st.success(f"Preview OK. Rows: {len(df_prev)}")
            st.dataframe(df_prev)
            ui_log(f"Query preview ok. cols={list(df_prev.columns)} rows={len(df_prev)}")
            with_audit("query_preview", src_type=src_type, rows=len(df_prev))
        except Exception as e:
            st.error(str(e))
            ui_log(f"Query preview error: {e}")
            with_audit("query_preview_error", src_type=src_type, message=str(e))

    df_prev = st.session_state.get("df_prev_query")

    if df_prev is not None and not df_prev.empty:
        try:
            check_destination_policy()
            dst_target_cols, dst_ch_schema = load_destination_schema()
            st.info(f"Destination columns ({len(dst_target_cols)}): {dst_target_cols}")
        except Exception as e:
            st.error(str(e))
            ui_log(f"Destination schema error: {e}")
            dst_target_cols, dst_ch_schema = [], {}

        if dst_target_cols:
            mapping = build_mapping_ui(list(df_prev.columns), dst_target_cols, key_prefix="query")

            dry_run = st.button("Dry run: validate query -> destination")
            start_load = st.button("START: run query -> destination")
            if dry_run or start_load:
                try:
                    require_role(role, {"loader", "admin"})
                    check_source_policy()
                    check_destination_policy()
                    sql = validate_sql(sql_raw, guards.allow_only_select)
                    if limits.max_rows is not None:
                        validate_cap(int(query_cap), limits.max_rows)

                    st.session_state["is_loading"] = True
                    st.session_state["cancel_requested"] = False

                    ok, msg = dst_adapter.test()
                    if not ok:
                        raise ValueError("Destination test failed:\n" + msg)

                    if not mapping:
                        raise ValueError("Mapping is empty. Select at least one column.")

                    target_cols_selected = list(mapping.keys())
                    source_cols_selected = [mapping[t] for t in target_cols_selected]

                    if dry_run:
                        st.success("Dry run OK. Query and mapping validated.")
                        with_audit(
                            "query_dry_run",
                            src_type=src_type,
                            dst_type=dst_type,
                            table=dst_table,
                            query_cap=int(query_cap),
                        )
                        st.session_state["is_loading"] = False
                    else:
                        prog = st.progress(0)
                        status = st.empty()
                        t0 = time.time()
                        done = 0
                        cap = int(query_cap) if int(query_cap) > 0 else None
                        if limits.max_rows is not None and cap is None:
                            cap = limits.max_rows
                        with_audit(
                            "query_load_start",
                            src_type=src_type,
                            dst_type=dst_type,
                            table=dst_table,
                            cap=cap,
                        )

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
                        else:
                            src_ad = CHAdapter(src_params_ch)
                            src_client = src_ad.connect()
                            _df_cols = ch_query_preview(src_client, sql, 1)
                            src_cols = list(_df_cols.columns)
                            src_iter = ch_iter_chunks_df(src_client, sql, int(batch_size), sort_key=ch_sort_key)

                            def src_fetch(_n: int):
                                try:
                                    return next(src_iter)
                                except StopIteration:
                                    return None

                            src_close = lambda: src_client.close()

                        missing = [c for c in source_cols_selected if c not in src_cols]
                        if missing:
                            src_close()
                            raise ValueError(f"Missing columns in query result: {missing}")

                        if src_type == "ClickHouse" and ch_sort_key and ch_sort_key not in src_cols:
                            src_close()
                            raise ValueError(f"ClickHouse keyset column is missing in query result: {ch_sort_key}")

                        try:
                            maybe_clear_destination()
                            while True:
                                if st.session_state.get("cancel_requested", False):
                                    ui_log("Stop: cancel_requested=True")
                                    break

                                if limits.max_seconds is not None and (time.time() - t0) > limits.max_seconds:
                                    raise TimeoutError(
                                        f"Query load exceeded timeout ({limits.max_seconds}s)."
                                    )

                                chunk = src_fetch(int(batch_size))
                                if chunk is None:
                                    break
                                if src_type in ("MySQL", "Greenplum") and not chunk:
                                    break
                                if src_type == "ClickHouse" and hasattr(chunk, "empty") and chunk.empty:
                                    break

                                if cap is not None:
                                    remaining = cap - done
                                    if remaining <= 0:
                                        break
                                    if src_type in ("MySQL", "Greenplum") and len(chunk) > remaining:
                                        chunk = chunk[:remaining]
                                    if src_type == "ClickHouse" and len(chunk) > remaining:
                                        chunk = chunk.head(remaining)

                                if src_type == "MySQL":
                                    df_chunk = pd.DataFrame(chunk)
                                elif src_type == "Greenplum":
                                    df_chunk = pd.DataFrame(chunk, columns=src_cols)
                                else:
                                    df_chunk = chunk

                                df_load = apply_mapping_df(df_chunk, mapping)

                                if dst_type == "MySQL":
                                    dst_adapter.insert_df(dst_table, df_load, int(batch_size), insert_mode)
                                elif dst_type == "ClickHouse":
                                    df_cast, bad = cast_df_to_ch_schema(df_load, dst_ch_schema)
                                    if bad:
                                        ui_log(f"ClickHouse cast removed rows: {bad}")
                                    if not df_cast.empty:
                                        dst_adapter.insert_df(dst_table, df_cast)
                                else:
                                    dst_adapter.copy_df(
                                        dst_table, df_load, target_cols_selected, force_lower_gp
                                    )

                                done += len(df_chunk)
                                if cap:
                                    prog.progress(min(1.0, done / max(cap, 1)))
                                    status.info(f"Loaded rows: {done}/{cap}")
                                else:
                                    status.info(f"Loaded rows: {done} (total unknown)")
                                ui_log(f"Loaded rows: {done}")

                                if cap is not None and done >= cap:
                                    break
                        finally:
                            src_close()

                        prog.progress(1.0)
                        status.info(f"Loaded rows total: {done}")
                        dt = time.time() - t0
                        st.success(f"Done. Read rows: {done}. Time: {dt:.1f}s")
                        ui_log(f"Done. Read={done}, time={dt:.1f}s")
                        with_audit(
                            "query_load_done",
                            src_type=src_type,
                            dst_type=dst_type,
                            table=dst_table,
                            rows=done,
                            seconds=round(dt, 1),
                        )
                        st.session_state["is_loading"] = False
                except Exception as e:
                    st.error(str(e))
                    ui_log(f"Query load error: {e}")
                    with_audit(
                        "query_load_error",
                        src_type=src_type,
                        dst_type=dst_type,
                        table=dst_table,
                        message=str(e),
                    )
                    st.session_state["is_loading"] = False

    st.divider()
    render_logs()
