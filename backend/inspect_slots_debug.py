import sqlite3

db_path = r"c:\Projects\ap-tracker\backend\ap_tracker.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- USER 10 ---")
cursor.execute("PRAGMA table_info(users)")
cols = [c[1] for c in cursor.fetchall()]

cursor.execute("SELECT * FROM users WHERE id = 10")
row = cursor.fetchone()
if row:
    print(dict(zip(cols, row)))
else:
    print("User 10 not found!")

conn.close()
