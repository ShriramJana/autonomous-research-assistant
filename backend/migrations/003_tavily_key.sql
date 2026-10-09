-- Local-mode project: optional per-user Tavily key (encrypted like the others).
alter table user_credentials add column if not exists tavily_key_ciphertext text;
