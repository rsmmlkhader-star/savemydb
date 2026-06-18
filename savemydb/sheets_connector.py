"""
sheets_connector.py — SaveMyDB
Handles all Google Sheets API interactions via gspread.
"""

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Rate-limit constants (Sheets API: 60 reads/min, 300 writes/min per project)
_RETRY_ATTEMPTS = 5
_RETRY_DELAY = 2   # seconds between retries


def _retry(fn):
    """Decorator: retry on transient Google API errors."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import gspread.exceptions as gex  # type: ignore
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return fn(*args, **kwargs)
            except gex.APIError as exc:
                if attempt == _RETRY_ATTEMPTS:
                    raise
                wait = _RETRY_DELAY * (2 ** (attempt - 1))
                logger.warning("Sheets API error (attempt %d/%d): %s — retrying in %ds",
                               attempt, _RETRY_ATTEMPTS, exc, wait)
                time.sleep(wait)
    return wrapper


# ─────────────────────────────────────────────
# SheetsConnector
# ─────────────────────────────────────────────

class SheetsConnector:
    """
    Wraps gspread to provide batch read/write access to Google Sheets.

    Authentication modes
    --------------------
    • service_account_file  — path to JSON key file
    • oauth_credentials     — path to OAuth2 credentials JSON (user flow)
    """

    METADATA_PREFIX = "_smdb_"   # prefix for hidden metadata columns

    def __init__(
        self,
        credentials_path: str,
        auth_mode: str = "service_account",
    ):
        self.credentials_path = credentials_path
        self.auth_mode = auth_mode
        self._client = None

    # ── auth ──────────────────────────────────

    def authenticate(self) -> None:
        import gspread  # type: ignore
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        if self.auth_mode == "service_account":
            self._client = gspread.service_account(
                filename=self.credentials_path,
                scopes=scopes,
            )
        else:
            self._client = gspread.oauth(
                credentials_filename=self.credentials_path,
                scopes=scopes,
            )
        logger.info("Google Sheets authenticated (%s).", self.auth_mode)

    # ── spreadsheet helpers ───────────────────

    def open_spreadsheet(self, spreadsheet_id: str):
        """Open a spreadsheet by its ID."""
        return self._client.open_by_key(spreadsheet_id)

    def create_spreadsheet(self, title: str):
        """Create a new spreadsheet and return its object."""
        ss = self._client.create(title)
        logger.info("Created spreadsheet '%s' (%s).", title, ss.id)
        return ss

    def share_spreadsheet(self, spreadsheet_id: str, email: str,
                          role: str = "writer") -> None:
        ss = self.open_spreadsheet(spreadsheet_id)
        ss.share(email, perm_type="user", role=role)
        logger.info("Shared %s with %s as %s.", spreadsheet_id, email, role)

    # ── worksheet helpers ─────────────────────

    def get_or_create_worksheet(self, ss, title: str, rows: int = 1000,
                                cols: int = 26):
        try:
            ws = ss.worksheet(title)
        except Exception:
            ws = ss.add_worksheet(title=title, rows=rows, cols=cols)
            logger.info("Created worksheet '%s'.", title)
        return ws

    # ── read ──────────────────────────────────

    @_retry
    def read_all(self, worksheet) -> Tuple[List[str], List[List[str]]]:
        """
        Return (headers, rows) from a worksheet.
        Row 1 is treated as the header row.
        """
        raw = worksheet.get_all_values()
        if not raw:
            return [], []
        headers = raw[0]
        rows = raw[1:]
        logger.debug("Read %d rows from '%s'.", len(rows), worksheet.title)
        return headers, rows

    @_retry
    def read_range(self, worksheet, cell_range: str) -> List[List[str]]:
        return worksheet.get(cell_range)

    # ── write ─────────────────────────────────

    @_retry
    def write_headers(self, worksheet, headers: List[str]) -> None:
        """Write the header row (row 1)."""
        worksheet.update("A1", [headers], value_input_option="RAW")
        # Bold the header row
        try:
            worksheet.format("1:1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.2, "green": 0.4, "blue": 0.8},
            })
        except Exception:
            pass

    @_retry
    def write_rows(self, worksheet, rows: List[List[Any]],
                   start_row: int = 2) -> None:
        """
        Batch-write rows starting at *start_row*.
        Converts all values to strings for safety.
        """
        if not rows:
            return
        safe = [[str(c) if c is not None else "" for c in row] for row in rows]
        start_cell = f"A{start_row}"
        worksheet.update(start_cell, safe, value_input_option="USER_ENTERED")
        logger.debug("Wrote %d rows starting at row %d.", len(rows), start_row)

    @_retry
    def clear_data(self, worksheet) -> None:
        """Clear all data except the header row."""
        worksheet.batch_clear(["A2:ZZ"])

    @_retry
    def append_rows(self, worksheet, rows: List[List[Any]]) -> None:
        if not rows:
            return
        safe = [[str(c) if c is not None else "" for c in row] for row in rows]
        worksheet.append_rows(safe, value_input_option="USER_ENTERED",
                              insert_data_option="INSERT_ROWS")

    @_retry
    def update_cell(self, worksheet, row: int, col: int, value: Any) -> None:
        worksheet.update_cell(row, col, str(value) if value is not None else "")

    @_retry
    def delete_row(self, worksheet, row_index: int) -> None:
        """Delete a row by 1-based index (including header = row 1)."""
        worksheet.delete_rows(row_index)

    # ── metadata helpers ──────────────────────

    def add_metadata_column(self, worksheet, col_name: str,
                            values: List[str]) -> None:
        """
        Append a metadata column (e.g. _smdb_row_id, _smdb_hash) to the right.
        Header on row 1; values starting row 2.
        """
        headers, _ = self.read_all(worksheet)
        if col_name in headers:
            idx = headers.index(col_name) + 1
        else:
            idx = len(headers) + 1

        from gspread.utils import rowcol_to_a1  # type: ignore
        cell = rowcol_to_a1(1, idx)
        worksheet.update(cell, [[col_name]])
        if values:
            data_cell = rowcol_to_a1(2, idx)
            worksheet.update(data_cell, [[v] for v in values])

    # ── protection / formatting ───────────────

    def freeze_header(self, worksheet) -> None:
        """Freeze the first row so headers stay visible when scrolling."""
        worksheet.freeze(rows=1)

    def protect_column(self, worksheet, col_letter: str,
                       description: str = "Protected by SaveMyDB") -> None:
        """Request column protection (requires owner token)."""
        try:
            worksheet.add_protected_range(
                f"{col_letter}:{col_letter}",
                editor_users_emails=[],
                description=description,
            )
        except Exception as exc:
            logger.warning("Could not protect column %s: %s", col_letter, exc)

    # ── full-sheet export/import ──────────────

    def export_to_sheet(
        self,
        spreadsheet_id: str,
        sheet_title: str,
        columns: List[str],
        rows: List[List[Any]],
        pk_columns: Optional[List[str]] = None,
    ) -> str:
        """
        Full export: open/create sheet, write headers + rows.
        Returns the worksheet URL.
        """
        ss = self.open_spreadsheet(spreadsheet_id)
        ws = self.get_or_create_worksheet(ss, sheet_title,
                                          rows=max(len(rows) + 10, 1000),
                                          cols=max(len(columns) + 5, 26))
        self.freeze_header(ws)
        self.clear_data(ws)

        # Add hidden _smdb_row_id column
        all_columns = columns + [f"{self.METADATA_PREFIX}row_id",
                                  f"{self.METADATA_PREFIX}hash"]
        self.write_headers(ws, all_columns)

        if rows:
            import hashlib, json
            enriched = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                if pk_columns:
                    rid = "|".join(str(row_dict.get(pk, "")) for pk in pk_columns)
                else:
                    rid = str(id(row))
                row_hash = hashlib.md5(
                    json.dumps(row, default=str, sort_keys=True).encode()
                ).hexdigest()[:8]
                enriched.append(list(row) + [rid, row_hash])

            self.write_rows(ws, enriched, start_row=2)

        logger.info("Exported %d rows to sheet '%s'.", len(rows), sheet_title)
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    # ── change detection ──────────────────────

    def read_with_metadata(
        self, worksheet
    ) -> Tuple[List[str], List[Dict[str, str]]]:
        """
        Read the sheet and return
        (data_columns, list_of_dicts_including_metadata).
        """
        headers, rows = self.read_all(worksheet)
        if not headers:
            return [], []

        meta_cols = {h for h in headers if h.startswith(self.METADATA_PREFIX)}
        data_cols = [h for h in headers if h not in meta_cols]

        result = []
        for row in rows:
            padded = row + [""] * (len(headers) - len(row))
            rec = dict(zip(headers, padded))
            result.append(rec)

        return data_cols, result
