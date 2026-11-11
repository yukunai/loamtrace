from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.paths import project_db_path, project_root
from loamtrace.services.time import now_iso


def create_run_dir(project_id: str, run_id: str, run_type: str) -> Path:
    safe_ts = now_iso().replace(":", "-")
    safe_type = run_type.replace("/", "_")
    path = project_root(project_id) / "runs" / f"{safe_ts}_{safe_type}_{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_artifacts(
    project_id: str,
    run_id: str,
    run_type: str,
    artifacts: dict,
    logs: Optional[list[dict]] = None,
) -> Path:
    run_dir = create_run_dir(project_id, run_id, run_type)
    for filename, value in artifacts.items():
        path = run_dir / filename
        if filename.endswith(".md"):
            path.write_text(str(value), encoding="utf-8")
        else:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    log_path = run_dir / "logs.jsonl"
    with log_path.open("w", encoding="utf-8") as handle:
        for event in logs or []:
            handle.write(json.dumps({"ts": now_iso(), **event}, ensure_ascii=False) + "\n")
    return run_dir


def write_audit(project_id: str, event_type: str, payload: dict) -> None:
    event = {"ts": now_iso(), "type": event_type, **payload}
    root = project_root(project_id)
    log_path = root / "runs" / "decision_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            "insert into audit_log(id, ts, type, payload_json) values (?, ?, ?, ?)",
            (f"audit_{uuid.uuid4().hex}", event["ts"], event_type, json.dumps(payload)),
        )
