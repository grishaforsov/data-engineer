from __future__ import annotations

from typing import Dict, Tuple

import clickhouse_connect
import pandas as pd

from data_loader.core.models import CHParams
from data_loader.core.safety import assert_safe_name


class CHAdapter:
    def __init__(self, p: CHParams):
        self.p = p

    def connect(self):
        return clickhouse_connect.get_client(
            host=self.p.host,
            port=self.p.port,
            username=self.p.user,
            password=self.p.password,
            database=self.p.database,
        )

    def test(self) -> Tuple[bool, str]:
        try:
            client = self.connect()
            client.command("select 1")
            client.close()
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def get_schema(self, table: str) -> Dict[str, str]:
        if "." in table:
            db, tbl = table.split(".", 1)
        else:
            db, tbl = self.p.database, table

        assert_safe_name(db, "database")
        assert_safe_name(tbl, "table")

        client = self.connect()
        try:
            rows = client.query(f"describe table `{db}`.`{tbl}`").result_rows
            return {r[0]: r[1] for r in rows}
        finally:
            client.close()

    def truncate(self, table: str) -> None:
        client = self.connect()
        try:
            full = table if "." in table else f"{self.p.database}.{table}"
            client.command(f"truncate table {full}")
        finally:
            client.close()

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        client = self.connect()
        try:
            full = table if "." in table else f"{self.p.database}.{table}"
            client.insert_df(full, df)
            return len(df)
        finally:
            client.close()