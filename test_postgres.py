import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        database="talentbridge",
        user="postgres",
        password="pass123"  # replace if different
    )

    print("✅ Connected successfully!")

    conn.close()

except Exception as e:
    print("❌ Error:", e)
