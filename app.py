from flask import Flask, jsonify, request
from flask_cors import CORS
import os, uuid, logging
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

_connections = {}
_sheets_creds = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")

def _ok(data=None, message="OK", status=200):
    return jsonify({"status": "ok", "message": message, "data": data}), status

def _err(message, status=400):
    return jsonify({"status": "error", "message": message}), status

@app.get("/api/health")
def health():
    return _ok({"version": "1.0.0", "service": "SaveMyDB"})

@app.post("/api/connections")
def create_connection():
    body = request.get_json()
    db_type = body.get("db_type", "").lower()
    config  = body.get("config", {})
    if not db_type or not config:
        return _err("db_type and config are required.")
    try:
        from savemydb.db_connector import get_connector
        connector = get_connector(db_type, config)
        connector.connect()
        tables = connector.get_tables()
        connector.ensure_audit_table()
        connector.disconnect()
        conn_id = str(uuid.uuid4())[:8]
        _connections[conn_id] = {"db_type": db_type, "config": config}
        return _ok({"connection_id": conn_id, "tables": tables}, "Connection successful.", 201)
    except Exception as exc:
        return _err(f"Connection failed: {exc}", 502)

@app.get("/api/connections")
def list_connections():
    return _ok([{"connection_id": k, "db_type": v["db_type"]} for k, v in _connections.items()])

@app.get("/api/connections/<conn_id>/tables")
def list_tables(conn_id):
    meta = _connections.get(conn_id)
    if not meta: return _err("Unknown connection_id.", 404)
    from savemydb.db_connector import get_connector
    c = get_connector(meta["db_type"], meta["config"])
    c.connect()
    tables = c.get_tables()
    c.disconnect()
    return _ok(tables)

@app.get("/api/connections/<conn_id>/tables/<table>/schema")
def get_schema(conn_id, table):
    meta = _connections.get(conn_id)
    if not meta: return _err("Unknown connection_id.", 404)
    from savemydb.db_connector import get_connector
    c = get_connector(meta["db_type"], meta["config"])
    c.connect()
    schema = c.get_schema(table)
    pks = c.get_primary_keys(table)
    c.disconnect()
    return _ok({"schema": schema, "primary_keys": pks})

def _build_engine(body):
    conn_id = body.get("connection_id")
    meta = _connections.get(conn_id)
    if not meta: raise ValueError(f"Unknown connection_id '{conn_id}'.")
    from savemydb.db_connector import get_connector
    from savemydb.sheets_connector import SheetsConnector
    from savemydb.sync_engine import SyncEngine
    connector = get_connector(meta["db_type"], meta["config"])
    connector.connect()
    sheets = SheetsConnector(_sheets_creds)
    sheets.authenticate()
    config = {
        "spreadsheet_id": body["spreadsheet_id"],
        "sheet_title": body.get("sheet_title", body.get("table", "Sheet1")),
        "table": body["table"],
        "db_type": meta["db_type"],
        "allow_deletes": body.get("allow_deletes", False),
        "changed_by": body.get("changed_by", "savemydb-api"),
        "page_size": body.get("page_size", 5000),
    }
    return SyncEngine(connector, sheets, config)

@app.post("/api/sync/export")
def sync_export():
    body = request.get_json()
    try:
        engine = _build_engine(body)
        rows = engine.export_to_sheet(body.get("where_clause", ""))
        engine.db.disconnect()
        return _ok({"rows_exported": rows, "spreadsheet_id": body["spreadsheet_id"]}, f"Exported {rows} rows.")
    except Exception as exc:
        return _err(f"Export failed: {exc}", 500)

@app.post("/api/sync/import")
def sync_import():
    body = request.get_json()
    try:
        engine = _build_engine(body)
        stats = engine.sync_to_db()
        engine.db.disconnect()
        return _ok({"inserts": stats.inserts, "updates": stats.updates, "deletes": stats.deletes, "skipped": stats.skipped}, f"Sync complete. {stats.total_changes} change(s) applied.")
    except Exception as exc:
        return _err(f"Sync failed: {exc}", 500)

@app.post("/api/sync/full")
def sync_full():
    body = request.get_json()
    try:
        engine = _build_engine(body)
        rows = engine.export_to_sheet()
        stats = engine.sync_to_db()
        engine.db.disconnect()
        return _ok({"rows_exported": rows, "inserts": stats.inserts, "updates": stats.updates, "deletes": stats.deletes}, "Full sync complete.")
    except Exception as exc:
        return _err(f"Full sync failed: {exc}", 500)

@app.get("/api/audit/<conn_id>/<table>")
def get_audit(conn_id, table):
    meta = _connections.get(conn_id)
    if not meta: return _err("Unknown connection_id.", 404)
    from savemydb.db_connector import get_connector
    from savemydb.audit import AuditLogger
    c = get_connector(meta["db_type"], meta["config"])
    c.connect()
    history = AuditLogger(c).get_history(table, request.args.get("row_id"), int(request.args.get("limit", 100)))
    c.disconnect()
    return _ok(history)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info("SaveMyDB API starting on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=True)