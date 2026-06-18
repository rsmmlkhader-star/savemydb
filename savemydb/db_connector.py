"""
db_connector.py — SaveMyDB
Handles connections to MySQL, PostgreSQL, and SQL Server.
"""

from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Base class
# ─────────────────────────────────────────────

class BaseConnector(ABC):
    """Abstract base for all database connectors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._conn = None

    # ── lifecycle ──────────────────────────────

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @contextmanager
    def connection(self) -> Generator:
        self.connect()
        try:
            yield self
        finally:
            self.disconnect()

    # ── schema helpers ─────────────────────────

    @abstractmethod
    def get_tables(self) -> List[str]: ...

    @abstractmethod
    def get_schema(self, table: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_primary_keys(self, table: str) -> List[str]: ...

    # ── data helpers ───────────────────────────

    @abstractmethod
    def fetch_all(
        self,
        table: str,
        limit: int = 10_000,
        offset: int = 0,
        where: str = "",
    ) -> Tuple[List[str], List[List[Any]]]: ...

    @abstractmethod
    def execute_many(self, sql: str, params: List[Tuple]) -> int: ...

    @abstractmethod
    def execute(self, sql: str, params: Tuple = ()) -> Any: ...

    # ── audit table ────────────────────────────

    def ensure_audit_table(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS savemydb_audit_log (
            id          BIGINT AUTO_INCREMENT PRIMARY KEY,
            table_name  VARCHAR(128)  NOT NULL,
            row_id      VARCHAR(512)  NOT NULL,
            operation   VARCHAR(10)   NOT NULL,
            changed_by  VARCHAR(128),
            changed_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            old_value   TEXT,
            new_value   TEXT
        )
        """
        try:
            self.execute(sql)
            logger.info("Audit table ready.")
        except Exception as exc:
            logger.warning("Could not create audit table: %s", exc)

    def log_audit(
        self,
        table_name: str,
        row_id: str,
        operation: str,
        changed_by: str = "savemydb",
        old_value: str = "",
        new_value: str = "",
    ) -> None:
        sql = """
        INSERT INTO savemydb_audit_log
            (table_name, row_id, operation, changed_by, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        try:
            self.execute(sql, (table_name, row_id, operation,
                                changed_by, old_value, new_value))
        except Exception as exc:
            logger.warning("Audit log failed: %s", exc)


# ─────────────────────────────────────────────
# MySQL
# ─────────────────────────────────────────────

class MySQLConnector(BaseConnector):
    """Connector for MySQL / MariaDB using mysql-connector-python."""

    def connect(self) -> None:
        import mysql.connector  # type: ignore
        self._conn = mysql.connector.connect(
            host=self.config.get("host", "localhost"),
            port=int(self.config.get("port", 3306)),
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
            autocommit=False,
        )
        logger.info("MySQL connected to %s@%s", self.config["database"],
                    self.config.get("host"))

    def disconnect(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def get_tables(self) -> List[str]:
        _, rows = self._query("SHOW TABLES")
        return [r[0] for r in rows]

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        _, rows = self._query(f"DESCRIBE `{table}`")
        return [
            {"column": r[0], "type": r[1], "nullable": r[2] == "YES",
             "key": r[3], "default": r[4]}
            for r in rows
        ]

    def get_primary_keys(self, table: str) -> List[str]:
        return [c["column"] for c in self.get_schema(table) if c["key"] == "PRI"]

    def fetch_all(self, table, limit=10_000, offset=0, where=""):
        clause = f"WHERE {where}" if where else ""
        sql = f"SELECT * FROM `{table}` {clause} LIMIT %s OFFSET %s"
        return self._query(sql, (limit, offset))

    def execute_many(self, sql: str, params: List[Tuple]) -> int:
        cur = self._conn.cursor()
        cur.executemany(sql, params)
        self._conn.commit()
        return cur.rowcount

    def execute(self, sql: str, params: Tuple = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        self._conn.commit()
        return cur

    # ── internal ───────────────────────────────

    def _query(self, sql: str, params: Tuple = ()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, [list(r) for r in rows]

    def ensure_audit_table(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS savemydb_audit_log (
            id          BIGINT AUTO_INCREMENT PRIMARY KEY,
            table_name  VARCHAR(128)  NOT NULL,
            row_id      VARCHAR(512)  NOT NULL,
            operation   VARCHAR(10)   NOT NULL,
            changed_by  VARCHAR(128),
            changed_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            old_value   TEXT,
            new_value   TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        self.execute(sql)
        logger.info("MySQL audit table ready.")


# ─────────────────────────────────────────────
# PostgreSQL
# ─────────────────────────────────────────────

class PostgreSQLConnector(BaseConnector):
    """Connector for PostgreSQL using psycopg2."""

    def connect(self) -> None:
        import psycopg2  # type: ignore
        import psycopg2.extras
        self._conn = psycopg2.connect(
            host=self.config.get("host", "localhost"),
            port=int(self.config.get("port", 5432)),
            user=self.config["user"],
            password=self.config["password"],
            dbname=self.config["database"],
        )
        self._conn.autocommit = False
        logger.info("PostgreSQL connected to %s@%s",
                    self.config["database"], self.config.get("host"))

    def disconnect(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def get_tables(self) -> List[str]:
        _, rows = self._query(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )
        return [r[0] for r in rows]

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        sql = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
        """
        _, rows = self._query(sql, (table,))
        pks = set(self.get_primary_keys(table))
        return [
            {"column": r[0], "type": r[1], "nullable": r[2] == "YES",
             "key": "PRI" if r[0] in pks else "", "default": r[3]}
            for r in rows
        ]

    def get_primary_keys(self, table: str) -> List[str]:
        sql = """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_name = %s
        """
        _, rows = self._query(sql, (table,))
        return [r[0] for r in rows]

    def fetch_all(self, table, limit=10_000, offset=0, where=""):
        clause = f"WHERE {where}" if where else ""
        sql = f'SELECT * FROM "{table}" {clause} LIMIT %s OFFSET %s'
        return self._query(sql, (limit, offset))

    def execute_many(self, sql: str, params: List[Tuple]) -> int:
        import psycopg2.extras
        cur = self._conn.cursor()
        psycopg2.extras.execute_batch(cur, sql, params, page_size=500)
        self._conn.commit()
        return cur.rowcount

    def execute(self, sql: str, params: Tuple = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        self._conn.commit()
        return cur

    def _query(self, sql: str, params: Tuple = ()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, [list(r) for r in cur.fetchall()]

    def ensure_audit_table(self) -> None:
        sql = """
        CREATE TABLE IF NOT EXISTS savemydb_audit_log (
            id          BIGSERIAL PRIMARY KEY,
            table_name  VARCHAR(128)  NOT NULL,
            row_id      VARCHAR(512)  NOT NULL,
            operation   VARCHAR(10)   NOT NULL,
            changed_by  VARCHAR(128),
            changed_at  TIMESTAMPTZ   DEFAULT NOW(),
            old_value   TEXT,
            new_value   TEXT
        )
        """
        self.execute(sql)
        logger.info("PostgreSQL audit table ready.")

    def log_audit(self, table_name, row_id, operation,
                  changed_by="savemydb", old_value="", new_value=""):
        sql = """
        INSERT INTO savemydb_audit_log
            (table_name, row_id, operation, changed_by, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        self.execute(sql, (table_name, row_id, operation,
                           changed_by, old_value, new_value))


# ─────────────────────────────────────────────
# SQL Server
# ─────────────────────────────────────────────

class SQLServerConnector(BaseConnector):
    """Connector for Microsoft SQL Server using pyodbc."""

    def connect(self) -> None:
        import pyodbc  # type: ignore
        conn_str = (
            f"DRIVER={{{self.config.get('driver', 'ODBC Driver 17 for SQL Server')}}};"
            f"SERVER={self.config.get('host', 'localhost')},{self.config.get('port', 1433)};"
            f"DATABASE={self.config['database']};"
            f"UID={self.config['user']};"
            f"PWD={self.config['password']}"
        )
        self._conn = pyodbc.connect(conn_str, autocommit=False)
        logger.info("SQL Server connected to %s", self.config["database"])

    def disconnect(self) -> None:
        if self._conn:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def get_tables(self) -> List[str]:
        _, rows = self._query(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE'"
        )
        return [r[0] for r in rows]

    def get_schema(self, table: str) -> List[Dict[str, Any]]:
        sql = """
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """
        _, rows = self._query(sql, (table,))
        pks = set(self.get_primary_keys(table))
        return [
            {"column": r[0], "type": r[1], "nullable": r[2] == "YES",
             "key": "PRI" if r[0] in pks else "", "default": r[3]}
            for r in rows
        ]

    def get_primary_keys(self, table: str) -> List[str]:
        sql = """
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE OBJECTPROPERTY(OBJECT_ID(CONSTRAINT_SCHEMA + '.' + CONSTRAINT_NAME),
              'IsPrimaryKey') = 1
          AND TABLE_NAME = ?
        """
        _, rows = self._query(sql, (table,))
        return [r[0] for r in rows]

    def fetch_all(self, table, limit=10_000, offset=0, where=""):
        clause = f"WHERE {where}" if where else ""
        sql = (f"SELECT * FROM [{table}] {clause} "
               f"ORDER BY (SELECT NULL) OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY")
        return self._query(sql)

    def execute_many(self, sql: str, params: List[Tuple]) -> int:
        cur = self._conn.cursor()
        cur.fast_executemany = True
        cur.executemany(sql, params)
        self._conn.commit()
        return cur.rowcount

    def execute(self, sql: str, params: Tuple = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(sql, params)
        try:
            self._conn.commit()
        except Exception:
            pass
        return cur

    def _query(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, [list(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────

CONNECTORS = {
    "mysql": MySQLConnector,
    "postgresql": PostgreSQLConnector,
    "postgres": PostgreSQLConnector,
    "sqlserver": SQLServerConnector,
    "mssql": SQLServerConnector,
}


def get_connector(db_type: str, config: Dict[str, Any]) -> BaseConnector:
    """Return the appropriate connector for *db_type*."""
    key = db_type.lower().replace(" ", "").replace("-", "")
    cls = CONNECTORS.get(key)
    if not cls:
        raise ValueError(
            f"Unsupported database type '{db_type}'. "
            f"Choose from: {list(CONNECTORS.keys())}"
        )
    return cls(config)
