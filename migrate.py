import sqlite3
import psycopg2
from psycopg2.extras import execute_values

sqlite_conn = sqlite3.connect("./Backend/talentbridge.db")
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

pg_conn = psycopg2.connect(
    host="localhost",
    database="talentbridge",
    user="postgres",
    password="pass123"
)

pg_cur = pg_conn.cursor()

tables = [
    "companies",
    "users",
    "job_seeker_profiles",
    "jobs",
    "candidates",
    "activity_log"
]

for table in tables:
    print(f"Migrating {table}...")

    sqlite_cur.execute(f"SELECT * FROM {table}")
    rows = sqlite_cur.fetchall()

    if not rows:
        print("  -> No rows found")
        continue

    columns = rows[0].keys()
    values = []

    for row in rows:
        row_data = []

        for col in columns:
            value = row[col]

            if table == "companies" and col == "verified":
                value = bool(value)

            if table == "job_seeker_profiles" and col == "open_to_work":
                value = bool(value)

            row_data.append(value)

        values.append(tuple(row_data))

    pg_cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")

    insert_sql = f"""
        INSERT INTO {table}
        ({','.join(columns)})
        VALUES %s
    """

    execute_values(pg_cur, insert_sql, values)

    pg_conn.commit()

    print(f"  -> {len(rows)} rows migrated")

sqlite_conn.close()
pg_conn.close()

print("\nMigration complete!")
