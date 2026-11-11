from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
pragma foreign_keys = on;

create table if not exists documents(
  id text primary key,
  project_id text not null,
  sha256 text not null,
  filename text not null,
  mime_type text not null,
  source_path text not null,
  created_at text not null,
  parsed_at text,
  parser_version text,
  ocr_used integer default 0,
  ocr_confidence real,
  status text not null
);

create table if not exists pages(
  id text primary key,
  document_id text not null,
  page_number integer not null,
  width real,
  height real,
  render_path text,
  text_layer_available integer default 1
);

create table if not exists blocks(
  id text primary key,
  document_id text not null,
  page_id text,
  block_type text not null,
  text text,
  bbox_json text,
  reading_order integer,
  heading_path text
);

create table if not exists tables(
  id text primary key,
  document_id text not null,
  page_id text,
  bbox_json text,
  caption text,
  parser text
);

create table if not exists cells(
  id text primary key,
  table_id text,
  document_id text not null,
  page_id text,
  sheet_name text,
  cell_ref text,
  row_index integer,
  col_index integer,
  text text,
  value_json text,
  bbox_json text
);

create table if not exists words(
  id text primary key,
  document_id text not null,
  page_id text not null,
  block_id text,
  text text not null,
  char_start integer,
  char_end integer,
  bbox_json text not null,
  word_index integer not null
);

create table if not exists chunks(
  id text primary key,
  document_id text not null,
  chunk_type text not null,
  text text not null,
  token_count integer,
  heading_path text,
  page_start integer,
  page_end integer,
  bbox_json text,
  word_ids_json text,
  cell_ids_json text,
  source_uri text not null
);

create virtual table if not exists chunks_fts
using fts5(id unindexed, document_id unindexed, text);

create table if not exists chunk_embeddings(
  chunk_id text primary key,
  document_id text not null,
  embedding_json text not null,
  updated_at text not null
);

create table if not exists claims(
  id text primary key,
  project_id text not null,
  run_id text not null,
  claim_text text not null,
  claim_type text,
  calculation_formula text,
  source_numbers_json text,
  status text not null,
  created_at text not null
);

create table if not exists citations(
  id text primary key,
  claim_id text not null,
  chunk_id text not null,
  document_id text not null,
  quote text not null,
  source_uri text not null,
  bbox_json text,
  verified integer not null default 0,
  verification_method text,
  verification_score real,
  failure_reason text,
  support_level text,
  support_reason text,
  support_judge_label text,
  support_judge_reason text,
  reviewer text,
  review_note text,
  reviewed_at text
);

create table if not exists runs(
  id text primary key,
  project_id text not null,
  run_type text not null,
  input_json text not null,
  output_json text,
  model text,
  started_at text not null,
  finished_at text,
  status text not null
);

create table if not exists audit_log(
  id text primary key,
  ts text not null,
  type text not null,
  payload_json text not null
);

create table if not exists ui_preferences(
  project_id text primary key,
  column_widths_json text not null,
  updated_at text not null
);

create table if not exists retrieval_preferences(
  project_id text primary key,
  preferences_json text not null,
  updated_at text not null
);

create table if not exists review_tasks(
  id text primary key,
  project_id text not null,
  claim_id text not null,
  status text not null,
  assignee text,
  priority text not null,
  created_at text not null,
  updated_at text not null,
  resolved_at text
);

create table if not exists review_comments(
  id text primary key,
  task_id text not null,
  author text not null,
  body text not null,
  created_at text not null
);

create table if not exists users(
  id text primary key,
  email text unique not null,
  display_name text,
  created_at text not null
);

create table if not exists teams(
  id text primary key,
  name text not null,
  created_at text not null
);

create table if not exists team_members(
  team_id text not null,
  user_id text not null,
  role text not null check(role in ('owner','admin','member','viewer')),
  created_at text not null,
  primary key(team_id, user_id)
);

create table if not exists project_acl(
  project_id text not null,
  principal_type text not null check(principal_type in ('team','user')),
  principal_id text not null,
  role text not null check(role in ('owner','editor','reviewer','viewer')),
  created_at text not null,
  primary key(project_id, principal_type, principal_id)
);

create table if not exists background_jobs(
  id text primary key,
  project_id text not null,
  job_type text not null,
  status text not null check(status in ('queued','running','succeeded','failed','canceled')),
  input_json text not null,
  output_json text,
  error text,
  actor_user_id text,
  actor_email text,
  request_id text,
  created_at text not null,
  updated_at text not null,
  started_at text,
  finished_at text
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "citations", "support_level", "text")
        _ensure_column(conn, "citations", "support_reason", "text")
        _ensure_column(conn, "citations", "support_judge_label", "text")
        _ensure_column(conn, "citations", "support_judge_reason", "text")
        _ensure_column(conn, "citations", "reviewer", "text")
        _ensure_column(conn, "citations", "review_note", "text")
        _ensure_column(conn, "citations", "reviewed_at", "text")
        _ensure_column(conn, "claims", "calculation_formula", "text")
        _ensure_column(conn, "claims", "source_numbers_json", "text")
        _ensure_column(conn, "documents", "ocr_confidence", "real")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")
