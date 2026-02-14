from __future__ import annotations

import re

# Разрешаем только безопасные имена БД/таблиц/колонок: латиница/цифры/underscore и точка для db.table.
# Это не "пуленепробиваемая безопасность", но защита от мусора и от очевидных SQL-инъекций там,
# где имя таблицы/схемы нельзя передать параметром (а приходится собирать SQL строкой).
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_$.]+$")


def assert_safe_name(name: str, what: str) -> None:
    if not name or not SAFE_NAME_RE.match(name):
        raise ValueError(
            f"Некорректное {what}: '{name}'. Допустимо: буквы/цифры/_, и точка для db.table."
        )
