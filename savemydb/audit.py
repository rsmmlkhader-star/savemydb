"""
audit.py — SaveMyDB
Audit trail: logs every INSERT / UPDATE / DELETE to savemydb_audit_log.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Wraps a BaseConnector to record changes in savemydb_audit_log.
    Falls back to local JSON file if the DB write fails.
    """

    def __init__(self, db_connector, fallback_file: str = "audit_fallback.jsonl"):
        self.db = db_connector
        self.fallback_file = fallback_file

    # ── single-entry log ──────────────────────

    def log(
        self,
        table_name: str,
        row_id: str,
        operation: str,         # INSERT | UPDATE | DELETE
        changed_by: str = "savemydb",
        old_value: Optional[Dict] = None,
        new_value: Optional[Dict] = None,
    ) -> None:
        old_str = json.dumps(old_value, default=str) if old_value else ""
        new_str = json.dumps(new_value, default=str) if new_value else ""

        try:
            self.db.log_audit(
                table_name=table_name,
                row_id=row_id,
                operation=operation,
                changed_by=changed_by,
                old_value=old_str,
                new_value=new_str,
            )
        except Exception as exc:
            logger.warning("DB audit write failed (%s); writing to fallback file.", exc)
            self._fallback_log({
                "table_name": table_name,
                "row_id": row_id,
                "operation": operation,
                "changed_by": changed_by,
                "changed_at": datetime.utcnow().isoformat(),
                "old_value": old_str,
                "new_value": new_str,
            })

    # ── batch convenience ─────────────────────

    def log_insert(self, table: str, row_id: str, new_row: Dict,
                   changed_by: str = "savemydb") -> None:
        self.log(table, row_id, "INSERT", changed_by, None, new_row)

    def log_update(self, table: str, row_id: str, old_row: Dict,
                   new_row: Dict, changed_by: str = "savemydb") -> None:
        self.log(table, row_id, "UPDATE", changed_by, old_row, new_row)

    def log_delete(self, table: str, row_id: str, old_row: Dict,
                   changed_by: str = "savemydb") -> None:
        self.log(table, row_id, "DELETE", changed_by, old_row, None)

    # ── query ─────────────────────────────────

    def get_history(
        self,
        table_name: str,
        row_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return recent audit entries for a table (or specific row)."""
        if row_id:
            sql = (
                "SELECT * FROM savemydb_audit_log "
                "WHERE table_name = %s AND row_id = %s "
                "ORDER BY changed_at DESC LIMIT %s"
            )
            params = (table_name, row_id, limit)
        else:
            sql = (
                "SELECT * FROM savemydb_audit_log "
                "WHERE table_name = %s "
                "ORDER BY changed_at DESC LIMIT %s"
            )
            params = (table_name, limit)

        try:
            cols, rows = self.db._query(sql, params)
            return [dict(zip(cols, row)) for row in rows]
        except Exception as exc:
            logger.error("Could not read audit log: %s", exc)
            return []

    # ── fallback ──────────────────────────────

    def _fallback_log(self, entry: Dict) -> None:
        try:
            with open(self.fallback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.error("Fallback audit log also failed: %s", exc)

    def replay_fallback(self) -> int:
        """
        Try to replay any entries in the fallback JSONL file into the DB.
        Returns the number of successfully replayed entries.
        """
        import os
        if not os.path.exists(self.fallback_file):
            return 0

        replayed = 0
        remaining = []
        with open(self.fallback_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                try:
                    self.db.log_audit(
                        table_name=entry["table_name"],
                        row_id=entry["row_id"],
                        operation=entry["operation"],
                        changed_by=entry["changed_by"],
                        old_value=entry["old_value"],
                        new_value=entry["new_value"],
                    )
                    replayed += 1
                except Exception:
                    remaining.append(line)

        with open(self.fallback_file, "w", encoding="utf-8") as f:
            f.writelines(remaining)

        logger.info("Replayed %d fallback audit entries.", replayed)
        return replayed
