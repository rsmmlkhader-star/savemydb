"""
sync_engine.py — SaveMyDB
Detects and applies changes between Google Sheets and the database.

Change detection strategy
─────────────────────────
1. Read DB rows → build {pk_value: hash} index.
2. Read Sheet rows → build {pk_value: hash} index.
3. Diff the two indexes:
   • In Sheet but not in DB  → INSERT
   • In both but hash differs → UPDATE
   • In DB but not in Sheet  → DELETE  (only if deletions enabled)
4. Apply changes to DB in bulk.
5. Reload sheet with fresh DB data (optional).
"""

from __future__ import annotations
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .db_connector import BaseConnector
from .sheets_connector import SheetsConnector
from .validation import SchemaValidator
from .audit import AuditLogger

logger = logging.getLogger(__name__)

META = SheetsConnector.METADATA_PREFIX   # "_smdb_"


# ─────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────

@dataclass
class SyncStats:
    inserts: int = 0
    updates: int = 0
    deletes: int = 0
    skipped: int = 0
    validation_errors: List[str] = field(default_factory=list)

    @property
    def total_changes(self):
        return self.inserts + self.updates + self.deletes

    def __str__(self):
        return (
            f"Inserts: {self.inserts} | Updates: {self.updates} | "
            f"Deletes: {self.deletes} | Skipped: {self.skipped} | "
            f"Validation errors: {len(self.validation_errors)}"
        )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _row_hash(row_dict: Dict[str, Any], columns: List[str]) -> str:
    """MD5 of the sorted column values (excluding metadata cols)."""
    data = {k: str(v) for k, v in row_dict.items() if k in columns}
    return hashlib.md5(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()


def _pk_key(row_dict: Dict[str, Any], pk_columns: List[str]) -> str:
    return "|".join(str(row_dict.get(pk, "")) for pk in pk_columns)


def _build_upsert_sql(table: str, columns: List[str],
                      pk_columns: List[str], db_type: str) -> str:
    """Build DB-specific UPSERT SQL."""
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(f"`{c}`" if db_type == "mysql" else f'"{c}"'
                         for c in columns)

    if db_type in ("mysql",):
        updates = ", ".join(
            f"`{c}` = VALUES(`{c}`)"
            for c in columns if c not in pk_columns
        )
        return (f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}")

    elif db_type in ("postgresql", "postgres"):
        conflict_cols = ", ".join(f'"{c}"' for c in pk_columns)
        updates = ", ".join(
            f'"{c}" = EXCLUDED."{c}"'
            for c in columns if c not in pk_columns
        )
        return (f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
                f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {updates}")

    else:  # SQL Server — MERGE
        merge_on = " AND ".join(
            f"target.[{c}] = source.[{c}]" for c in pk_columns
        )
        update_set = ", ".join(
            f"target.[{c}] = source.[{c}]"
            for c in columns if c not in pk_columns
        )
        col_list_sq = ", ".join(f"[{c}]" for c in columns)
        src_cols = ", ".join(f"source.[{c}]" for c in columns)
        values_clause = ", ".join(["%s"] * len(columns))
        # For SQL Server we fall back to explicit UPDATE/INSERT
        return "__sqlserver_merge__"


def _build_delete_sql(table: str, pk_columns: List[str], db_type: str) -> str:
    if db_type == "mysql":
        where = " AND ".join(f"`{c}` = %s" for c in pk_columns)
        return f"DELETE FROM `{table}` WHERE {where}"
    elif db_type in ("postgresql", "postgres"):
        where = " AND ".join(f'"{c}" = %s' for c in pk_columns)
        return f'DELETE FROM "{table}" WHERE {where}'
    else:
        where = " AND ".join(f"[{c}] = ?" for c in pk_columns)
        return f"DELETE FROM [{table}] WHERE {where}"


# ─────────────────────────────────────────────
# SyncEngine
# ─────────────────────────────────────────────

class SyncEngine:
    """
    Orchestrates Sheet ↔ DB synchronization.

    Usage
    -----
    engine = SyncEngine(db, sheets, config)
    engine.export_to_sheet()          # DB → Sheet (initial load)
    stats = engine.sync_to_db()      # Sheet → DB (apply edits)
    stats = engine.full_sync()       # bidirectional
    """

    def __init__(
        self,
        db: BaseConnector,
        sheets: SheetsConnector,
        config: Dict[str, Any],
    ):
        """
        config keys:
          spreadsheet_id   str  — Google Sheets file ID
          sheet_title      str  — worksheet tab name
          table            str  — DB table name
          db_type          str  — mysql / postgresql / sqlserver
          allow_deletes    bool — whether Sheet deletions propagate to DB
          changed_by       str  — audit attribution label
          page_size        int  — rows per batch (default 5000)
        """
        self.db = db
        self.sheets = sheets
        self.cfg = config
        self.table = config["table"]
        self.db_type = config.get("db_type", "mysql").lower()
        self.allow_deletes = config.get("allow_deletes", False)
        self.changed_by = config.get("changed_by", "savemydb")
        self.page_size = config.get("page_size", 5_000)

        # lazily populated
        self._schema: Optional[List[Dict]] = None
        self._pk_columns: Optional[List[str]] = None
        self._data_columns: Optional[List[str]] = None
        self._validator: Optional[SchemaValidator] = None
        self._auditor: Optional[AuditLogger] = None

    # ── lazy accessors ────────────────────────

    @property
    def schema(self) -> List[Dict]:
        if self._schema is None:
            self._schema = self.db.get_schema(self.table)
        return self._schema

    @property
    def pk_columns(self) -> List[str]:
        if self._pk_columns is None:
            self._pk_columns = self.db.get_primary_keys(self.table)
        return self._pk_columns

    @property
    def data_columns(self) -> List[str]:
        if self._data_columns is None:
            self._data_columns = [c["column"] for c in self.schema]
        return self._data_columns

    @property
    def validator(self) -> SchemaValidator:
        if self._validator is None:
            self._validator = SchemaValidator(self.schema)
        return self._validator

    @property
    def auditor(self) -> AuditLogger:
        if self._auditor is None:
            self._auditor = AuditLogger(self.db)
        return self._auditor

    # ── export: DB → Sheet ────────────────────

    def export_to_sheet(self, where_clause: str = "") -> int:
        """
        Load the entire DB table into the Google Sheet.
        Returns number of rows exported.
        """
        logger.info("Exporting table '%s' → Sheet '%s' …",
                    self.table, self.cfg["sheet_title"])

        all_rows: List[List[Any]] = []
        offset = 0
        while True:
            cols, rows = self.db.fetch_all(
                self.table, limit=self.page_size,
                offset=offset, where=where_clause
            )
            all_rows.extend(rows)
            if len(rows) < self.page_size:
                break
            offset += self.page_size

        ss = self.sheets.open_spreadsheet(self.cfg["spreadsheet_id"])
        ws = self.sheets.get_or_create_worksheet(
            ss, self.cfg["sheet_title"],
            rows=max(len(all_rows) + 20, 1000),
            cols=max(len(cols) + 5, 26),
        )
        self.sheets.freeze_header(ws)
        self.sheets.clear_data(ws)

        # Header row
        meta_cols = [f"{META}row_id", f"{META}hash"]
        self.sheets.write_headers(ws, cols + meta_cols)

        # Data rows with metadata
        if all_rows:
            enriched = []
            for row in all_rows:
                row_dict = dict(zip(cols, row))
                rid = _pk_key(row_dict, self.pk_columns)
                rhash = _row_hash(row_dict, cols)
                enriched.append(list(row) + [rid, rhash])

            # Write in batches of 1000 to avoid Sheets API limits
            BATCH = 1_000
            for i in range(0, len(enriched), BATCH):
                self.sheets.write_rows(ws, enriched[i:i+BATCH],
                                       start_row=2 + i)

        logger.info("Exported %d rows.", len(all_rows))
        return len(all_rows)

    # ── sync: Sheet → DB ─────────────────────

    def sync_to_db(self) -> SyncStats:
        """
        Read the Sheet, diff against DB, apply INSERT/UPDATE/DELETE.
        Returns SyncStats.
        """
        stats = SyncStats()
        logger.info("Starting sync: Sheet → DB table '%s'", self.table)

        # ── 1. read sheet ─────────────────────
        ss = self.sheets.open_spreadsheet(self.cfg["spreadsheet_id"])
        ws = ss.worksheet(self.cfg["sheet_title"])
        data_cols, sheet_records = self.sheets.read_with_metadata(ws)

        if not sheet_records:
            logger.warning("Sheet is empty; nothing to sync.")
            return stats

        # ── 2. read DB ────────────────────────
        db_cols, db_rows = self.db.fetch_all(self.table, limit=500_000)
        db_index: Dict[str, Dict] = {}
        for row in db_rows:
            rd = dict(zip(db_cols, row))
            db_index[_pk_key(rd, self.pk_columns)] = rd

        # ── 3. diff ───────────────────────────
        to_insert: List[Dict] = []
        to_update: List[Dict] = []
        seen_keys: set = set()

        for rec in sheet_records:
            # skip metadata-only rows
            if not any(rec.get(c) for c in data_cols if not c.startswith(META)):
                continue

            pk_key = rec.get(f"{META}row_id") or _pk_key(rec, self.pk_columns)
            seen_keys.add(pk_key)

            sheet_hash = _row_hash(rec, data_cols)
            stored_hash = rec.get(f"{META}hash", "")

            if pk_key not in db_index:
                to_insert.append(rec)
            elif sheet_hash != stored_hash:
                to_update.append(rec)
            # else: unchanged

        # rows in DB but not in Sheet → candidates for deletion
        to_delete_keys = set(db_index.keys()) - seen_keys

        # ── 4. validate ───────────────────────
        all_to_write = to_insert + to_update
        bad = self.validator.validate_batch(all_to_write, self.pk_columns)
        bad_indices = {i for i, _ in bad}

        if bad:
            for i, res in bad:
                stats.validation_errors.append(str(res))
                logger.warning("Row %d failed validation: %s", i, res)

        valid_inserts = [
            r for j, r in enumerate(to_insert) if j not in bad_indices
        ]
        valid_updates = [
            r for j, r in enumerate(to_update,
                                     start=len(to_insert)) if j not in bad_indices
        ]
        stats.skipped = len(bad)

        # ── 5. apply inserts ──────────────────
        if valid_inserts:
            stats.inserts = self._apply_upsert(valid_inserts, "insert")

        # ── 6. apply updates ──────────────────
        if valid_updates:
            stats.updates = self._apply_upsert(valid_updates, "update")

        # ── 7. apply deletes ──────────────────
        if self.allow_deletes and to_delete_keys:
            stats.deletes = self._apply_deletes(
                [db_index[k] for k in to_delete_keys]
            )

        logger.info("Sync complete. %s", stats)
        return stats

    # ── full bidirectional sync ───────────────

    def full_sync(self) -> SyncStats:
        """Export DB → Sheet, then sync Sheet → DB."""
        self.export_to_sheet()
        return self.sync_to_db()

    # ── internal apply helpers ────────────────

    def _apply_upsert(self, records: List[Dict], operation: str) -> int:
        cols = self.data_columns
        db_type = self.db_type

        upsert_sql = _build_upsert_sql(self.table, cols, self.pk_columns, db_type)

        params: List[Tuple] = []
        for rec in records:
            coerced = self.validator.coerce_row(rec)
            params.append(tuple(coerced.get(c) for c in cols))

            # Audit
            pk_key = _pk_key(rec, self.pk_columns)
            if operation == "insert":
                self.auditor.log_insert(self.table, pk_key, coerced,
                                        self.changed_by)
            else:
                self.auditor.log_update(self.table, pk_key, {}, coerced,
                                        self.changed_by)

        if db_type in ("sqlserver", "mssql"):
            # SQL Server: fall back to row-by-row
            count = self._sqlserver_upsert(records, cols)
        else:
            count = self.db.execute_many(upsert_sql, params)

        logger.info("Applied %d %s(s) to '%s'.", len(records), operation, self.table)
        return len(records)

    def _sqlserver_upsert(self, records: List[Dict], cols: List[str]) -> int:
        """SQL Server explicit UPDATE + INSERT fallback."""
        pk = self.pk_columns
        for rec in records:
            coerced = self.validator.coerce_row(rec)
            pk_vals = tuple(coerced.get(c) for c in pk)
            where = " AND ".join(f"[{c}] = ?" for c in pk)
            existing = self.db.execute(
                f"SELECT 1 FROM [{self.table}] WHERE {where}", pk_vals
            ).fetchone()

            if existing:
                non_pk_cols = [c for c in cols if c not in pk]
                set_clause = ", ".join(f"[{c}] = ?" for c in non_pk_cols)
                vals = tuple(coerced.get(c) for c in non_pk_cols) + pk_vals
                self.db.execute(
                    f"UPDATE [{self.table}] SET {set_clause} WHERE {where}", vals
                )
            else:
                col_list = ", ".join(f"[{c}]" for c in cols)
                ph = ", ".join(["?"] * len(cols))
                vals = tuple(coerced.get(c) for c in cols)
                self.db.execute(
                    f"INSERT INTO [{self.table}] ({col_list}) VALUES ({ph})", vals
                )
        return len(records)

    def _apply_deletes(self, rows: List[Dict]) -> int:
        if not rows:
            return 0
        sql = _build_delete_sql(self.table, self.pk_columns, self.db_type)
        params = [tuple(row.get(pk) for pk in self.pk_columns) for row in rows]

        for row in rows:
            self.auditor.log_delete(
                self.table,
                _pk_key(row, self.pk_columns),
                row,
                self.changed_by,
            )

        self.db.execute_many(sql, params)
        logger.info("Deleted %d row(s) from '%s'.", len(rows), self.table)
        return len(rows)

    # ── conflict resolution ───────────────────

    def resolve_conflict(
        self,
        db_row: Dict,
        sheet_row: Dict,
        strategy: str = "last_write_wins",
        db_ts_col: str = "updated_at",
        sheet_ts_col: str = "updated_at",
    ) -> Dict:
        """
        Resolve a conflict between DB and Sheet versions of a row.
        Strategies:
          last_write_wins — whichever timestamp is newer wins
          db_wins         — DB always wins
          sheet_wins      — Sheet always wins
        """
        if strategy == "db_wins":
            return db_row
        if strategy == "sheet_wins":
            return sheet_row

        # last_write_wins
        from datetime import datetime as dt
        db_ts = db_row.get(db_ts_col)
        sh_ts = sheet_row.get(sheet_ts_col)

        def _parse(ts):
            if isinstance(ts, dt):
                return ts
            try:
                return dt.fromisoformat(str(ts))
            except Exception:
                return dt.min

        return db_row if _parse(db_ts) >= _parse(sh_ts) else sheet_row
