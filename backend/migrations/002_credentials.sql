-- Phase 2b: encrypted per-user provider credentials + Tavily usage accounting.
-- Idempotent. Apply via Supabase SQL editor or psql, like 001_initial.sql.

create table if not exists user_credentials (
  user_id                   uuid primary key references auth.users(id) on delete cascade,
  active_provider           text not null default 'free'
                              check (active_provider in ('free','anthropic','openai')),
  anthropic_key_ciphertext  text,
  openai_key_ciphertext     text,
  openai_base_url           text,
  openai_model              text,
  updated_at                timestamptz not null default now()
);

alter table reports
  add column if not exists tavily_searches int not null default 0;

alter table user_credentials enable row level security;

drop policy if exists user_credentials_own on user_credentials;
create policy user_credentials_own on user_credentials
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
