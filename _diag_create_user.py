"""Diagnose create_user against configured DB. Do not commit."""
from __future__ import annotations

import os
import time
import traceback
from pathlib import Path


def _load_dotenv() -> None:
    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def main() -> None:
    _load_dotenv()
    print("TURSO_URL set", bool(os.getenv("TURSO_DATABASE_URL")))
    print("USE_LOCAL_DB", os.getenv("USE_LOCAL_DB"))
    from community_auth import create_user, find_user_by_email
    from db import ensure_schema, get_db

    email = f"diag.auth.{int(time.time())}@example.com"
    try:
        client = get_db()
        ensure_schema(client)
        print("schema ok")
        try:
            r = client.execute("SELECT COUNT(*) FROM users")
            print("users count", r.rows)
        except Exception as e:
            print("count fail", type(e).__name__, e)
            traceback.print_exc()
        print("creating", email)
        u = create_user(client, name="Diag User", email=email, password="SenhaForte123!")
        print("CREATED id=", u.get("id"), "avatar=", u.get("avatar_url"))
        again = find_user_by_email(client, email)
        print("find_by_email", bool(again), "id=", again.get("id") if again else None)
    except Exception as e:
        print("ERR", type(e).__name__, e)
        traceback.print_exc()


if __name__ == "__main__":
    main()
