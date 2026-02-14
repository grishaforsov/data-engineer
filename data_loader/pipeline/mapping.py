from __future__ import annotations

from typing import Dict, List
import streamlit as st
import pandas as pd


# НОВОЕ: APPLY_MAPPING_BUTTON
# В Streamlit значение виджета с одинаковым key живёт в session_state и переживает перезапуски.
# Поэтому простой "index=default_index" не всегда срабатывает: если пользователь ранее уже видел эти selectbox'ы,
# Streamlit возьмёт старое значение из session_state и проигнорирует дефолт.
# Кнопка "Применить автомаппинг" принудительно проставляет значения в session_state.
def build_mapping_ui(source_cols: List[str], target_cols: List[str], key_prefix: str) -> Dict[str, str]:
    st.caption("Маппинг: для каждой колонки назначения выбери колонку источника. Если не нужно — (skip).")

    auto = st.checkbox("Автомаппинг по совпадению имён", value=True, key=f"{key_prefix}_auto")
    source_lower = {c.lower(): c for c in source_cols}

    if st.button("Применить автомаппинг", key=f"{key_prefix}_apply_automap"):
        for tcol in target_cols:
            if tcol.lower() in source_lower:
                st.session_state[f"{key_prefix}_map_{tcol}"] = source_lower[tcol.lower()]
            else:
                st.session_state[f"{key_prefix}_map_{tcol}"] = "(skip)"
        st.rerun()

    mapping: Dict[str, str] = {}
    for tcol in target_cols:
        options = ["(skip)"] + source_cols
        default_index = 0
        if auto and tcol.lower() in source_lower:
            default_index = options.index(source_lower[tcol.lower()])

        choice = st.selectbox(
            f"target: {tcol}",
            options,
            index=default_index,
            key=f"{key_prefix}_map_{tcol}",
        )
        if choice != "(skip)":
            mapping[tcol] = choice

    if not mapping:
        st.warning("Маппинг пустой — заливать нечего.")

    return mapping


def apply_mapping_df(df, mapping: Dict[str, str]) -> pd.DataFrame:
    # НОВОЕ: APPLY_MAPPING_DF_ROBUST
    # Нормализуем имена колонок (строки + strip), чтобы избежать ложных "нет колонки" из-за пробелов.
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Готовим быстрый case-insensitive lookup: lower(name) -> real name
    lower_map = {str(c).strip().lower(): str(c).strip() for c in df.columns}

    data: Dict[str, pd.Series] = {}

    for tcol, scol_raw in mapping.items():
        scol = str(scol_raw).strip()

        if scol in df.columns:
            data[tcol] = df[scol]
            continue

        alt = lower_map.get(scol.lower())
        if alt is not None:
            data[tcol] = df[alt]
            continue

        # Показываем пользователю контекст, чтобы было понятно, что именно пришло в df_chunk
        raise ValueError(
            f"В источнике нет колонки '{scol_raw}' (проверь маппинг). "
            f"Доступные колонки: {list(df.columns)}"
        )

    return pd.DataFrame(data)
