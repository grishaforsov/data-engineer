from __future__ import annotations

from typing import Optional
import pandas as pd


def read_uploaded_file_to_df(
    uploaded_file,
    file_kind: str,
    excel_sheet: Optional[str],
    csv_sep: str,
) -> pd.DataFrame:
    if uploaded_file is None:
        raise ValueError("Файл не выбран.")

    if file_kind == "Excel (.xlsx)":
        return pd.read_excel(uploaded_file, sheet_name=excel_sheet or 0, engine="openpyxl")

    if file_kind == "CSV (.csv)":
        return pd.read_csv(uploaded_file, sep=csv_sep)

    raise ValueError("Неизвестный тип файла.")
