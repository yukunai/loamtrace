import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(os.environ.get("LOAMTRACE_WORKSPACE_ROOT", APP_ROOT / "workspace")).expanduser()
PROJECTS_ROOT = WORKSPACE_ROOT / "projects"
SERVER_MODE = os.environ.get("LOAMTRACE_SERVER_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
