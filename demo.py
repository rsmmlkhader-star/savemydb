import logging, os, sys
from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "savemydb_demo"),
}

SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID", "")
CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json")
SHEET_TITLE = "Products"

SEED_DATA = [
    ("SKU-001","Wireless Keyboard","Electronics",49.99,120,1),
    ("SKU-002","USB-C Hub 7-in-1","Electronics",34.95,85,1),
    ("SKU-003","Ergonomic Mouse","Electronics",59.00,60,1),
    ("SKU-004","Laptop Stand","Accessories",29.99,200,1),
    ("SKU-005","Noise-Cancel Headset","Electronics",129.00,30,1),
]

def run():
    import mysql.connector, gspread
    from google.oauth2.service_account import Credentials

    print("\n[1/3] Setting up MySQL...")
    conn = mysql.connector.connect(host=DB_CONFIG["host"],port=DB_CONFIG["port"],user=DB_CONFIG["user"],password=DB_CONFIG["password"])
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS savemydb_demo CHARACTER SET utf8mb4")
    conn.commit(); conn.close()

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS products (
        id INT AUTO_INCREMENT PRIMARY KEY,
        sku VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL,
        category VARCHAR(100),
        price DECIMAL(10,2) DEFAULT 0.00,
        stock INT DEFAULT 0,
        is_active TINYINT(1) DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
    cur.executemany("INSERT IGNORE INTO products (sku,name,category,price,stock,is_active) VALUES (%s,%s,%s,%s,%s,%s)", SEED_DATA)
    conn.commit(); conn.close()
    print("   MySQL ready with 5 products ✅")

    print("\n[2/3] Exporting to Google Sheet...")
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT id,sku,name,category,price,stock,is_active FROM products")
    rows = cur.fetchall(); conn.close()

    scopes = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scopes)
    client = gspread.authorize(creds)
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(SHEET_TITLE); ws.clear()
    except:
        ws = ss.add_worksheet(title=SHEET_TITLE, rows=100, cols=20)

    ws.update("A1", [["id","sku","name","category","price","stock","is_active"]])
    ws.update("A2", [[str(c) if c is not None else "" for c in row] for row in rows])
    print(f"   Exported {len(rows)} rows ✅")
    print(f"   Open: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")

    input("\n   ► Edit any price in the sheet, then press ENTER...")

    print("\n[3/3] Syncing back to MySQL...")
    data = ws.get_all_values()[1:]
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    for row in data:
        if len(row) >= 7 and row[0]:
            cur.execute("UPDATE products SET price=%s, stock=%s WHERE id=%s",(float(row[4]),int(row[5]),int(row[0])))
    conn.commit(); conn.close()
    print("   Changes saved to MySQL ✅")
    print("\n🎉 SaveMyDB is working!\n")

if __name__ == "__main__":
    run()