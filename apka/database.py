import sqlite3
from datetime import datetime

DB_NAME = "measurements.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        sample_name TEXT,
        v1 REAL, v2 REAL, v3 REAL, v4 REAL, v5 REAL,
        v6 REAL, v7 REAL, v8 REAL, v9 REAL, v10 REAL,
        note TEXT
    )
    """)

    conn.commit()
    conn.close()


def insert_measurement(sample_name, values, note):
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO measurements (
        date, sample_name,
        v1,v2,v3,v4,v5,v6,v7,v8,v9,v10,
        note
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        now,
        sample_name,
        *values,
        note
    ))

    conn.commit()
    conn.close()
