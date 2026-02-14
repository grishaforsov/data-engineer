from __future__ import annotations

from typing import List, Tuple
import io
import time

import psycopg2
import pandas as pd

from data_loader.core.models import GPParams
from data_loader.core.safety import assert_safe_name


class GPAdapter:
    def __init__(self, p: GPParams):
        self.p = p

    def connect(self):
        cnx = psycopg2.connect(
            host=self.p.host,
            port=self.p.port,
            dbname=self.p.dbname,
            user=self.p.user,
            password=self.p.password,
        )
        cnx.autocommit = False
        return cnx

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
        if "." not in table:
            raise ValueError("Для Greenplum укажи таблицу как schema.table (например dev_db.table_test).")

        schema, tbl = table.split(".", 1)
        assert_safe_name(schema, "schema")
        assert_safe_name(tbl, "table")

        sql = """
        select column_name
        from information_schema.columns
        where table_schema = %s
          and table_name = %s
        order by ordinal_position
        """

        cnx = self.connect()
        try:
            with cnx.cursor() as cur:
                cur.execute(sql, (schema, tbl))
                return [r[0] for r in cur.fetchall()]
        finally:
            cnx.close()

    def truncate(self, table: str) -> None:
        assert_safe_name(table, "table")
        cnx = self.connect()
        try:
            with cnx.cursor() as cur:
                cur.execute(f"truncate table {table};")
            cnx.commit()
        finally:
            cnx.close()

    def copy_df(
        self,
        table: str,
        df: pd.DataFrame,
        target_cols: List[str],
        force_lower_cols: bool,
        retry_attempts: int = 3,
        retry_delay_sec: float = 1.0,
    ) -> int:
        assert_safe_name(table, "table")
        if df.empty:
            return 0

        work = df.copy()

        if force_lower_cols:
            work.columns = [c.lower() for c in work.columns]
            target_cols = [c.lower() for c in target_cols]

        missing = [c for c in target_cols if c not in work.columns]
        if missing:
            raise ValueError(f"В DataFrame не хватает колонок для GP COPY: {missing}")

        work = work[target_cols]

        buf = io.StringIO()
        work.to_csv(buf, index=False, header=False, na_rep="")
        buf.seek(0)

        copy_sql = f"""
        copy {table} ({", ".join(target_cols)})
        from stdin with (format csv, header false, null '', delimiter ',', quote '"', escape '"')
        """

        last_err = None
        for attempt in range(1, int(retry_attempts) + 1):
            cnx = self.connect()
            try:
                buf.seek(0)
                with cnx.cursor() as cur:
                    cur.copy_expert(copy_sql, buf)
                cnx.commit()
                return len(work)
            except Exception as e:
                last_err = e
                cnx.rollback()
                if attempt < int(retry_attempts):
                    time.sleep(float(retry_delay_sec) * attempt)
            finally:
                cnx.close()

        raise last_err if last_err is not None else RuntimeError("GP copy failed.")
