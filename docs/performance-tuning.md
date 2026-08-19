# Adaptive performance tuning: architecture, benchmark evidence, and end-to-end latency

Status: **Complete — all 7 milestones done.** This is the final report for
REDLY's hardware-adaptive performance project. Hardware detection, the
performance manager, memory-pressure adaptation, and end-to-end pipeline
latency instrumentation are all implemented, tested, and verified live in
the running application.

Machine used for every measurement in this document: i5-13400 (10 cores /
16 threads), 15.6 GB RAM, RTX 3050 8 GB — the same machine documented in
`docs/stt-benchmark.md`. All STT/RAG measurements are CPU-only. **Every
ENTRY/STANDARD-tier number in this document is a simulated proxy** — every
sweep constrained this one available machine's thread/batch counts down; it
did not measure genuinely different (lower-core, lower-RAM) hardware. True
multi-machine validation is future work; treat low-tier numbers as "how
this CPU behaves when artificially restricted," not "how a different,
weaker CPU behaves." This caveat applies to every table in this document
and is not repeated at every occurrence.

Scope: STT and RAG (both genuinely local) plus the cloud LLM call's
*latency*, measured but never tuned or hardware-tiered — REDLY's LLM stays
a cloud API call (OpenAI/Anthropic via `apps/backend`) throughout. No local
LLM, no Ollama, no change to backend/LLM behavior anywhere in this project.

---

## 0. Architecture

```
Hardware (sysinfo + DXGI + storage seek-penalty query)
   |
hardware::detect() -> HardwareProfile
   |
hardware::tier::score() -> HardwareTier (Entry/Standard/Performance/HighPerformance)
   |
hardware::PerformanceManager (single source of truth, in AppState)
   - mode: Adaptive | MaximumPerformance | BatterySaver (persisted, user override)
   - pressure: PressureTracker (sustained-RAM-pressure overlay, Milestone 6)
   - effective_config() / effective_config_checked(available_ram_mb)
   |                                   |
STT sidecar spawn                RAG sidecar spawn + retrieval_planner
(explicit thread param)          (env vars at spawn + per-question config)
   |                                   |
hardware::telemetry (Milestone 7: Stopwatch/FirstTokenTracker/PerfContext,
logs stage timings + tier/mode/pressure correlation via the `log` crate)
```

Local vs. cloud boundary (unchanged by this project, confirmed by every
milestone's testing): STT (sherpa-onnx sidecar) and RAG (sentence-
transformers embeddings + sqlite-vec) run entirely on the user's machine.
The only network call in the ask-a-question pipeline is the cloud LLM
request (`BackendClient::ask_stream` and its Sales/Consulting/Agent
siblings) — REDLY's own FastAPI backend, which in turn calls OpenAI/
Anthropic. No audio, no raw transcript, and no document content is ever
sent anywhere except that one backend call, and it receives only the
already-retrieved text context, never raw documents.

---

## 1. STT: STT_NUM_THREADS sweep

Tool: `packages/stt-bench/scripts/run_thread_sweep.py`, new in this
milestone. Runs the production `nemo-fastconformer-80ms-int8` engine (byte-
identical to `models/stt/nemo-fastconformer-80ms-int8`, verified by file
size/timestamp before trusting this sweep) at each thread count, each in its
own subprocess for a clean CPU/RAM baseline. Corpus: the synthetic 4-sentence
set (`corpus/synthetic/`) — no human corpus was recorded for this pass;
WER numbers below are not meaningful for accuracy comparison (synthetic TTS
scores near-0% for most engines per `docs/stt-benchmark.md` §5) but *are*
useful as a stability check (WER should not change across thread counts if
decoding is deterministic, and it didn't).

Two independent runs, second run re-checking the three most decision-relevant
thread counts:

**Run 1** (threads 1, 2, 4, 6, 8):

| threads | load s | WER | 1st partial | finalize | partial interval | RAM MB | CPU% of machine | CPU% peak |
|---|---|---|---|---|---|---|---|---|
| 1 | 1.2 | 1.8% | 501ms | 401ms | 196ms | 225 | 1.8% | 5.7% |
| 2 | 1.2 | 1.8% | 493ms | 361ms | 203ms | 227 | 18.1% | 23.0% |
| 4 | 1.3 | 1.8% | 493ms | 369ms | 203ms | 226 | 51.4% | 63.7% |
| 6 | 1.2 | 1.8% | 493ms | 362ms | 196ms | 228 | 83.1% | 102.5% |
| 8 | 1.1 | 1.8% | 532ms | 393ms | 203ms | 231 | 92.4% | 108.9% |

**Run 2** (threads 1, 4, 6, re-check for noise):

| threads | load s | WER | 1st partial | finalize | RAM MB | CPU% of machine | CPU% peak |
|---|---|---|---|---|---|---|---|
| 1 | 1.1 | 1.8% | 501ms | 393ms | 223 | 1.5% | 4.8% |
| 4 | 1.2 | 1.8% | 486ms | 354ms | 223 | 51.3% | 63.5% |
| 6 | 1.2 | 1.8% | 492ms | 361ms | 227 | 81.3% | 104.6% |

### Finding

**Latency is flat from 1 to 6 threads** (486-501ms first-partial, 354-401ms
finalize — the spread is within normal run-to-run jitter, confirmed by
run 2 landing within a few ms of run 1 at every thread count checked) **and
measurably worse at 8 threads** (532ms/393ms in run 1 — the one clear
outlier in either direction across both runs). Meanwhile **CPU-of-machine
scales almost linearly with thread count**: 1.8% → 18.1% → 51.4% → 83.1% →
92.4%. WER is identical (1.8%) at every thread count, so accuracy is not a
confound.

This directly contradicts the original provisional table's assumption that
higher hardware tiers should get more STT threads for better latency — on
this model, more STT threads buys nothing but CPU cost above 1-2 threads,
and actively hurts at 8. `sidecar.py`'s existing `DEFAULT_NUM_THREADS=4`
comment already hinted at this ("more threads did not reduce latency, just
spun more CPU") but this sweep is the first time it was checked below 4 and
above 4 in the same controlled comparison.

### What this could not validate on this machine

Genuinely lower-core-count hardware (e.g. a real 4-core laptop) — this
sweep's "1 thread" result is a proxy (this CPU running with an artificial
cap), not a measurement of a physically smaller CPU, which may have
different cache/frequency characteristics that change the picture.
STT-under-concurrent-RAG-load contention — this sweep measured STT in total
isolation; a real recording session may run STT and RAG embedding at the
same time, where CPU contention between them could behave differently than
either in isolation.

---

## 2. RAG: embedding batch size × torch thread count sweep

Tool: `packages/rag-bench/bench.py`, new in this milestone. Imports
`packages/rag`'s real `LocalEmbeddingProvider`
(`sentence-transformers/all-MiniLM-L6-v2`, the production model) and
`VectorStore` (SQLite + sqlite-vec, the production vector store) directly,
in-process — no HTTP layer. 150 synthetic ~650-token-scale chunks (matching
the production chunk size default), 5 fixed queries. Each (batch, threads)
configuration ran in its own subprocess.

| batch | threads | load s | embed s | ms/chunk | index s | search p50 | search p99 | RAM MB (delta) | CPU% of process |
|---|---|---|---|---|---|---|---|---|---|
| 8 | 1 | 8.7 | 9.87 | 65.79 | 0.014 | 1.07ms | 1.20ms | 291 | 99.2% |
| 16 | 1 | 12.9 | 11.30 | 75.34 | 0.028 | 1.24ms | 1.29ms | 280 | 99.3% |
| 32 | 1 | 9.8 | 10.68 | 71.23 | 0.013 | 1.33ms | 1.40ms | 346 | 99.1% |
| 64 | 1 | 10.5 | 12.30 | 82.01 | 0.014 | 1.26ms | 1.68ms | 396 | 100.4% |
| 8 | 2 | 10.0 | 7.07 | 47.16 | 0.018 | 1.31ms | 1.52ms | 293 | 195.8% |
| 16 | 2 | 9.8 | 6.81 | 45.43 | 0.014 | 1.24ms | 1.38ms | 283 | 195.2% |
| 32 | 2 | 10.4 | 7.53 | 50.18 | 0.015 | 1.05ms | 1.32ms | 344 | 194.6% |
| 64 | 2 | 9.5 | 6.63 | 44.18 | 0.014 | 1.16ms | 1.47ms | 434 | 198.1% |
| 8 | 4 | 9.1 | 5.07 | 33.81 | 0.016 | 1.09ms | 1.37ms | 310 | 398.2% |
| 16 | 4 | 9.5 | 5.84 | 38.95 | 0.021 | 1.73ms | 2.43ms | 283 | 392.8% |
| 32 | 4 | 10.1 | 5.74 | 38.27 | 0.014 | 1.47ms | 1.61ms | 345 | 385.2% |
| 64 | 4 | 9.3 | 5.51 | 36.73 | 0.014 | 1.39ms | 1.86ms | 436 | 398.1% |
| 8 | 8 | 9.4 | 3.58 | 23.89 | 0.016 | 1.39ms | 1.73ms | 338 | 767.7% |
| 16 | 8 | 9.2 | 3.66 | 24.41 | 0.017 | 1.40ms | 1.54ms | 299 | 773.6% |
| 32 | 8 | 9.9 | 3.75 | 25.02 | 0.015 | 1.92ms | 2.02ms | 405 | 785.4% |
| 64 | 8 | 9.2 | 3.74 | 24.94 | 0.021 | 1.38ms | 1.54ms | 439 | 783.1% |

### Finding

**Embedding throughput scales close to linearly with torch thread count**
at any fixed batch size: ~66-82ms/chunk at 1 thread → ~44-50ms/chunk at
2 → ~34-39ms/chunk at 4 → ~24-25ms/chunk at 8. No plateau observed in this
range (unlike STT's thread scaling, which flattened immediately). CPU%-of-
process scales correspondingly (roughly `100% × threads`, confirming
`torch.set_num_threads()` genuinely controls the parallelism used).

**Batch size has essentially no effect on embedding speed** at a fixed
thread count — e.g. at 4 threads, ms/chunk is 33.8 / 39.0 / 38.3 / 36.7 for
batch 8/16/32/64 respectively, a spread that is noise, not a trend. Batch
size's real effect is on memory: RSS delta climbs from ~280-310MB at batch
8-16 to ~400-440MB at batch 64, fairly consistently across thread counts.

**Search latency (sqlite-vec exact KNN) is trivially fast regardless of
config** — 1.0-2.4ms p50/p99 across every configuration, at 150 chunks.
This is far too fast to be a useful discriminator between configs at this
corpus size; it does confirm exact brute-force KNN is not a bottleneck at
small-to-moderate scale, consistent with the existing finding in
`docs/architecture.md`/investigation notes that this is a "Phase 1, swap
later if needed" design.

### What this could not validate on this machine

RAG search latency at a realistic multi-thousand-chunk knowledge base — 150
chunks is small enough that sqlite-vec's exact KNN never became a
bottleneck; a real user's knowledge base could be large enough that this
picture changes and top_k/similarity_threshold tuning matters more than
this sweep suggests. RAG-under-concurrent-STT-load contention, same caveat
as the STT section. Genuinely lower-core hardware, same caveat as the STT
section — "1 thread" here is this CPU capped, not a smaller CPU measured.

---

## 3. Corrected tier table (production defaults)

The pre-benchmark provisional table assumed "higher tier → more STT threads
→ faster STT" and "higher tier → bigger RAG batch → faster embedding."
Neither held up. The corrected table below is what actually ships — live in
`apps/desktop/src-tauri/src/hardware/manager.rs::config_for_tier`, wired
into `SttSidecar::spawn` and the RAG sidecar's env vars since Milestones
4b/5, and verified live: on this HighPerformance-tier machine, the RAG
service's own log line read `torch_threads=8 batch_size=32` on model load,
exactly matching the table.

| Parameter | ENTRY | STANDARD | PERFORMANCE (today's shipped default) | HIGH_PERFORMANCE |
|---|---|---|---|---|
| `STT_NUM_THREADS` | 1 | 2 | 4 | 4 (was 6 — no benchmarked benefit above 4, and 6 was statistically indistinguishable from 4) |
| RAG `top_k` | 2 | 3 | 4 | 5 (unchanged — not part of this sweep, see §4) |
| RAG `max_context_chars` | 2000 | 3000 | 3500 | 4000 (unchanged — not part of this sweep, see §4) |
| RAG retrieval timeout | 800ms | 1200ms | 1500ms | 2000ms (unchanged — not part of this sweep) |
| `RAG_EMBED_BATCH_SIZE` | 8 | 16 | 32 | 32 (was 64 — no measured latency benefit, only +~90MB RSS for nothing) |
| `RAG_TORCH_THREADS` | 1 | 2 | 4 | min(logical_cores/2, 8) — confirmed as the one lever worth scaling with tier |
| RAG `similarity_threshold` | 0.35 | 0.3 | 0.3 | 0.25 (unchanged — not part of this sweep) |

Why `STT_NUM_THREADS` stays at 4 for PERFORMANCE rather than dropping to
1-2 (which the data would technically justify): that value matches today's
actual shipped production default
(`packages/stt/streaming_asr_sidecar/sidecar.py`'s `DEFAULT_NUM_THREADS`).
Changing the shipped default itself is a separate decision from correcting
this tier table, and is flagged as an open question below rather than made
unilaterally by this benchmark pass.

---

## 4. Not covered by this sweep

RAG `top_k`, `max_context_chars`, `similarity_threshold`, and retrieval
timeout were not swept in Milestone 4a — that requires end-to-end
measurement (does a bigger retrieval budget actually produce a better
answer, weighed against the added local retrieval time *and* the added
prompt size sent to the cloud LLM). Milestone 7 (§6) built the
instrumentation capable of measuring this (`rag_retrieval`/`llm_total`/
`question_to_answer` stage timings), but did not itself run a sweep across
different `top_k`/`max_context_chars` values with that instrumentation —
that would be a further optimization pass, which is explicitly out of scope
for this project (see §7/§8's "keep scope tight" close-out). Their values
in the table above are carried over unchanged from the original provisional
table and are not backed by measurement.

GPU acceleration for either STT or RAG was not attempted — out of scope
per the project plan (STT's installed wheel is CPU-only, GPU was already
tested and rejected in `docs/stt-benchmark.md`; RAG's torch build is
CPU-only). Not revisited by this sweep.

---

## 5. Runtime memory-pressure adaptation (Milestone 6)

Implementation: `apps/desktop/src-tauri/src/hardware/pressure.rs`
(`PressureTracker`), consulted via
`PerformanceManager::effective_config_checked` at six checkpoints: STT
session start (system audio capture + Notes mic dictation) and RAG
retrieval planning (Interview/Sales/Consulting/Agent-ask live modes plus
the offline interview-analysis path). Not a continuous background poll —
no timer thread, no periodic wakeups; a checkpoint only fires when the app
is about to do the corresponding work.

**Rule:** sustained pressure, not a single low reading. Two consecutive
checkpoint samples below 1024MB available RAM (anchored to STT's own
measured 228MB footprint, see `docs/stt-benchmark.md`) are required before
entering a reduced-workload state. Recovery requires available RAM to stay
continuously above a 256MB margin (1280MB) for a 90-second cooldown — any
dip back down resets the cooldown clock, so hovering near the threshold
cannot cause repeated flips.

**Scope of what pressure adaptation touches:** only `stt_num_threads` and
RAG's per-question retrieval parameters (`top_k`, `max_context_chars`,
`similarity_threshold`, `retrieval_timeout_ms`) are clamped down to
ENTRY-tier values under pressure — both apply without restarting anything
(STT threads take effect on the next sidecar spawn; retrieval params are
read fresh per question). `rag_embed_batch_size`/`rag_torch_threads` are
**never** touched by pressure adaptation, since changing them requires
restarting the RAG sidecar process, and this module never triggers a
restart automatically — only an explicit user mode change
(`set_performance_mode`) restarts RAG, exactly as before this milestone.
STT model choice, VAD, endpointing, and the cloud LLM/backend are
completely outside this module's reach.

**Every state transition is logged** with the actual reading and threshold
that triggered it (e.g. `"entering reduced-workload mode: available RAM
412MB stayed below 1024MB for 2 consecutive checks"`), via the existing
`log::warn!` sink — no new persistence, no telemetry queue.

**Test coverage:** 14 tests in `hardware::pressure::tests` (entry
threshold, hysteresis on both edges, cooldown timing, cooldown reset on a
dip, re-triggering after recovery, the RAG-embed-config-untouched
guarantee) plus 3 integration tests in `hardware::manager::tests`
confirming the manager wiring. All still pass unmodified after Milestone 7
(pressure.rs and the pressure-related parts of manager.rs were not touched
by this final milestone — see §6).

---

## 6. End-to-end pipeline latency instrumentation (Milestone 7)

Implementation: `apps/desktop/src-tauri/src/hardware/telemetry.rs` — a
`Stopwatch` (monotonic `Instant`-based timer), a `FirstTokenTracker` (for
time-to-first-token inside a streaming callback the caller doesn't get back
control of), and a `PerfContext` (tier/mode/pressure-state/config
snapshot). Wired into the four live "ask a question" call sites
(`interview_mode`, `sales_mode`, `consulting_mode`, `agents::ask`) and the
STT session-start/first-partial/first-final path (`commands.rs`'s
`start_system_audio_capture`, `notes_mode/dictation.rs`).

### Stages measured

| Stage | What it measures | Where |
|---|---|---|
| `stt_session_start` | Audio capture start -> STT sidecar process spawned | `commands.rs`, `notes_mode/dictation.rs` |
| `stt_first_partial` | Forwarder-thread start -> first partial transcript of the session | `commands.rs` (system audio only — see note below) |
| `stt_final` | Forwarder-thread start -> first finalized transcript segment of the session | `commands.rs` |
| `rag_retrieval` | One `RetrievalPlanner::plan_for_question` call (HTTP round trip + local filter/dedup) | all four ask-question call sites |
| `llm_first_token` | LLM request dispatched -> first streamed delta received | all four ask-question call sites |
| `llm_total` | LLM request dispatched -> stream complete | all four ask-question call sites |
| `question_to_answer` | User's question submitted -> final answer complete (the number the user actually experiences) | all four ask-question call sites |

**Note on `stt_first_partial`/`stt_final`:** these log only the *first*
occurrence of each event kind per recording session, not every utterance.
This was a deliberate choice to satisfy "no excessive logging" — logging
every partial/final in a long interview would be far noisier than the
brief's own "lightweight" requirement allows. Per-utterance latency (speech
end -> finalized text) is already well-characterized in
`docs/stt-benchmark.md`'s corpus-based benchmark; this milestone's addition
is the *session-level* number (how long from starting a recording until
the user first sees text), which that benchmark does not measure. Mic
dictation (`notes_mode/dictation.rs`) only logs `stt_session_start` — it is
a transcription-to-buffer flow with no RAG/LLM involved, outside this
milestone's "question -> answer" pipeline scope.

### Log format

One `log::info!` line per stage boundary, e.g.:

```
perf: stage=llm_first_token ms=612 tier=HighPerformance mode=Adaptive pressure=Normal stt_threads=4 rag_top_k=5 rag_ctx_chars=4000
```

Fields: `stage` (fixed enum label), `ms` (elapsed milliseconds), `tier`
(detected `HardwareTier`), `mode` (`PerformanceMode`), `pressure`
(`PressureState`), `stt_threads`/`rag_top_k`/`rag_ctx_chars` (the config
actually in effect for that call). Nothing else — no question text, no
answer text, no retrieved chunk text, no filenames, no API keys/JWTs, no
request/response bodies. This is enforced at the type level: `log_stage`/
`log_stage_ms`'s signatures only accept `PipelineStage` (a closed enum),
`Duration`/`u128`, and `PerfContext` (enums + small numbers) — there is no
`&str`/`String` parameter a future edit could accidentally wire free text
into. Every call site was manually audited (see the `telemetry` module doc
comment and this document's own review) to confirm no `question`,
`answer`, `delta`, `request`, or retrieved-chunk value is ever passed to a
telemetry call.

### Verified live in the running application

```
perf: stage=stt_session_start ms=85    tier=HighPerformance mode=Adaptive pressure=Normal stt_threads=4 rag_top_k=5 rag_ctx_chars=4000
perf: stage=stt_first_partial ms=2014  tier=HighPerformance mode=Adaptive pressure=Normal stt_threads=4 rag_top_k=5 rag_ctx_chars=4000
perf: stage=stt_final ms=2818          tier=HighPerformance mode=Adaptive pressure=Normal stt_threads=4 rag_top_k=5 rag_ctx_chars=4000
```

Captured from a real `npm run tauri dev` run on the HighPerformance-tier
benchmark machine: system audio capture started, the STT sidecar spawned
and reported ready in 85ms, the first partial transcript appeared 2.0s
after the forwarder thread started (audio-dependent — this run's test
audio had a few seconds of lead-in before speech), and the first
finalized segment landed at 2.8s. The backend's `/api/v1/ask/stream`
endpoint was separately confirmed live and streaming correctly (`curl`
against the running backend produced real `event: delta` SSE frames) —
the `llm_first_token`/`llm_total`/`rag_retrieval`/`question_to_answer`
stages could not be captured from a live UI interaction in this
environment (no way to drive the Tauri webview's UI directly here), but
the wrapping code is a pure non-invasive timer around the unmodified
`ask_stream`/`RetrievalPlanner::plan_for_question` calls, and is covered
by the composed-flow unit test in §6 below standing in for that exact
sequence.

### Testing

18 new tests in `hardware::telemetry::tests`: `Stopwatch` timing accuracy,
`FirstTokenTracker`'s mark-once/ignore-later-marks/shared-cell-via-clone
behavior (mirroring exactly how the four call sites use it), a composed
"question -> retrieval -> LLM -> answer" flow test that simulates
`ask_stream`'s ownership shape (the closure is moved in and never handed
back) with a fake streaming function — **no real network/cloud API call**,
so this cannot be flaky on real LLM latency — and a content-safety
regression guard documenting that the logging API's signatures cannot
accept free-text parameters.

### What could NOT be measured in this pass

- **Real cloud LLM latency numbers.** The instrumentation is verified
  correct and live (STT stages captured from the real app; the backend's
  streaming endpoint independently confirmed working), but no real
  question was driven through the Tauri UI to capture actual
  `llm_first_token`/`llm_total`/`question_to_answer` numbers, since this
  environment has no way to interact with the desktop app's webview UI
  directly (only launch it and inspect its logs/backing services). The
  code path is a thin, unmodified wrapper around the existing
  `ask_stream` calls, so there is no reason to expect it behaves
  differently in a real interaction than in the composed-flow test, but
  "verified live end-to-end including real cloud LLM numbers" is not the
  same claim as "verified the instrumentation code is correct and the STT
  half is live" — the latter is what was actually established here.
- **Concurrent STT+RAG+LLM load.** Every measurement in this project
  (Milestones 4a and 7) measured each stage's own latency; none measured
  what happens when STT decoding, RAG embedding, and a streaming LLM
  response are all active on the machine simultaneously, which is the
  realistic steady state during a live interview with retrieval enabled.
- **Multi-machine validation**, same caveat as every other section of this
  document.

---

## 7. Recommended production defaults

- **Adaptive mode as the default** (already the case) — it auto-selects
  the tier row in §3 based on detected hardware, with no user action
  required.
- **Keep `STT_NUM_THREADS=4` as the shipped default** for now (§3's
  PERFORMANCE row) — do not act on the open question in §8 without a
  separate, focused decision, since it affects every user today regardless
  of the new tier system.
- **Do not pursue GPU acceleration for STT or RAG in the near term** — no
  working CUDA wheel is installed for either, and wiring one is a
  separately-scoped dependency change with its own validation burden (see
  §4).
- **Do not swap sqlite-vec for an ANN index** based on this project's
  findings — search latency was trivial (1-2ms) at the corpus size tested;
  revisit only if real user knowledge bases are shown to be large enough
  to matter (see the open question in §8).
- **Leave RAG `top_k`/`max_context_chars`/`similarity_threshold`/timeout
  values as currently tabulated in §3** — they were never benchmarked
  end-to-end in this project (see §4); changing them further should wait
  for real question->answer latency numbers under load, not be guessed at
  again.

---

## 8. Open questions for the user

1. **Should the shipped STT default itself change** (currently 4 threads,
   set in `sidecar.py`'s `DEFAULT_NUM_THREADS` and used whenever
   `STT_NUM_THREADS` is unset)? This sweep shows 1 thread performs
   identically to 4 on this hardware while using ~28x less CPU (1.8% vs
   51.4% of machine). That is a real, evidence-backed opportunity, but
   changing it affects every user today, not just the new adaptive tiers,
   and is a separate decision from this benchmarking pass. Recommend
   treating this as a candidate for a focused follow-up, not bundled into
   Milestone 4b/5's tier-wiring work.
2. **Is 150 synthetic chunks a large enough RAG test corpus** to trust the
   "batch size doesn't matter, search is always fast" finding for real
   users with larger knowledge bases? A larger sweep (1000+ chunks) would
   be needed to know whether these findings hold at scale, and is not done
   here.
3. **Real cloud-LLM end-to-end numbers are still unmeasured** (§6) — the
   instrumentation is live and verified for STT; a follow-up should drive
   an actual question through the running app's UI (something this
   environment could not do) and capture the resulting
   `question_to_answer`/`llm_first_token` log lines to get real numbers,
   rather than relying on the composed-flow unit test as a stand-in.

---

## Project status: complete

All 7 milestones are implemented, tested, and (where an interactive UI
would have been required) verified as far as this environment allows.
Summary of what changed across the whole project, for reference:

- **Milestones 1-3**: hardware detection (`hardware::profile`/`gpu`/
  `storage`), tier scoring (`hardware::tier`), the `PerformanceManager`
  single source of truth, persistence, Tauri commands, and the Performance
  panel UI.
- **Milestone 4a**: STT thread-count and RAG batch/thread benchmarks,
  correcting the tier table from an untested "more resources = better"
  assumption to evidence-backed values.
- **Milestones 4b/5**: wired the corrected tier table into
  `SttSidecar::spawn` and the RAG sidecar's env vars; regression tests
  proving each tier produces its documented config.
- **Milestone 6**: sustained-memory-pressure adaptation with hysteresis/
  cooldown, scoped to never require a RAG restart.
- **Milestone 7** (this pass): end-to-end latency instrumentation across
  STT -> RAG retrieval -> cloud LLM -> final answer, with performance-tier/
  mode/pressure correlation, verified to log no sensitive content, and this
  final documentation.

Per the project's own scope boundary: no local LLM/Ollama was introduced at
any point, the cloud LLM remains the sole inference layer, and no further
optimization work is planned as part of this project — remaining
opportunities are captured as open questions above for a future, separately
-scoped decision, not started here.
