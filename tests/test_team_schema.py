import sqlite3

import pytest

from loamtrace.db import connect, init_db


def test_init_db_creates_team_server_schema(tmp_path):
    db_path = tmp_path / "project.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

        assert {"users", "teams", "team_members", "project_acl"}.issubset(tables)

        conn.execute(
            "insert into users(id, email, display_name, created_at) values (?, ?, ?, ?)",
            ("user_1", "user@example.test", "User One", "2026-06-10T00:00:00Z"),
        )
        conn.execute(
            "insert into teams(id, name, created_at) values (?, ?, ?)",
            ("team_1", "Team One", "2026-06-10T00:00:00Z"),
        )
        conn.execute(
            "insert into team_members(team_id, user_id, role, created_at) values (?, ?, ?, ?)",
            ("team_1", "user_1", "admin", "2026-06-10T00:00:00Z"),
        )
        conn.execute(
            """
            insert into project_acl(project_id, principal_type, principal_id, role, created_at)
            values (?, ?, ?, ?, ?)
            """,
            ("project_1", "team", "team_1", "editor", "2026-06-10T00:00:00Z"),
        )

        acl = conn.execute("select * from project_acl where project_id = ?", ("project_1",)).fetchone()
        assert acl["principal_type"] == "team"
        assert acl["role"] == "editor"


def test_team_server_schema_rejects_invalid_roles(tmp_path):
    db_path = tmp_path / "project.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "insert into team_members(team_id, user_id, role, created_at) values (?, ?, ?, ?)",
                ("team_1", "user_1", "superuser", "2026-06-10T00:00:00Z"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                insert into project_acl(project_id, principal_type, principal_id, role, created_at)
                values (?, ?, ?, ?, ?)
                """,
                ("project_1", "group", "team_1", "owner", "2026-06-10T00:00:00Z"),
            )


def test_init_db_adds_team_server_schema_to_existing_database(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table audit_log(
              id text primary key,
              ts text not null,
              type text not null,
              payload_json text not null
            )
            """
        )

    init_db(db_path)

    with connect(db_path) as conn:
        for table_name in ["users", "teams", "team_members", "project_acl"]:
            row = conn.execute(
                "select name from sqlite_master where type = 'table' and name = ?",
                (table_name,),
            ).fetchone()
            assert row["name"] == table_name
