from dotenv import load_dotenv
import os, pymysql

load_dotenv()

print("Connecting with:")
print("  HOST:", os.getenv("MYSQL_HOST"))
print("  USER:", os.getenv("MYSQL_USER"))
print("  PASS:", os.getenv("MYSQL_PASSWORD"))
print("  DB:  ", os.getenv("MYSQL_DB"))

try:
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        db=os.getenv("MYSQL_DB"),
    )
    print("\nSUCCESS — MySQL connected!")
    conn.close()
except Exception as e:
    print("\nFAILED:", e)