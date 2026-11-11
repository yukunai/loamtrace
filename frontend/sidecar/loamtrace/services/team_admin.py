from __future__ import annotations

import uuid
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.time import now_iso

TEAM_MEMBER_ROLES = {"owner", "admin", "member", "viewer"}
PROJECT_ACL_ROLES = {"owner", "editor", "reviewer", "viewer"}
PRINCIPAL_TYPES = {"team", "user"}


def bootstrap_local_admin(
    project_id: str,
    email: str = "local@loamtrace.local",
    display_name: str = "Local Admin",
) -> dict:
    user = upsert_user(project_id, None, email, display_name)
    # 安全：bootstrap 仅用于"尚无 owner"的初始化。若已存在 owner 且不是同一用户，
    # 必须拒绝——否则未授权 actor 可经未守卫的 /api/team/bootstrap-admin 自授 owner，
    # 绕过整个 ACL 模型（server 模式下的提权）。对同一 owner 幂等以保留桌面便利。
    with connect(project_db_path(project_id)) as conn:
        existing_owner = conn.execute(
            "select principal_type, principal_id from project_acl"
            " where project_id = ? and role = 'owner'",
            (project_id,),
        ).fetchone()
    if existing_owner is not None and not (
        existing_owner["principal_type"] == "user"
        and existing_owner["principal_id"] == user["id"]
    ):
        raise ValueError("owner_already_exists")
    acl = set_project_acl(project_id, "user", user["id"], "owner")
    return {"project_id": project_id, "user": user, "acl": acl}


def acl_migration_diagnostics(project_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        user_count = conn.execute("select count(*) from users").fetchone()[0]
        team_count = conn.execute("select count(*) from teams").fetchone()[0]
        acl_count = conn.execute("select count(*) from project_acl where project_id = ?", (project_id,)).fetchone()[0]
        owner_count = conn.execute(
            "select count(*) from project_acl where project_id = ? and role = 'owner'",
            (project_id,),
        ).fetchone()[0]

    return {
        "project_id": project_id,
        "users": user_count,
        "teams": team_count,
        "acl_entries": acl_count,
        "owner_acl_entries": owner_count,
        "desktop_compatible": True,
        "enforcement_ready": owner_count > 0,
        "enforcement_enabled": False,
        "recommended_action": "none" if owner_count > 0 else "bootstrap_local_admin",
        "notes": [
            "desktop mode remains no-op compatible",
            "route enforcement is disabled",
            "owner ACL is required before any future server-mode enforcement",
        ],
    }


def upsert_user(project_id: str, user_id: Optional[str], email: str, display_name: Optional[str] = None) -> dict:
    ensure_project(project_id)
    normalized_email = _require_text(email, "email").lower()
    now = now_iso()
    with connect(project_db_path(project_id)) as conn:
        existing = conn.execute("select * from users where email = ?", (normalized_email,)).fetchone()
        if existing:
            resolved_id = existing["id"]
            conn.execute(
                "update users set display_name = ? where id = ?",
                (display_name, resolved_id),
            )
        else:
            resolved_id = user_id or f"user_{uuid.uuid4().hex}"
            conn.execute(
                """
                insert into users(id, email, display_name, created_at)
                values (?, ?, ?, ?)
                """,
                (resolved_id, normalized_email, display_name, now),
            )
        return _get_user(conn, resolved_id)


def list_users(project_id: str) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute("select * from users order by email asc").fetchall()
    return [dict(row) for row in rows]


def upsert_team(project_id: str, team_id: Optional[str], name: str) -> dict:
    ensure_project(project_id)
    resolved_id = team_id or f"team_{uuid.uuid4().hex}"
    now = now_iso()
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into teams(id, name, created_at)
            values (?, ?, ?)
            on conflict(id) do update set name = excluded.name
            """,
            (resolved_id, _require_text(name, "name"), now),
        )
        return _get_team(conn, resolved_id)


def list_teams(project_id: str) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute("select * from teams order by name asc").fetchall()
    return [dict(row) for row in rows]


def set_team_member(project_id: str, team_id: str, user_id: str, role: str) -> dict:
    _validate(role, TEAM_MEMBER_ROLES, "role")
    ensure_project(project_id)
    now = now_iso()
    with connect(project_db_path(project_id)) as conn:
        _require_existing(conn, "teams", team_id, "team_id")
        _require_existing(conn, "users", user_id, "user_id")
        conn.execute(
            """
            insert into team_members(team_id, user_id, role, created_at)
            values (?, ?, ?, ?)
            on conflict(team_id, user_id) do update set role = excluded.role
            """,
            (team_id, user_id, role, now),
        )
        return _get_team_member(conn, team_id, user_id)


def list_team_members(project_id: str, team_id: Optional[str] = None) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        if team_id:
            rows = conn.execute(
                """
                select tm.*, u.email, u.display_name
                from team_members tm
                left join users u on u.id = tm.user_id
                where tm.team_id = ?
                order by u.email asc, tm.user_id asc
                """,
                (team_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select tm.*, u.email, u.display_name
                from team_members tm
                left join users u on u.id = tm.user_id
                order by tm.team_id asc, u.email asc, tm.user_id asc
                """
            ).fetchall()
    return [dict(row) for row in rows]


def delete_team_member(project_id: str, team_id: str, user_id: str) -> dict:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        cursor = conn.execute(
            "delete from team_members where team_id = ? and user_id = ?",
            (team_id, user_id),
        )
    if cursor.rowcount == 0:
        raise KeyError("team_member_not_found")
    return {"deleted": True, "team_id": team_id, "user_id": user_id}


def set_project_acl(project_id: str, principal_type: str, principal_id: str, role: str) -> dict:
    _validate(principal_type, PRINCIPAL_TYPES, "principal_type")
    _validate(role, PROJECT_ACL_ROLES, "role")
    ensure_project(project_id)
    now = now_iso()
    with connect(project_db_path(project_id)) as conn:
        table = "users" if principal_type == "user" else "teams"
        _require_existing(conn, table, principal_id, "principal_id")
        conn.execute(
            """
            insert into project_acl(project_id, principal_type, principal_id, role, created_at)
            values (?, ?, ?, ?, ?)
            on conflict(project_id, principal_type, principal_id) do update set role = excluded.role
            """,
            (project_id, principal_type, principal_id, role, now),
        )
        return _get_project_acl(conn, project_id, principal_type, principal_id)


def list_project_acl(project_id: str) -> list[dict]:
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            """
            select *
            from project_acl
            where project_id = ?
            order by principal_type asc, principal_id asc
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_project_acl(project_id: str, principal_type: str, principal_id: str) -> dict:
    _validate(principal_type, PRINCIPAL_TYPES, "principal_type")
    ensure_project(project_id)
    with connect(project_db_path(project_id)) as conn:
        cursor = conn.execute(
            "delete from project_acl where project_id = ? and principal_type = ? and principal_id = ?",
            (project_id, principal_type, principal_id),
        )
    if cursor.rowcount == 0:
        raise KeyError("project_acl_not_found")
    return {"deleted": True, "project_id": project_id, "principal_type": principal_type, "principal_id": principal_id}


def _get_user(conn, user_id: str) -> dict:
    row = conn.execute("select * from users where id = ?", (user_id,)).fetchone()
    if not row:
        raise KeyError("user_not_found")
    return dict(row)


def _get_team(conn, team_id: str) -> dict:
    row = conn.execute("select * from teams where id = ?", (team_id,)).fetchone()
    if not row:
        raise KeyError("team_not_found")
    return dict(row)


def _get_team_member(conn, team_id: str, user_id: str) -> dict:
    row = conn.execute(
        """
        select tm.*, u.email, u.display_name
        from team_members tm
        left join users u on u.id = tm.user_id
        where tm.team_id = ? and tm.user_id = ?
        """,
        (team_id, user_id),
    ).fetchone()
    if not row:
        raise KeyError("team_member_not_found")
    return dict(row)


def _get_project_acl(conn, project_id: str, principal_type: str, principal_id: str) -> dict:
    row = conn.execute(
        """
        select *
        from project_acl
        where project_id = ? and principal_type = ? and principal_id = ?
        """,
        (project_id, principal_type, principal_id),
    ).fetchone()
    if not row:
        raise KeyError("project_acl_not_found")
    return dict(row)


def _require_existing(conn, table: str, entity_id: str, field: str) -> None:
    row = conn.execute(f"select id from {table} where id = ?", (entity_id,)).fetchone()
    if not row:
        raise KeyError(f"{field}_not_found")


def _require_text(value: str, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field}_required")
    return stripped


def _validate(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid_{field}")
