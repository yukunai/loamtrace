from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import loamtrace.config
from loamtrace.db import init_db


def safe_project_id(project_id: str) -> str:
    # 去除路径分隔符与首尾点/空白，防止 ".." / "." 逃出 PROJECTS_ROOT
    # （与 exports._snapshot_target_project_id 的清洗一致）
    safe_id = project_id.replace("/", "_").replace("\\", "_").strip(". ")
    if not safe_id:
        raise ValueError("invalid_project_id")
    return safe_id


def project_root(project_id: str) -> Path:
    safe_id = safe_project_id(project_id)
    return loamtrace.config.PROJECTS_ROOT / safe_id


def project_db_path(project_id: str) -> Path:
    return project_root(project_id) / "index" / "project.sqlite"


def ensure_project(project_id: str, name: Optional[str] = None) -> Path:
    root = project_root(project_id)
    for rel in [
        "sources/original",
        "sources/rendered_pages",
        "index",
        "notes",
        "slides",
        "runs",
        "exports",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    metadata = root / "project.json"
    if not metadata.exists():
        metadata.write_text(
            json.dumps({"id": project_id, "name": name or project_id}, indent=2),
            encoding="utf-8",
        )
    init_db(project_db_path(project_id))
    return root
