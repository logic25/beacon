-- Beacon Analytics Schema for Supabase
-- Run this in Supabase SQL Editor to create the tables.
-- These replace the SQLite tables that get wiped on every Railway deploy.

-- Main interactions table (every Beacon question/answer)
create table if not exists beacon_interactions (
  id bigint generated always as identity primary key,
  timestamp text not null,
  user_id text not null,
  user_name text,
  space_name text,
  question text not null,
  response text,
  command text,
  answered boolean not null default true,
  response_length integer,
  had_sources boolean,
  sources_used text,
  tokens_used integer,
  cost_usd numeric(10, 6),
  response_time_ms integer,
  confidence numeric(5, 4),
  topic text
);

create index if not exists idx_bi_timestamp on beacon_interactions(timestamp);
create index if not exists idx_bi_user on beacon_interactions(user_id);
create index if not exists idx_bi_topic on beacon_interactions(topic);

-- API usage tracking (Anthropic, Pinecone, Voyage costs)
create table if not exists beacon_api_usage (
  id bigint generated always as identity primary key,
  timestamp text not null,
  api_name text not null,
  operation text not null,
  tokens_used integer,
  cost_usd numeric(10, 6)
);

create index if not exists idx_bau_timestamp on beacon_api_usage(timestamp);
create index if not exists idx_bau_api on beacon_api_usage(api_name);

-- Team correction suggestions
create table if not exists beacon_suggestions (
  id bigint generated always as identity primary key,
  timestamp text not null,
  user_id text not null,
  user_name text,
  wrong_answer text not null,
  correct_answer text not null,
  topics text,
  status text default 'pending',
  reviewed_by text,
  reviewed_at text
);

create index if not exists idx_bs_status on beacon_suggestions(status);

-- Admin corrections
create table if not exists beacon_corrections (
  id bigint generated always as identity primary key,
  timestamp text not null,
  user_id text not null,
  user_name text,
  wrong_answer text not null,
  correct_answer text not null,
  topics text,
  applied boolean default true
);

-- User feedback / feature requests
create table if not exists beacon_feedback (
  id bigint generated always as identity primary key,
  timestamp text not null,
  user_id text not null,
  user_name text,
  feedback_text text not null,
  status text default 'new',
  responded_by text,
  responded_at text,
  roadmap_status text default 'backlog',
  priority text default 'medium',
  target_quarter text,
  notes text
);

-- Enable Row Level Security but allow service role full access
-- (Beacon backend uses service_role key)
alter table beacon_interactions enable row level security;
alter table beacon_api_usage enable row level security;
alter table beacon_suggestions enable row level security;
alter table beacon_corrections enable row level security;
alter table beacon_feedback enable row level security;

-- Service role bypass policies (the Railway backend uses service_role key)
create policy "Service role full access" on beacon_interactions for all using (true) with check (true);
create policy "Service role full access" on beacon_api_usage for all using (true) with check (true);
create policy "Service role full access" on beacon_suggestions for all using (true) with check (true);
create policy "Service role full access" on beacon_corrections for all using (true) with check (true);
create policy "Service role full access" on beacon_feedback for all using (true) with check (true);

-- Read access for authenticated Ordino users (so the AI Usage page can query directly)
create policy "Authenticated read" on beacon_interactions for select using (auth.role() = 'authenticated');
create policy "Authenticated read" on beacon_api_usage for select using (auth.role() = 'authenticated');
create policy "Authenticated read" on beacon_feedback for select using (auth.role() = 'authenticated');
