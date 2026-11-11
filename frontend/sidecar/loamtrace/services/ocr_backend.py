from __future__ import annotations

import os
import shutil
import site
import sys
from pathlib import Path
from typing import Optional


def find_tesseract() -> Optional[str]:
    configured = os.environ.get("TESSERACT_CMD")
    if configured:
        path = Path(configured).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    for root in _bundled_ocr_roots():
        candidate = root / "bin" / "tesseract"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    path = shutil.which("tesseract")
    if path:
        return path

    for root in [site.USER_BASE, str(Path.home() / ".local")]:
        if not root:
            continue
        candidate = Path(root) / "bin" / "tesseract"
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    for candidate in sorted((Path.home() / "Library" / "Python").glob("*/bin/tesseract")):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def tesseract_env(tesseract_path: str) -> dict[str, str]:
    env = dict(os.environ)
    path = Path(tesseract_path)
    bundled_tessdata = path.parent.parent / "share" / "tessdata"
    if bundled_tessdata.exists():
        env.setdefault("TESSDATA_PREFIX", str(bundled_tessdata))
    return env


def _bundled_ocr_roots() -> list[Path]:
    roots = []
    configured = os.environ.get("LOAMTRACE_OCR_ROOT")
    if configured:
        roots.append(Path(configured).expanduser())

    cwd = Path.cwd()
    roots.extend([cwd / "ocr", cwd.parent / "ocr"])

    executable = Path(sys.executable)
    for parent in [executable.parent, *executable.parents]:
        roots.append(parent / "ocr")
        if parent.name == "MacOS":
            roots.append(parent.parent / "Resources" / "app" / "ocr")

    unique = []
    seen = set()
    for root in roots:
        resolved = root.resolve() if root.exists() else root
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return unique


def ocr_backend_status() -> dict:
    path = find_tesseract()
    if not path:
        return {
            "backend": "unavailable",
            "available": False,
            "reason": "tesseract_not_found",
        }
    return {
        "backend": "tesseract",
        "available": True,
        "path": path,
    }
