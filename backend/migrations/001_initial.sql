-- ARA auth + history schema. Apply via Supabase SQL editor or psql.
-- Fully idempotent: tables/indexes use IF NOT EXISTS; RLS policies use
-- DROP POLICY IF EXISTS before re-creation.

-- ============================================================================
-- 1. user_profiles  — app-level user data, 1:1 with auth.users
-- ============================================================================
create table if not exists user_profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  display_name text
);

-- ============================================================================
-- 2. reports  — the main entity. owner_id + is_sample + share_token define
--    the three access paths, ALL enforced in Python (the backend uses the
--    service-role key, which bypasses RLS). The RLS policies below cover
--    only owner + is_sample as defense-in-depth for any future anon-key
--    access — share_token reads are intentionally not gated by RLS.
-- ============================================================================
create table if not exists reports (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid not null references auth.users(id) on delete cascade,
  question        text not null,
  status          text not null check (status in ('running','completed','error')),
  depth           text not null check (depth in ('quick','standard','deep')),
  browse_web      boolean not null default true,
  used_byok       boolean not null default false,
  is_sample       boolean not null default false,
  share_token     uuid unique,
  cost_usd        numeric(10,6),
  report_payload  jsonb,
  error_message   text,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

create index if not exists reports_owner_created_idx
  on reports (owner_id, created_at desc);

create index if not exists reports_sample_idx
  on reports (is_sample) where is_sample;

-- ============================================================================
-- 3. report_events  — append-only event log; drives SSE replay
-- ============================================================================
create table if not exists report_events (
  id          bigserial primary key,
  report_id   uuid not null references reports(id) on delete cascade,
  event       jsonb not null,
  created_at  timestamptz not null default now()
);

create index if not exists report_events_report_idx
  on report_events (report_id, id);

-- ============================================================================
-- RLS — defense-in-depth. Backend uses the service role (bypasses RLS) and
-- enforces access in Python. If anything ever connects with the anon key,
-- these policies make sure cross-account leakage is impossible.
-- ============================================================================
alter table user_profiles  enable row level security;
alter table reports        enable row level security;
alter table report_events  enable row level security;

-- user_profiles: own row only
drop policy if exists user_profiles_select_own on user_profiles;
create policy user_profiles_select_own on user_profiles
  for select using (auth.uid() = id);

drop policy if exists user_profiles_upsert_own on user_profiles;
create policy user_profiles_upsert_own on user_profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

-- reports: own row + public samples
drop policy if exists reports_select_own_or_sample on reports;
create policy reports_select_own_or_sample on reports
  for select using (auth.uid() = owner_id or is_sample = true);

drop policy if exists reports_modify_own on reports;
create policy reports_modify_own on reports
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- report_events: visibility joins on the owning report
drop policy if exists report_events_select on report_events;
create policy report_events_select on report_events
  for select using (
    exists (
      select 1 from reports r
      where r.id = report_events.report_id
        and (auth.uid() = r.owner_id or r.is_sample = true)
    )
  );

drop policy if exists report_events_modify on report_events;
create policy report_events_modify on report_events
  for all using (
    exists (
      select 1 from reports r
      where r.id = report_events.report_id and auth.uid() = r.owner_id
    )
  );
