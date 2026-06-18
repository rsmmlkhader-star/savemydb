"""
validation.py — SaveMyDB
Enforces schema rules before writing data to the database.
"""

from __future__ import annotations
import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    column: str
    value: Any
    message: str

    def __str__(self):
        return f"[{self.column}] '{self.value}' — {self.message}"


@dataclass
class ValidationResult:
    valid: bool = True
    errors: List[ValidationError] = field(default_factory=list)

    def add_error(self, column: str, value: Any, message: str) -> None:
        self.valid = False
        self.errors.append(ValidationError(column, value, message))

    def __str__(self):
        if self.valid:
            return "OK"
        return " | ".join(str(e) for e in self.errors)


# ─────────────────────────────────────────────
# Type-checking helpers
# ─────────────────────────────────────────────

_INTEGER_TYPES = {
    "int", "integer", "bigint", "smallint", "tinyint", "mediumint",
    "serial", "bigserial", "smallserial",
    "int2", "int4", "int8",
}

_FLOAT_TYPES = {
    "float", "double", "real", "decimal", "numeric",
    "float4", "float8", "money", "smallmoney",
}

_DATE_TYPES = {"date"}
_DATETIME_TYPES = {"datetime", "timestamp", "timestamptz", "datetime2", "smalldatetime"}
_BOOL_TYPES = {"bool", "boolean", "bit"}
_TEXT_TYPES = {
    "varchar", "char", "text", "nvarchar", "nchar", "ntext",
    "character varying", "character", "tinytext", "mediumtext", "longtext",
}

_DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"]
_DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S",
]


def _base_type(db_type: str) -> str:
    """Strip length/precision: 'varchar(255)' → 'varchar'."""
    return re.sub(r"\s*\(.*\)", "", db_type).strip().lower()


def _is_integer(val: str) -> bool:
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


def _is_float(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _parse_date(val: str) -> Optional[datetime.date]:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(val, fmt).date()
        except ValueError:
            pass
    return None


def _parse_datetime(val: str) -> Optional[datetime.datetime]:
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.datetime.strptime(val, fmt)
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────
# SchemaValidator
# ─────────────────────────────────────────────

class SchemaValidator:
    """
    Validates spreadsheet rows against a DB schema definition.

    schema = [
      {"column": "id",    "type": "int",          "nullable": False, "key": "PRI"},
      {"column": "name",  "type": "varchar(100)",  "nullable": False},
      {"column": "price", "type": "decimal(10,2)", "nullable": True},
      ...
    ]
    """

    def __init__(self, schema: List[Dict[str, Any]]):
        self.schema = schema
        self._col_map: Dict[str, Dict] = {c["column"]: c for c in schema}

    def validate_row(
        self,
        row: Dict[str, Any],
        pk_columns: Optional[List[str]] = None,
        operation: str = "upsert",
    ) -> ValidationResult:
        result = ValidationResult()
        pk_columns = pk_columns or []

        for col_def in self.schema:
            col = col_def["column"]
            db_type = _base_type(col_def.get("type", "text"))
            nullable = col_def.get("nullable", True)
            is_pk = col in pk_columns

            # Skip auto-generated PKs on INSERT
            if is_pk and operation == "insert" and col not in row:
                continue

            raw = row.get(col)

            # ── required check ─────────────────
            if raw is None or str(raw).strip() == "":
                if not nullable and not is_pk:
                    result.add_error(col, raw, "Required field is empty.")
                continue  # skip type checks for empty nullable fields

            val = str(raw).strip()

            # ── type checks ────────────────────
            if db_type in _INTEGER_TYPES:
                if not _is_integer(val):
                    result.add_error(col, val, f"Expected integer, got '{val}'.")

            elif db_type in _FLOAT_TYPES:
                if not _is_float(val):
                    result.add_error(col, val, f"Expected numeric value, got '{val}'.")

            elif db_type in _DATE_TYPES:
                if _parse_date(val) is None:
                    result.add_error(
                        col, val,
                        f"Expected date (YYYY-MM-DD), got '{val}'."
                    )

            elif db_type in _DATETIME_TYPES:
                if _parse_datetime(val) is None:
                    result.add_error(
                        col, val,
                        f"Expected datetime (YYYY-MM-DD HH:MM:SS), got '{val}'."
                    )

            elif db_type in _BOOL_TYPES:
                if val.lower() not in {"true", "false", "1", "0", "yes", "no"}:
                    result.add_error(col, val, f"Expected boolean, got '{val}'.")

            # ── length check for text ──────────
            elif db_type in _TEXT_TYPES:
                m = re.search(r"\((\d+)\)", col_def.get("type", ""))
                if m:
                    max_len = int(m.group(1))
                    if len(val) > max_len:
                        result.add_error(
                            col, val,
                            f"Value length {len(val)} exceeds max {max_len}."
                        )

        return result

    def validate_batch(
        self,
        rows: List[Dict[str, Any]],
        pk_columns: Optional[List[str]] = None,
        operation: str = "upsert",
    ) -> List[Tuple[int, ValidationResult]]:
        """
        Validate a list of rows.
        Returns list of (row_index, ValidationResult) for INVALID rows only.
        """
        bad: List[Tuple[int, ValidationResult]] = []
        for i, row in enumerate(rows):
            res = self.validate_row(row, pk_columns, operation)
            if not res.valid:
                bad.append((i, res))
        return bad

    def coerce_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Best-effort type coercion: convert string values to Python types
        so they can be safely inserted into the DB.
        """
        coerced = {}
        for col_def in self.schema:
            col = col_def["column"]
            db_type = _base_type(col_def.get("type", "text"))
            raw = row.get(col)

            if raw is None or str(raw).strip() == "":
                coerced[col] = None
                continue

            val = str(raw).strip()

            try:
                if db_type in _INTEGER_TYPES:
                    coerced[col] = int(val)
                elif db_type in _FLOAT_TYPES:
                    coerced[col] = float(val)
                elif db_type in _DATE_TYPES:
                    coerced[col] = _parse_date(val)
                elif db_type in _DATETIME_TYPES:
                    coerced[col] = _parse_datetime(val)
                elif db_type in _BOOL_TYPES:
                    coerced[col] = val.lower() in {"true", "1", "yes"}
                else:
                    coerced[col] = val
            except Exception:
                coerced[col] = val  # fallback: pass raw string

        return coerced


# ─────────────────────────────────────────────
# Utility: from typing import Tuple (fix)
# ─────────────────────────────────────────────
from typing import Tuple  # noqa: E402 (needed for the return type annotation above)
