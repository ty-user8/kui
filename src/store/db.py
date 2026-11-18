"""SQLite 连接、迁移执行与事务。

数据库路径只从环境变量读取（`db.path_env`），本模块不接受硬编码路径。
"""

from __future__ import annotations

import contextlib
import pathlib
import sqlite3
from typing import Iterator

MIGRATION_GLOB = "*.sql"


def connect(db_path: pathlib.Path | str) -> sqlite3.Connection:
    """打开连接，启用外键与行级工厂；父目录不存在时创建。"""
    path = pathlib.Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def apply_migrations(conn: sqlite3.Connection, migrations_dir: pathlib.Path) -> list[int]:
    """按文件名顺序执行迁移脚本，返回本次新应用的版本号。

    脚本内部已使用 `CREATE TABLE IF NOT EXISTS` 与 `INSERT OR IGNORE`，重复执行安全。
    """
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")} if _has_table(
        conn, "schema_migrations"
    ) else set()
    new_versions: list[int] = []
    for script in sorted(migrations_dir.glob(MIGRATION_GLOB)):
        version = int(script.name.split("_", 1)[0])
        conn.executescript(script.read_text(encoding="utf-8"))
        if version not in applied:
            new_versions.append(version)
    return new_versions


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """显式事务：异常回滚，正常提交。"""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
