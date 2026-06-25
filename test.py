import psycopg2


def get_connection():
    return psycopg2.connect(
        host="104.248.246.2",
        database="postgres",
        user="user",
        password="123123",
        port="5432"
    )


try:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'users'
        ORDER BY ordinal_position
    """)

    print("\n📋 Users Columns:\n")

    for column in cursor.fetchall():
        print(f"{column[0]} -> {column[1]}")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"\n❌ Error: {e}")