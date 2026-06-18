"""SaveMyDB — Spreadsheet-to-Database Synchronization Platform."""

__version__ = "1.0.0"
__author__ = "SaveMyDB"

from .db_connector import get_connector, MySQLConnector, PostgreSQLConnector, SQLServerConnector
from .sheets_connector import SheetsConnector
from .sync_engine import SyncEngine, SyncStats
from .validation import SchemaValidator, ValidationResult
from .audit import AuditLogger

__all__ = [
    "get_connector",
    "MySQLConnector",
    "PostgreSQLConnector",
    "SQLServerConnector",
    "SheetsConnector",
    "SyncEngine",
    "SyncStats",
    "SchemaValidator",
    "ValidationResult",
    "AuditLogger",
]
