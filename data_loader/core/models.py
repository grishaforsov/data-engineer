from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MySQLParams:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class CHParams:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class GPParams:
    host: str
    port: int
    dbname: str
    user: str
    password: str
