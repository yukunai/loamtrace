from __future__ import annotations

import uuid
from typing import Optional

from loamtrace.db import connect
from loamtrace.services.audit import write_audit
from loamtrace.services.paths import ensure_project, project_db_path
from loamtrace.services.time import now_iso


ACTIVE_STATUSES = {"open", "in_review"}


def create_review_task(
    project_id: str,
    claim_id: str,
    assignee: Optional[str] = None,
    priority: str = "normal",
) -> dict:
    ensure_project(project_id)
    claim = _get_claim(project_id, claim_id)
    now = now_iso()
    with connect(project_db_path(project_id)) as conn:
        existing = conn.execute(
            """
            select * from review_tasks
            where project_id = ? and claim_id = ? and status in ('open', 'in_review')
            order by created_at desc
            limit 1
            """,
            (project_id, claim_id),
        ).fetchone()
        if existing:
            task_id = existing["id"]
            conn.execute(
                """
                update review_tasks
                set assignee = coalesce(?, assignee),
                    priority = ?,
                    updated_at = ?
                where id = ?
                """,
                (assignee, priority, now, task_id),
            )
            event_type = "review_task_reused"
        else:
            task_id = f"review_{uuid.uuid4().hex}"
            conn.execute(
                """
                insert into review_tasks(
                  id, project_id, claim_id, status, assignee, priority,
                  created_at, updated_at, resolved_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, project_id, claim_id, "open", assignee, priority, now, now, None),
            )
            event_type = "review_task_created"

    write_audit(
        project_id,
        event_type,
        {"task_id": task_id, "claim_id": claim_id, "assignee": assignee, "priority": priority},
    )
    return _get_review_task(project_id, task_id, claim)


def list_review_tasks(project_id: str, status: Optional[str] = None) -> list[dict]:
    ensure_project(project_id)
    params = [project_id]
    status_filter = ""
    if status:
        status_filter = "and t.status = ?"
        params.append(status)
    with connect(project_db_path(project_id)) as conn:
        rows = conn.execute(
            f"""
            select
              t.*,
              c.claim_text,
              c.status as claim_status,
              count(rc.id) as comment_count
            from review_tasks t
            join claims c on c.id = t.claim_id
            left join review_comments rc on rc.task_id = t.id
            where t.project_id = ?
            {status_filter}
            group by t.id
            order by
              case t.status
                when 'open' then 0
                when 'in_review' then 1
                when 'resolved' then 2
                else 3
              end,
              t.updated_at desc
            """,
            tuple(params),
        ).fetchall()
    return [_task_from_row(row) for row in rows]


def update_review_task(
    project_id: str,
    task_id: str,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
) -> dict:
    ensure_project(project_id)
    _get_review_task(project_id, task_id)
    now = now_iso()
    fields = []
    params = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
        fields.append("resolved_at = ?")
        params.append(now if status in {"resolved", "dismissed"} else None)
    if assignee is not None:
        fields.append("assignee = ?")
        params.append(assignee)
    if priority is not None:
        fields.append("priority = ?")
        params.append(priority)
    if fields:
        fields.append("updated_at = ?")
        params.append(now)
        params.extend([project_id, task_id])
        with connect(project_db_path(project_id)) as conn:
            conn.execute(
                f"""
                update review_tasks
                set {", ".join(fields)}
                where project_id = ? and id = ?
                """,
                tuple(params),
            )
    write_audit(
        project_id,
        "review_task_updated",
        {"task_id": task_id, "status": status, "assignee": assignee, "priority": priority},
    )
    return _get_review_task(project_id, task_id)


def add_review_comment(project_id: str, task_id: str, author: str, body: str) -> dict:
    ensure_project(project_id)
    _get_review_task(project_id, task_id)
    now = now_iso()
    comment_id = f"comment_{uuid.uuid4().hex}"
    with connect(project_db_path(project_id)) as conn:
        conn.execute(
            """
            insert into review_comments(id, task_id, author, body, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (comment_id, task_id, author, body, now),
        )
        conn.execute(
            "update review_tasks set updated_at = ? where project_id = ? and id = ?",
            (now, project_id, task_id),
        )
    write_audit(
        project_id,
        "review_comment_added",
        {"task_id": task_id, "comment_id": comment_id, "author": author},
    )
    return _get_review_task(project_id, task_id)


def _get_claim(project_id: str, claim_id: str) -> dict:
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            "select * from claims where project_id = ? and id = ?",
            (project_id, claim_id),
        ).fetchone()
    if not row:
        raise KeyError("claim_not_found")
    return dict(row)


def _get_review_task(project_id: str, task_id: str, claim: Optional[dict] = None) -> dict:
    with connect(project_db_path(project_id)) as conn:
        row = conn.execute(
            """
            select
              t.*,
              c.claim_text,
              c.status as claim_status,
              count(rc.id) as comment_count
            from review_tasks t
            join claims c on c.id = t.claim_id
            left join review_comments rc on rc.task_id = t.id
            where t.project_id = ? and t.id = ?
            group by t.id
            """,
            (project_id, task_id),
        ).fetchone()
        comments = conn.execute(
            """
            select id, task_id, author, body, created_at
            from review_comments
            where task_id = ?
            order by created_at asc
            """,
            (task_id,),
        ).fetchall()
    if not row:
        raise KeyError("review_task_not_found")
    task = _task_from_row(row)
    if claim:
        task["claim_text"] = claim["claim_text"]
        task["claim_status"] = claim["status"]
    task["comments"] = [dict(comment) for comment in comments]
    return task


def _task_from_row(row) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "claim_id": row["claim_id"],
        "claim_text": row["claim_text"],
        "claim_status": row["claim_status"],
        "status": row["status"],
        "assignee": row["assignee"],
        "priority": row["priority"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "resolved_at": row["resolved_at"],
        "comment_count": row["comment_count"],
    }
