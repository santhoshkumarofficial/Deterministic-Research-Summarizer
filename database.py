import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":        os.getenv("MYSQL_HOST", "localhost"),
    "port":        int(os.getenv("MYSQL_PORT", 3306)),
    "user":        os.getenv("MYSQL_USER", "root"),
    "password":    os.getenv("MYSQL_PASSWORD", ""),
    "db":          os.getenv("MYSQL_DB", "research_ai"),
    "charset":     "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit":  False,
}


def get_db():
    """Return a new MySQL connection. Caller must close it."""
    return pymysql.connect(**DB_CONFIG)