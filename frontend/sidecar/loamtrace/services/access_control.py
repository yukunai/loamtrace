from __future__ import annotations

from contextvars import ContextVar
from typing import Mapping, Optional

import loamtrace.config
from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path

LOCAL_ACTOR = {
    "id": "local",
    "email": "local@loamtrace.local",
    "display_name": "Local User",
    "team_id": None,
    "project_role": "owner",
    "mode": "desktop",
    "request_id": None,
}

_CURRENT_ACTOR: ContextVar[dict] = ContextVar("loamtrace_current_actor", default=LOCAL_ACTOR.copy())
_VALID_PROJECT_ROLES = {"viewer", "reviewer", "editor", "owner"}
_ROLE_RANK = {"viewer": 1, "reviewer": 2, "editor": 3, "owner": 4}
_PERMISSION_ROLE = {
    "read": "viewer",
    "review": "reviewer",
    "write": "editor",
    "edit": "editor",
    "export": "editor",
    "delete": "owner",
    "admin": "owner",
    "owner": "owner",
}


def get_current_actor() -> dict:
    return _CURRENT_ACTOR.get().copy()


def set_current_actor(actor: dict):
    return _CURRENT_ACTOR.set(normalize_actor(actor))


def reset_current_actor(token) -> None:
    _CURRENT_ACTOR.reset(token)


def actor_from_headers(headers: Optional[Mapping[str, str]]) -> dict:
    if headers is None:
        return LOCAL_ACTOR.copy()

    actor_id = _header(headers, "x-loamtrace-actor-id")
    team_id = _header(headers, "x-loamtrace-team-id")
    mode = "team" if actor_id or team_id else "desktop"
    default_project_role = LOCAL_ACTOR["project_role"] if mode == "desktop" else "viewer"
    return normalize_actor(
        {
            "id": actor_id or LOCAL_ACTOR["id"],
            "email": _header(headers, "x-loamtrace-actor-email") or LOCAL_ACTOR["email"],
            "display_name": _header(headers, "x-loamtrace-actor-name") or LOCAL_ACTOR["display_name"],
            "team_id": team_id,
            "project_role": _header(headers, "x-loamtrace-project-role") or default_project_role,
            "mode": mode,
            "request_id": _header(headers, "x-request-id"),
        }
    )


def normalize_actor(actor: dict) -> dict:
    normalized = LOCAL_ACTOR.copy()
    normalized.update({key: value for key, value in actor.items() if key in normalized})
    if normalized["project_role"] not in _VALID_PROJECT_ROLES:
        normalized["project_role"] = "viewer"
    if normalized["mode"] not in {"desktop", "team"}:
        normalized["mode"] = "desktop"
    return normalized


def check_project_access(project_id: str, permission: str, actor: Optional[dict] = None) -> dict:
    current = normalize_actor(actor or get_current_actor())
    reason = "desktop_noop" if current["mode"] == "desktop" else "team_acl_not_enforced_s1"
    return {
        "allowed": True,
        "mode": current["mode"],
        "reason": reason,
        "project_id": project_id,
        "permission": permission,
        "actor_id": current["id"],
        "project_role": current["project_role"],
    }


def require_project_access(project_id: str, permission: str, actor: Optional[dict] = None) -> dict:
    decision = check_project_access(project_id, permission, actor)
    if not decision["allowed"]:
        raise PermissionError(f"{permission} access denied for project {project_id}")
    return decision


def dry_run_route_guard(project_id: str, permission: str, actor: Optional[dict] = None) -> dict:
    preview = preview_project_access(project_id, permission, actor)
    server_mode = bool(loamtrace.config.SERVER_MODE)
    if not server_mode:
        return {
            **preview,
            "allowed": True,
            "enforced": False,
            "would_block": False,
            "server_mode": False,
            "guard_reason": "server_mode_disabled",
        }

    would_block = not preview["allowed"]
    return {
        **preview,
        "enforced": True,
        "would_block": would_block,
        "server_mode": True,
        "guard_reason": "server_mode_would_allow" if not would_block else "server_mode_would_block",
    }


def guarded_project_access(project_id: str, permission: str, actor: Optional[dict] = None) -> dict:
    guard = dry_run_route_guard(project_id, permission, actor)
    if not guard["server_mode"]:
        return guard

    if not _project_has_owner_acl(project_id):
        return {
            **guard,
            "allowed": True,
            "enforced": False,
            "would_block": False,
            "guard_reason": "owner_bootstrap_required",
        }

    if guard["would_block"]:
        raise PermissionError(f"{permission} access denied for project {project_id}")
    return guard


def preview_project_access(project_id: str, permission: str, actor: Optional[dict] = None) -> dict:
    current = normalize_actor(actor or get_current_actor())
    required_role = _required_role(permission)
    if current["mode"] == "desktop":
        return {
            "allowed": True,
            "enforced": False,
            "mode": "desktop",
            "reason": "desktop_owner_preview",
            "project_id": project_id,
            "permission": permission,
            "required_role": required_role,
            "matched_role": "owner",
            "matched_principal_type": "local",
            "matched_principal_id": current["id"],
            "actor_id": current["id"],
        }

    entries = _actor_acl_entries(project_id, current)
    best = _best_entry(entries)
    if best is None:
        return {
            "allowed": False,
            "enforced": False,
            "mode": "team",
            "reason": "no_matching_acl_preview",
            "project_id": project_id,
            "permission": permission,
            "required_role": required_role,
            "matched_role": None,
            "matched_principal_type": None,
            "matched_principal_id": None,
            "actor_id": current["id"],
        }

    allowed = _ROLE_RANK[best["role"]] >= _ROLE_RANK[required_role]
    return {
        "allowed": allowed,
        "enforced": False,
        "mode": "team",
        "reason": "acl_preview_allowed" if allowed else "acl_preview_insufficient_role",
        "project_id": project_id,
        "permission": permission,
        "required_role": required_role,
        "matched_role": best["role"],
        "matched_principal_type": best["principal_type"],
        "matched_principal_id": best["principal_id"],
        "actor_id": current["id"],
    }


def actor_audit_fields(actor: Optional[dict] = None) -> dict:
    current = normalize_actor(actor or get_current_actor())
    return {
        "actor_user_id": current["id"],
        "actor_email": current["email"],
        "team_id": current["team_id"],
        "project_role": current["project_role"],
        "request_id": current["request_id"],
    }


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    value = headers.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _required_role(permission: str) -> str:
    return _PERMISSION_ROLE.get(permission, "viewer")


def _actor_acl_entries(project_id: str, actor: dict) -> list[dict]:
    ensure_project(project_id)
    principals = [("user", actor["id"])]
    if actor.get("team_id"):
        principals.append(("team", actor["team_id"]))

    clauses = " or ".join(["(principal_type = ? and principal_id = ?)"] * len(principals))
    params: list[str] = [project_id]
    for principal_type, principal_id in principals:
        params.extend([principal_type, principal_id])

    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"""
            select principal_type, principal_id, role
            from project_acl
            where project_id = ? and ({clauses})
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _best_entry(entries: list[dict]) -> Optional[dict]:
    if not entries:
        return None
    return max(entries, key=lambda entry: _ROLE_RANK[entry["role"]])


def _project_has_owner_acl(project_id: str) -> bool:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select 1 from project_acl where project_id = ? and role = 'owner' limit 1",
            (project_id,),
        ).fetchone()
    return row is not None
