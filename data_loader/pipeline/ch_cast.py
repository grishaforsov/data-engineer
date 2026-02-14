from __future__ import annotations

import re
from typing import Dict, Tuple
import pandas as pd


def _ch_base_type(ch_type: str) -> str:
    t = ch_type.strip()
    while True:
        m = re.match(r"^(Nullable|LowCardinality)\((.+)\)$", t)
        if not m:
            return t
        t = m.group(2).strip()


def cast_df_to_ch_schema(df: pd.DataFrame, schema: Dict[str, str]) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if df.empty:
        return df, {}

    out = df.copy()
    bad_report: Dict[str, int] = {}

    for col in list(out.columns):
        if col not in schema:
            continue

        ch_t = _ch_base_type(schema[col])

        if ch_t in ("UInt8", "UInt16", "UInt32", "UInt64", "Int8", "Int16", "Int32", "Int64"):
            s = pd.to_numeric(out[col], errors="coerce")

            if ch_t.startswith("UInt"):
                bits = int(ch_t[4:])
                min_v, max_v = 0, 2**bits - 1
            else:
                bits = int(ch_t[3:])
                min_v, max_v = -(2 ** (bits - 1)), 2 ** (bits - 1) - 1

            ok = (~s.isna()) & ((s % 1) == 0) & (s >= min_v) & (s <= max_v)
            bad_cnt = int((~ok).sum())
            if bad_cnt:
                bad_report[col] = bad_cnt

            out = out.loc[ok].copy()
            out[col] = pd.to_numeric(out[col], errors="raise").astype(ch_t.lower())
            continue

        if ch_t in ("Float32", "Float64"):
            s = pd.to_numeric(out[col], errors="coerce")
            ok = ~s.isna()
            bad_cnt = int((~ok).sum())
            if bad_cnt:
                bad_report[col] = bad_cnt
            out = out.loc[ok].copy()
            out[col] = pd.to_numeric(out[col], errors="raise").astype("float32" if ch_t == "Float32" else "float64")
            continue

        if ch_t.startswith("DateTime") or ch_t == "Date":
            s = pd.to_datetime(out[col], errors="coerce")
            ok = ~s.isna()
            bad_cnt = int((~ok).sum())
            if bad_cnt:
                bad_report[col] = bad_cnt
            out = out.loc[ok].copy()
            out[col] = pd.to_datetime(out[col], errors="raise")
            continue

        if ch_t in ("String", "FixedString", "UUID"):
            out[col] = out[col].astype("string")
            continue

    return out, bad_report
