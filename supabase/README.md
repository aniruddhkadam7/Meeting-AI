# REDLY Cloud — Supabase setup

This directory holds the SQL schema for REDLY Cloud (Stage 1-2 of the hybrid
migration — see `docs/cloud-migration.md`). Supabase provides Auth + Postgres;
nothing else in this directory runs a server.

## One-time setup

1. Create a project at https://supabase.com (free tier is enough for 10-50 beta users).
2. In the SQL editor, run `migrations/0001_init.sql` once, top to bottom (it's
   idempotent — safe to re-run if you're ever unsure whether it applied).
3. Project Settings -> API:
   - Copy the **Project URL**. Goes in both `apps/backend/.env` and the
     desktop's `SUPABASE_URL` (see `apps/desktop/.env.example`) as `SUPABASE_URL`.
   - Copy the **Publishable key** (`sb_publishable_...`). Desktop-only — put
     it in the desktop's `SUPABASE_ANON_KEY`. The backend has no use for
     this key; do not add it to `apps/backend/.env`.
   - Copy the **Secret key** (`sb_secret_...`). Backend-only — put it in
     `apps/backend/.env` as `SUPABASE_SERVICE_ROLE_KEY`. This key bypasses
     RLS and must never reach the desktop app or any client-side code.
4. Project Settings -> API -> JWT Keys -> **Legacy JWT Secret** tab: copy the
   shared secret shown there (not the newer ECC/P-256 signing key on the
   "JWT Signing Keys" tab). Put it in `apps/backend/.env` as
   `SUPABASE_JWT_SECRET` — `app/core/auth.py` verifies session tokens with
   HS256 against this value.
5. Project Settings -> Auth: email/password sign-in is enabled by default,
   which is all REDLY needs for the beta. Leave email confirmations on.

## What's enforced

Every user-owned table (`agents`, `agent_knowledge`, `conversations`,
`messages`, `conversation_summaries`, `usage_events` read path, `usage_costs`
read path) has Row Level Security restricting access to
`auth.uid() = user_id`. The anon key alone grants nothing — a valid user JWT
(obtained via Supabase Auth on the desktop, e.g. sign-in) is required for any
row to become visible or writable.

`usage_costs` and the analytics read path are written only by the backend's
service-role key (billing/cost tracking must not be forgeable by a
compromised or malicious client).

## Local desktop app has no service role key, ever

The desktop app only ever holds:
- the Supabase **URL** and **Publishable key** (both safe to embed — the
  publishable key is a public identifier, not a secret; its safety comes
  entirely from RLS), and
- the **user's own JWT**, obtained after they sign in, stored in the OS
  credential store (not a plaintext file) — see `docs/cloud-migration.md`
  Stage 4.

The Secret key and Legacy JWT Secret live only in `apps/backend/.env`, on
the server. Never in the desktop app, never in a commit, never printed to a
terminal/log.
