from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("LOAMTRACE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("LOAMTRACE_API_PORT", "8000"))
    uvicorn.run("loamtrace.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
