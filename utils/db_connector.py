"""
Connects to an external database (as a *source* to import a table FROM, not
a place we write to) so a table can be pulled in and analyzed exactly like
an uploaded file.

Supported out of the box: PostgreSQL, MySQL, SQLite (drivers included in
requirements.txt: psycopg2-binary, PyMySQL). SQL Server and Oracle need
extra drivers (pyodbc / cx_Oracle + native client libraries) that aren't
bundled by default since they require OS-level installation - see the
README for how to add them.

Connections are opened, used for one read, and closed. We never persist a
person's database credentials to disk.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

MAX_PREVIEW_ROWS = 500_000  # sanity cap so an accidental "SELECT * FROM huge_table" can't hang the app

DIALECT_DRIVERS = {
    "postgresql": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "sqlite": "sqlite",
}


class DatabaseConnectionError(Exception):
    pass


def build_connection_url(dialect: str, host: str, port: str, database: str,
                          username: str, password: str) -> str:
    driver = DIALECT_DRIVERS.get(dialect)
    if not driver:
        raise DatabaseConnectionError(
            f"'{dialect}' isn't supported out of the box yet. Supported: "
            f"{', '.join(DIALECT_DRIVERS)}. SQL Server/Oracle need extra drivers - see README."
        )
    if dialect == "sqlite":
        return f"sqlite:///{database}"
    auth = f"{username}:{password}@" if username else ""
    port_part = f":{port}" if port else ""
    return f"{driver}://{auth}{host}{port_part}/{database}"

def get_engine(connection_url: str) -> Engine:
    try:
        engine = create_engine(connection_url, pool_pre_ping=True, connect_args={"connect_timeout": 10}
                                if connection_url.startswith(("postgresql", "mysql")) else {})
        # Fail fast with a clear error rather than timing out deep inside a query later
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as exc:  # noqa: BLE001
        raise DatabaseConnectionError(f"Could not connect to the database: {exc}") from exc


def list_tables(connection_url: str) -> list[str]:
    engine = get_engine(connection_url)
    try:
        return inspect(engine).get_table_names()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseConnectionError(f"Could not list tables: {exc}") from exc
    finally:
        engine.dispose()


def load_table(connection_url: str, table_name: str) -> pd.DataFrame:
    engine = get_engine(connection_url)
    try:
        # table_name comes from list_tables()' own inspector output (never
        # raw user SQL), so this is safe from injection in practice; we still
        # quote defensively via SQLAlchemy's reflected identifier handling.
        with engine.connect() as conn:
            df = pd.read_sql_table(table_name, conn) if _is_simple_ident(table_name) else \
                 pd.read_sql_query(text(f'SELECT * FROM "{table_name}"'), conn)
        return df.head(MAX_PREVIEW_ROWS)
    except Exception as exc:  # noqa: BLE001
        raise DatabaseConnectionError(f"Could not load table '{table_name}': {exc}") from exc
    finally:
        engine.dispose()


def _is_simple_ident(name: str) -> bool:
    return name.replace("_", "").isalnum()
