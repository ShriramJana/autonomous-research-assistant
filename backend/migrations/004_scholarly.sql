-- Connected sources (scholarly): per-report flag mirroring browse_web.
alter table reports add column if not exists scholarly boolean not null default false;
