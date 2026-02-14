from __future__ import annotations

from typing import Iterator
import pandas as pd


def mysql_query_preview(cnx, sql: str, limit: int) -> pd.DataFrame:
    sql = sql.strip().rstrip(";")
    preview_sql = f"select * from ({sql}) as t limit {int(limit)}"
    cur = cnx.cursor(dictionary=True)
    cur.execute(preview_sql)
    data = cur.fetchall()
    cur.close()
    df = pd.DataFrame(data)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def mysql_stream_cursor(cnx, sql: str):
    sql = sql.strip().rstrip(";")
    cur = cnx.cursor(dictionary=True)
    cur.execute(sql)
    return cur


def gp_query_preview(cnx, sql: str, limit: int) -> pd.DataFrame:
    sql = sql.strip().rstrip(";")
    preview_sql = f"select * from ({sql}) t limit {int(limit)}"
    df = pd.read_sql_query(preview_sql, cnx)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def gp_stream_cursor(cnx, sql: str, fetch_size: int):
    sql = sql.strip().rstrip(";")
    cur = cnx.cursor(name="stream_cursor")
    cur.itersize = int(fetch_size)
    cur.execute(sql)
    return cur


def ch_query_preview(client, sql: str, limit: int) -> pd.DataFrame:
    """Preview для ClickHouse.

    Почему так: clickhouse-connect умеет возвращать результат как pandas.DataFrame, но нам нужно
    поддержать любой пользовательский SELECT. Поэтому оборачиваем запрос в подзапрос и ставим LIMIT.
    """
    sql = sql.strip().rstrip(";")
    preview_sql = f"select * from ({sql}) limit {int(limit)}"
    df = client.query_df(preview_sql)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def ch_iter_chunks_df(client, sql: str, chunk_size: int) -> Iterator[pd.DataFrame]:
    """Итератор чанков для ClickHouse.

    В MySQL/GP можно использовать server-side cursor. В clickhouse-connect это не так удобно,
    поэтому делаем безопасную схему через LIMIT/OFFSET.

    Ограничение: большие OFFSET могут быть медленными. Для очень больших выгрузок лучше
    сразу писать запрос с собственной пагинацией (например по dt/id) и прогонять по диапазонам.
    """
    sql = sql.strip().rstrip(";")
    offset = 0
    while True:
        chunk_sql = f"select * from ({sql}) limit {int(chunk_size)} offset {int(offset)}"
        df = client.query_df(chunk_sql)
        if df is None or df.empty:
            break
        yield df
        offset += len(df)
