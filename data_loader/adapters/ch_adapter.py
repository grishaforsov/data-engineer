from __future__ import annotations

from typing import Dict, Tuple
import time

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

    def insert_df(self, table: str, df: pd.DataFrame, retry_attempts: int = 3, retry_delay_sec: float = 1.0) -> int:
        if df.empty:
            return 0
        full = table if "." in table else f"{self.p.database}.{table}"
        last_err = None
        for attempt in range(1, int(retry_attempts) + 1):
            client = self.connect()
            try:
                client.insert_df(full, df)
                return len(df)
            except Exception as e:
                last_err = e
                if attempt < int(retry_attempts):
                    time.sleep(float(retry_delay_sec) * attempt)
            finally:
                client.close()
        raise last_err if last_err is not None else RuntimeError("ClickHouse insert failed.")
