"""Create all DHARA tables in the configured Postgres database. Idempotent."""
from dhara_shared.db import init_db

if __name__ == "__main__":
    init_db()
    print("DHARA schema created/verified.")
