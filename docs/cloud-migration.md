# WhitedotAI Hybrid Cloud Migration

Tracks the move from a fully local, single-user desktop app to the hybrid
architecture: Tauri desktop (local STT/audio/RAG, unchanged) + WhitedotAI Cloud
(Supabase Auth/Postgres + FastAPI, for accounts, agent sync, and analytics).

## Before this migration

Everything ran locally with no cloud component:
- WASAPI capture -> NeMo STT sidecar -> transcript — 100% local, unchanged by
  this migration.
- `packages/rag` — a local FastAPI process (127.0.0.1:8100) for document
  upload/embedding/search. Unchanged — stays local per the product
  direction (no continuous audio/STT/RAG in the cloud).
- `apps/backend` — a FastAPI process the desktop talked to at
  `127.0.0.1:8000` (or wherever `BACKEND_URL` pointed), run manually in dev,
  with no auth, no database, no per-user concept. It called OpenAI directly
  using a shared local `.env` key.
- Custom Agents, conversation history, Sales/Consulting/Notes mode state —
  all local JSON files under `%APPDATA%\...\`, no sync, no accounts.
- No updater — users would need to reinstall manually for every release.

## What changed

`apps/backend` is now **WhitedotAI Cloud**: the same FastAPI app, unchanged in
its existing routes/behavior, with three additions:

1. **Auth** (`app/core/auth.py`) — verifies Supabase-issued JWTs. Every
   cloud-only route (`/agents/sync/*`, `/analytics/events`) requires one;
   every existing route (`/interviews/analyze`, `/ask`, `/agents/ask`, ...)
   is untouched and still works with no auth, exactly as before, for
   backward compatibility with any build not yet pointed at a real
   Supabase project.
2. **Agent sync** (`app/api/routes/agent_sync.py`) — push/pull endpoints so
   the desktop's local `agents.json` can mirror to `public.agents` in
   Supabase Postgres.
3. **Analytics** (`app/api/routes/analytics.py`) — a write-only event
   ingestion endpoint backed by `public.usage_events`.

The desktop app gained:
- `src-tauri/src/auth/` — signs in directly against Supabase Auth (GoTrue),
  stores the session in Windows Credential Manager via the `keyring` crate.
  WhitedotAI Cloud's FastAPI never sees a password.
- `src-tauri/src/cloud_sync/` — pushes/pulls agents, merged into the local
  `AgentStore` last-write-wins by `updated_at_ms`. Local storage remains the
  source of truth for offline use; sync is best-effort and additive.
- `src-tauri/src/analytics/` — an in-memory event queue flushed to WhitedotAI
  Cloud every 60s when signed in. No-ops (queues, doesn't fail) when signed
  out or offline.
- `src-tauri/src/updater.rs` + `tauri-plugin-updater` — checks a configured
  update endpoint on launch; installing is always an explicit user action.
- `src/Account.tsx`, `src/UpdateBanner.tsx` — the only new UI surfaces. Both
  are optional/dismissible; nothing else in the app changed behavior.

## What did not change

- STT, WASAPI capture, the gap filler, Interview Mode's live overlay,
  screen-capture exclusion — untouched.
- The local RAG service (`packages/rag`) — still local-only, still no
  outbound HTTP client of its own, still never receives calls from
  anywhere but the desktop app on 127.0.0.1.
- Every existing FastAPI route's request/response shape and behavior.
- Local-first agent storage — `agents.json` still works fully offline with
  no account; sync is additive, not a replacement.

## Setup (first time)

1. **Supabase**: follow `supabase/README.md` — create a project, run
   `supabase/migrations/0001_init.sql`, copy the URL/anon key/JWT
   secret/service-role key.
2. **Backend env**: copy `apps/backend/.env.example` -> `.env`, fill in the
   `SUPABASE_*` block. Without it, the server still runs — auth-gated routes
   return a clear 401/503 instead of crashing, and every pre-existing route
   keeps working unauthenticated.
3. **Desktop env**: set `SUPABASE_URL` / `SUPABASE_ANON_KEY` (same non-secret
   values the backend has) as environment variables before `npm run tauri
   dev` / in the production build's env. Without them, `Account` shows "not
   configured" and the rest of the app is unaffected.
4. **Updater signing key**: a keypair was generated for this migration
   (public key embedded in `tauri.conf.json`). The private key is NOT
   committed to the repo — store it in a password manager or CI secret store
   as `TAURI_SIGNING_PRIVATE_KEY` (+ `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` if
   you set one) before running a release build, or `npm run tauri build`
   will produce unsigned (non-updatable) artifacts.
5. **Update endpoint**: `tauri.conf.json`'s `plugins.updater.endpoints`
   currently points at `https://releases.whitedotai.app/updates/...` as a
   placeholder — replace with wherever release JSON manifests + installers
   actually get hosted (a static file host / S3 bucket / GitHub Releases all
   work with Tauri's updater; pick one and update this URL before shipping
   real updates).

## Deploying the backend (10-50 user beta)

`apps/backend/Dockerfile` + `fly.toml` are ready for a single small
container on Fly.io (or swap `fly.toml` for the equivalent Render/Railway
config — the Dockerfile itself is host-agnostic). See the comments in
`fly.toml` for the exact `fly launch`/`fly secrets set`/`fly deploy` steps.
This is intentionally the cheapest viable option: one container, no
autoscaling, Supabase's free tier for the database.

## What's still local-only / not synced

- Transcripts, recordings, interview sessions — never leave the device.
- Document knowledge-base content (the actual files/chunks/embeddings in
  `packages/rag`) — only lightweight metadata (`agent_knowledge` table:
  filename, type, status, chunk count) has a cloud table prepared, and
  nothing currently writes to it; wiring that up is a follow-on, not part of
  this migration.
- Sales/Consulting/Notes mode history — still local JSON only; the schema's
  `conversations`/`messages` tables are ready for this but no sync code was
  written for them yet (Custom Agents was the one explicitly scoped for
  Stage 6/7 in this pass).

## Explicit non-goals (per product direction)

No payments, no subscription enforcement, no public marketing website, no
team/organization management UI (the `organizations`/`subscriptions` tables
exist as schema foundation only, with no application logic on top).
