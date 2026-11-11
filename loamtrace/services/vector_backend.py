from __future__ import annotations

import sqlite3
from functools import lru_cache


@lru_cache(maxsize=1)
def vector_backend_status() -> dict:
    try:
        import sqlite_vec
    except ModuleNotFoundError:
        return {
            "backend": "json-fallback",
            "sqlite_vec_available": False,
            "reason": "sqlite_vec_not_installed",
        }

    conn = sqlite3.connect(":memory:")
    try:
        if not hasattr(conn, "load_extension"):
            return {
                "backend": "json-fallback",
                "sqlite_vec_available": False,
                "reason": "sqlite_load_extension_unavailable",
            }
        sqlite_vec.load(conn)
        version = conn.execute("select vec_version()").fetchone()[0]
        return {
            "backend": "sqlite-vec",
            "sqlite_vec_available": True,
            "version": version,
        }
    except Exception as exc:
        return {
            "backend": "json-fallback",
            "sqlite_vec_available": False,
            "reason": f"sqlite_vec_load_failed:{type(exc).__name__}",
        }
    finally:
        conn.close()
