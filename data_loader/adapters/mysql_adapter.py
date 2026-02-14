from __future__ import annotations

from typing import List, Tuple

import mysql.connector
import pandas as pd

from data_loader.core.models import MySQLParams
from data_loader.core.safety import assert_safe_name


class MySQLAdapter:
    def __init__(self, p: MySQLParams):
        self.p = p

    def connect(self):
        return mysql.connector.connect(
            host=self.p.host,
            port=self.p.port,
            user=self.p.user,
            password=self.p.password,
            database=self.p.database,
            autocommit=False,
            connection_timeout=5,
            use_pure=True,
        )

    def test(self) -> Tuple[bool, str]:
        try:
            cnx = self.connect()
            with cnx.cursor() as cur:
                cur.execute("select 1")
                cur.fetchone()
            cnx.close()
            return True, "OK"
        except Exception as e:
            return False, str(e)

    def get_columns(self, table: str) -> List[str]:
        assert_safe_name(table, "table")
        if "." in table:
            db, tbl = table.split(".", 1)
            sql = f"show columns from `{db}`.`{tbl}`"
        else:
            sql = f"show columns from `{table}`"

        cnx = self.connect()
        try:
            cur = cnx.cursor()
            cur.execute(sql)
            cols = [row[0] for row in cur.fetchall()]
            cur.close()
            return cols
        finally:
            cnx.close()

    def delete_all(self, table: str) -> None:
        assert_safe_name(table, "table")
        cnx = self.connect()
        try:
            with cnx.cursor() as cur:
                cur.execute(f"delete from {table};")
            cnx.commit()
        finally:
            cnx.close()

    def insert_df(self, table: str, df: pd.DataFrame, batch_size: int, insert_mode: str, progress_cb=None) -> int:
        assert_safe_name(table, "table")
        if df.empty:
            return 0

        cols = list(df.columns)
        if not cols:
            raise ValueError("После маппинга нет колонок для вставки.")

        cols_sql = ", ".join([f"`{c}`" for c in cols])
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"{insert_mode} into {table} ({cols_sql}) values ({placeholders})"

        rows = list(df.itertuples(index=False, name=None))
        cnx = self.connect()
        cur = cnx.cursor()

        inserted = 0
        try:
            for i in range(0, len(rows), int(batch_size)):
                batch = rows[i : i + int(batch_size)]
                cur.executemany(sql, batch)
                cnx.commit()
                inserted += len(batch)
                if progress_cb:
                    progress_cb(inserted, len(rows))
            return inserted
        except Exception:
            cnx.rollback()
            raise
        finally:
            cur.close()
            cnx.close()
