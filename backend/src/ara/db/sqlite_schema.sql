-- SQLite schema for local mode. Mirrors migrations 001-003 with SQLite types:
-- uuid -> TEXT, timestamptz -> TEXT (ISO-8601 UTC), jsonb -> TEXT, boolean -> INTEGER.
create table if not exists reports (
  id              text primary key,
  owner_id        text not null,
  question        text not null,
  status          text not null check (status in ('running','completed','error')),
  depth           text not null check (depth in ('quick','standard','deep')),
  browse_web      integer not null default 1,
  used_byok       integer not null default 0,
  is_sample       integer not null default 0,
  share_token     text unique,
  cost_usd        real,
  report_payload  text,
  error_message   text,
  tavily_searches integer not null default 0,
  created_at      text not null,
  completed_at    text
);
create index if not exists reports_owner_created_idx on reports (owner_id, created_at desc);
create index if not exists reports_sample_idx on reports (is_sample);

create table if not exists report_events (
  id          integer primary key autoincrement,
  report_id   text not null references reports(id) on delete cascade,
  event       text not null,
  created_at  text not null
);
create index if not exists report_events_report_idx on report_events (report_id, id);

create table if not exists user_credentials (
  user_id                   text primary key,
  active_provider           text not null default 'free'
                              check (active_provider in ('free','anthropic','openai')),
  anthropic_key_ciphertext  text,
  openai_key_ciphertext     text,
  openai_base_url           text,
  openai_model              text,
  tavily_key_ciphertext     text,
  updated_at                text not null
);
