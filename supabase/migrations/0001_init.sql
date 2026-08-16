-- REDLY Cloud — initial schema
--
-- Design notes:
--   * auth.users (Supabase Auth) is the identity source of truth. Every
--     user-owned table has a `user_id uuid references auth.users(id)` and
--     RLS restricts all access to `auth.uid() = user_id`.
--   * Desktop only ever holds the anon key + a user's own JWT — RLS is what
--     makes "users can only access their own data" true even if the anon key
--     leaks, since the anon key alone grants nothing without a valid session.
--   * organizations/subscriptions are stubbed as empty tables with FKs ready
--     but no enforcement logic anywhere yet (explicitly out of scope now).
--   * Nothing here stores raw audio or full transcript audio — only text
--     metadata/settings/summaries the user explicitly chose to sync.
--
-- Idempotency: every statement below is safe to re-run against a project
-- this migration has already been applied to (partially or fully) — tables
-- use `if not exists`, functions use `or replace`, indexes use
-- `if not exists`, and policies/triggers are dropped-then-recreated with
-- `if exists` guards (Postgres has no `create policy/trigger if not
-- exists`). This is what makes it safe to paste into the SQL editor more
-- than once, e.g. after a partial failure or when double-checking setup.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- profiles — one row per auth.users row, created on signup via trigger.
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text,
    avatar_url text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
    for select using (auth.uid() = id);
drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
    for update using (auth.uid() = id);
drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own" on public.profiles
    for insert with check (auth.uid() = id);

-- Auto-create a profile row when a new auth user signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, display_name)
    values (new.id, new.raw_user_meta_data->>'display_name')
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------------
-- organizations / organization_members — foundation only, not enforced yet.
-- ---------------------------------------------------------------------------
create table if not exists public.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    owner_id uuid not null references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists public.organization_members (
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null default 'member',
    created_at timestamptz not null default now(),
    primary key (organization_id, user_id)
);

alter table public.organizations enable row level security;
alter table public.organization_members enable row level security;

drop policy if exists "organizations_select_member" on public.organizations;
create policy "organizations_select_member" on public.organizations
    for select using (
        owner_id = auth.uid()
        or id in (select organization_id from public.organization_members where user_id = auth.uid())
    );
drop policy if exists "organization_members_select_own" on public.organization_members;
create policy "organization_members_select_own" on public.organization_members
    for select using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- subscriptions — foundation only, no enforcement/billing logic yet.
-- ---------------------------------------------------------------------------
create table if not exists public.subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    plan text not null default 'free',
    status text not null default 'inactive',
    current_period_end timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

drop policy if exists "subscriptions_select_own" on public.subscriptions;
create policy "subscriptions_select_own" on public.subscriptions
    for select using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- agents — Custom Agents + predefined-role agents, synced from the desktop
-- local store. `client_id` is the desktop's own locally-generated id
-- (e.g. "agent-<hex>-<hex>") so sync can match local <-> cloud rows without
-- REDLY inventing a second id scheme on the desktop side.
-- ---------------------------------------------------------------------------
create table if not exists public.agents (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    client_id text not null,
    name text not null,
    base_role text,
    description text,
    custom_instructions text,
    personalization jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    unique (user_id, client_id)
);

create index if not exists agents_user_id_idx on public.agents(user_id);

alter table public.agents enable row level security;

drop policy if exists "agents_select_own" on public.agents;
create policy "agents_select_own" on public.agents
    for select using (auth.uid() = user_id);
drop policy if exists "agents_insert_own" on public.agents;
create policy "agents_insert_own" on public.agents
    for insert with check (auth.uid() = user_id);
drop policy if exists "agents_update_own" on public.agents;
create policy "agents_update_own" on public.agents
    for update using (auth.uid() = user_id);
drop policy if exists "agents_delete_own" on public.agents;
create policy "agents_delete_own" on public.agents
    for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- agent_knowledge — metadata only (filename, type, status, chunk count).
-- The actual document bytes/chunks/embeddings stay in the desktop's local
-- RAG service (packages/rag) — never uploaded here.
-- ---------------------------------------------------------------------------
create table if not exists public.agent_knowledge (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    agent_id uuid not null references public.agents(id) on delete cascade,
    filename text not null,
    document_type text,
    status text not null default 'ready',
    chunk_count integer not null default 0,
    created_at timestamptz not null default now()
);

create index if not exists agent_knowledge_agent_id_idx on public.agent_knowledge(agent_id);

alter table public.agent_knowledge enable row level security;

drop policy if exists "agent_knowledge_select_own" on public.agent_knowledge;
create policy "agent_knowledge_select_own" on public.agent_knowledge
    for select using (auth.uid() = user_id);
drop policy if exists "agent_knowledge_insert_own" on public.agent_knowledge;
create policy "agent_knowledge_insert_own" on public.agent_knowledge
    for insert with check (auth.uid() = user_id);
drop policy if exists "agent_knowledge_update_own" on public.agent_knowledge;
create policy "agent_knowledge_update_own" on public.agent_knowledge
    for update using (auth.uid() = user_id);
drop policy if exists "agent_knowledge_delete_own" on public.agent_knowledge;
create policy "agent_knowledge_delete_own" on public.agent_knowledge
    for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- conversations / messages — optional cloud sync of agent Q&A history.
-- Mirrors the desktop's local `agent_history_<id>.json` files. Raw meeting
-- audio is never stored here — text only, and only what the user chooses to
-- sync (see conversation_summaries for the privacy-conscious alternative).
-- ---------------------------------------------------------------------------
create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    agent_id uuid references public.agents(id) on delete set null,
    client_id text not null,
    title text,
    mode text not null default 'agent',
    started_at timestamptz not null default now(),
    ended_at timestamptz,
    created_at timestamptz not null default now(),
    unique (user_id, client_id)
);

create index if not exists conversations_user_id_idx on public.conversations(user_id);

alter table public.conversations enable row level security;

drop policy if exists "conversations_select_own" on public.conversations;
create policy "conversations_select_own" on public.conversations
    for select using (auth.uid() = user_id);
drop policy if exists "conversations_insert_own" on public.conversations;
create policy "conversations_insert_own" on public.conversations
    for insert with check (auth.uid() = user_id);
drop policy if exists "conversations_update_own" on public.conversations;
create policy "conversations_update_own" on public.conversations
    for update using (auth.uid() = user_id);
drop policy if exists "conversations_delete_own" on public.conversations;
create policy "conversations_delete_own" on public.conversations
    for delete using (auth.uid() = user_id);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

create index if not exists messages_conversation_id_idx on public.messages(conversation_id);

alter table public.messages enable row level security;

drop policy if exists "messages_select_own" on public.messages;
create policy "messages_select_own" on public.messages
    for select using (auth.uid() = user_id);
drop policy if exists "messages_insert_own" on public.messages;
create policy "messages_insert_own" on public.messages
    for insert with check (auth.uid() = user_id);
drop policy if exists "messages_delete_own" on public.messages;
create policy "messages_delete_own" on public.messages
    for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- conversation_summaries — a short generated summary instead of full
-- transcript content, for when a user wants history without syncing every
-- message body (see PRODUCT DIRECTION: never silently collect full content).
-- ---------------------------------------------------------------------------
create table if not exists public.conversation_summaries (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    summary text not null,
    created_at timestamptz not null default now()
);

alter table public.conversation_summaries enable row level security;

drop policy if exists "conversation_summaries_select_own" on public.conversation_summaries;
create policy "conversation_summaries_select_own" on public.conversation_summaries
    for select using (auth.uid() = user_id);
drop policy if exists "conversation_summaries_insert_own" on public.conversation_summaries;
create policy "conversation_summaries_insert_own" on public.conversation_summaries
    for insert with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- usage_events — lightweight product analytics. Metadata only: event name,
-- generic JSONB properties, app version, timestamps, optional token/latency
-- numbers. Never raw audio, never document/transcript content.
-- ---------------------------------------------------------------------------
create table if not exists public.usage_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete set null,
    event_name text not null,
    properties jsonb not null default '{}'::jsonb,
    app_version text,
    created_at timestamptz not null default now()
);

create index if not exists usage_events_user_id_idx on public.usage_events(user_id);
create index if not exists usage_events_event_name_idx on public.usage_events(event_name);
create index if not exists usage_events_created_at_idx on public.usage_events(created_at);

alter table public.usage_events enable row level security;

-- Analytics events are write-only from the client's perspective (insert
-- your own events; no read-back needed by the desktop app). Reads for
-- product-analytics dashboards go through the service role on the backend,
-- never through a client-held key.
drop policy if exists "usage_events_insert_own" on public.usage_events;
create policy "usage_events_insert_own" on public.usage_events
    for insert with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- usage_costs — per-request LLM usage/cost tracking, written by the FastAPI
-- backend (service role) after each LLM call. Not writable by the desktop
-- client directly.
-- ---------------------------------------------------------------------------
create table if not exists public.usage_costs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    provider text not null,
    model text not null,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    estimated_cost_usd numeric(10, 6),
    request_kind text,
    created_at timestamptz not null default now()
);

create index if not exists usage_costs_user_id_idx on public.usage_costs(user_id);
create index if not exists usage_costs_created_at_idx on public.usage_costs(created_at);

alter table public.usage_costs enable row level security;

drop policy if exists "usage_costs_select_own" on public.usage_costs;
create policy "usage_costs_select_own" on public.usage_costs
    for select using (auth.uid() = user_id);
-- No insert policy for anon/authenticated — only the backend's service role
-- (which bypasses RLS entirely) writes usage_costs.

-- ---------------------------------------------------------------------------
-- updated_at maintenance trigger, reused across tables that have the column.
-- ---------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
    before update on public.profiles
    for each row execute procedure public.set_updated_at();

drop trigger if exists agents_set_updated_at on public.agents;
create trigger agents_set_updated_at
    before update on public.agents
    for each row execute procedure public.set_updated_at();

drop trigger if exists subscriptions_set_updated_at on public.subscriptions;
create trigger subscriptions_set_updated_at
    before update on public.subscriptions
    for each row execute procedure public.set_updated_at();
