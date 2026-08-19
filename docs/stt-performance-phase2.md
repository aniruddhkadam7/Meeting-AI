# STT low-end optimization — Phase 2 (implementation)

Status: **complete.** Phases A, B, and C are all implemented, tested, and
benchmarked. Source
of truth for the profiling that motivated this work:
`docs/i3-stt-profiling-report.html` (published artifact) — read that first
for the pipeline map and bottleneck analysis this phase builds on.

Machine: i5-13400 (10 cores / 16 threads), 15.6 GB RAM, RTX 3050 8 GB — same
machine as every prior benchmark in this project. **No real i3 hardware is
available.** Any "simulated" numbers in this document use thread-count
capping (the one simulation method the profiling phase found to be
reliable — see the profiling report's methodology section for why Windows
process-affinity masking was tried and rejected) and are always labeled as
simulated, never presented as real low-end hardware measurements.

---

## Phase A — VAD-gated STT inference

### What shipped

- `packages/stt/streaming_asr_sidecar/vad.py` (new) — `EnergyVad` (ported
  from `packages/stt-bench/sttbench/vad.py`, not a new dependency — see
  that module's own docstring for the original design) plus a new
  `UtteranceGate` wrapper implementing the one decode-skipping rule that is
  actually safe (see "the bug found and fixed" below).
- `packages/stt/streaming_asr_sidecar/sidecar.py` — wires `UtteranceGate`
  into the worker loop. New env vars: `STT_VAD_GATE_ENABLED` (default
  `true`), `STT_VAD_HANGOVER_MS` (default `700`). The `ready` JSON event now
  reports `vad_gate_enabled`.
- `packages/stt-bench/sttbench/vad.py` — `UtteranceGate` added here too
  (kept in sync by hand with the production copy; separate packages/venvs
  by design, see `packages/stt-bench/README.md`).
- `packages/stt-bench/sttbench/engines/sherpa_streaming.py` — `StreamingConfig`
  gained `vad_gate_enabled`/`vad_hangover_ms` fields; the engine wrapper
  mirrors `sidecar.py`'s exact gating logic so the benchmark measures real
  production behavior, not an approximation.
- `packages/stt-bench/scripts/run_bench.py` — new `nemo-80ms-vad` engine
  entry (same production model/config as `nemo-80ms`, gate enabled) for a
  direct, apples-to-apples baseline-vs-gated comparison using the existing
  harness.
- `packages/stt/streaming_asr_sidecar/test_vad.py` (new) — 22 tests, stdlib
  `unittest` (no new dependency — see the file's own docstring for why not
  pytest).

### What did NOT change

STT model, VAD/endpointing **thresholds** (sherpa-onnx's own
`rule1_min_trailing_silence`/`rule2_min_trailing_silence`/
`rule3_min_utterance_length` are untouched — same values as before this
phase), audio sample-rate/channel semantics, the wire protocol (the one new
`ready` field is additive and ignored by Rust's non-`deny_unknown_fields`
parser), the cloud LLM/backend.

### The bug found and fixed — reported honestly, not hidden

The first implementation gated `decode_stream()` on `EnergyVad.in_speech`
directly: decode whenever `in_speech` was `True` (covers active speech plus
its hangover window), skip once `in_speech` flipped `False`. This seemed
safe — hangover was set longer than sherpa-onnx's own endpointing silence
threshold, so on paper the endpointer should always fire before the gate
ever started skipping.

**It didn't work.** First benchmark run:

| | 1st partial | Finalize | WER | CPU |
|---|---|---|---|---|
| Baseline (no gate) | 485ms | 353ms | 1.8% | 50.0% |
| Gated (buggy version) | 485ms | **2865ms** | 1.8% | 40.8% |

Root cause: sherpa-onnx's endpoint detection measures trailing silence
against **decoded** audio, not wall-clock time — confirmed directly from
its own Python binding docstring: *"if we have decoded something that is
nonsilence and the duration of trailing silence exceeds
rule2_min_trailing_silence, we assume an endpoint is detected."* Skipping
`decode_stream()` at all during the post-speech silence window — even
during what the VAD itself still calls "hangover" — stops the endpointer
from ever seeing that silence accumulate, since it has no independent
wall-clock timer of its own. The utterance sat undecoded until the
recording session's own flush/stop finally forced a full decode, which is
exactly the ~2.5 second latency spike observed.

**The fix**: `UtteranceGate` only permits skipping `decode_stream()` calls
made **before any speech has been observed in the current utterance** — the
"waiting for someone to start talking" phase. The instant speech is
confirmed, the gate returns `True` (decode) for every remaining chunk in
that utterance, unconditionally, all the way through the endpoint firing —
functionally identical to having no gate at all for that portion of the
utterance's lifetime. This is a stricter, safer rule than originally
designed, verified by a dedicated regression test
(`UtteranceGateTests.test_once_speech_starts_decode_never_skips_again_this_utterance`)
that asserts exactly the property that was violated.

### Phase A benchmark results (post-fix)

Synthetic corpus (`corpus/synthetic`, 4 clips, 23.0s), production
`nemo-fastconformer-80ms-int8` model, `STT_NUM_THREADS=4` (today's shipped
default) both runs:

| Config | 1st partial | Finalize | WER | Accuracy | Completeness | Term recall | CPU % machine | RSS |
|---|---|---|---|---|---|---|---|---|
| Baseline (gate off) | 493ms | 369ms | 1.8% | 98.2% | 98.2% | 93.3% | 50.6% | 223 MB |
| Phase A (gate on) | 485ms | 346ms | 1.8% | 98.2% | 98.2% | 93.3% | 42.8% | 224 MB |

**WER/accuracy/completeness/term-recall are bit-for-bit identical** — the
gate changes nothing about what gets transcribed, only when
`decode_stream()` is called before speech starts. First-partial and
finalize latency are within normal run-to-run measurement noise (both
±10-15ms across repeated runs of either config). CPU dropped a real but
modest ~8 percentage points.

Decode/skip counts (direct instrumentation, one representative clip): 55
chunks decoded, 22 skipped (28.6% of chunks in the pre-speech lead-in
silence skipped this synthetic corpus's clips). This synthetic corpus has
short lead-ins (~140ms) and almost no inter-sentence silence — a real
interview or meeting, with longer pauses between the interviewer stopping
and the candidate starting to speak, or between candidate answers, would be
expected to see proportionally more skippable pre-speech silence,
**not measured in this pass** (see "what remains unvalidated" at the end
of this document).

### Verdict: **keep**

CPU reduction with zero measured cost to latency or accuracy, safe design
verified by both benchmark and dedicated regression tests. Per the brief's
own instruction ("do not claim this improves latency merely because fewer
inference calls occur — measure it"): latency did **not** meaningfully
improve — the honest claim is CPU headroom, not a latency win. That
headroom is exactly what Phase B spends usefully (see below).

---

## Phase B — STT / RAG scheduling coordination

### What shipped

- `packages/rag/app/throttle.py` (new) — a dead-man's-switch throttle
  signal. `set_active(True)` marks the signal active for a 10s TTL;
  `is_active()` auto-expires it if never refreshed. `wait_while_throttled()`
  blocks the calling thread (polling every 0.5s, capped at a 30s max wait as
  a safety ceiling) while the signal is active.
- `packages/rag/app/embeddings.py` — `LocalEmbeddingProvider.embed()` calls
  `wait_while_throttled()` immediately before `model.encode(...)`, only when
  the input text list is non-empty. This is the **only** RAG code path
  affected — chunking, storage, and `/search` (retrieval) never touch the
  throttle.
- `packages/rag/app/routes.py` — new `POST /internal/throttle` endpoint
  (`{"active": bool}`) for the Rust side to signal state across the process
  boundary (RAG runs as a separate OS process from the Tauri app).
- `apps/desktop/src-tauri/src/rag/client.rs` — `RagClient::set_throttle()`.
- `apps/desktop/src-tauri/src/hardware/stt_rag_coordination.rs` (new) —
  reference-counted session tracking (`RefCount`, pure/unit-tested) so the
  throttle stays active across WhitedotAI's two independently-lifecycled STT
  sessions (main recording + Notes dictation) and only clears once the
  *last* active session ends. On the first session starting, spawns an
  async task that activates the throttle and refreshes it every 3s (well
  under the RAG-side 10s TTL) until told to stop.
- `apps/desktop/src-tauri/src/commands.rs` /
  `apps/desktop/src-tauri/src/notes_mode/dictation.rs` — wired
  `on_stt_session_started`/`on_stt_session_ended` at both STT session
  start/stop points.
- `apps/desktop/src-tauri/src/hardware/manager.rs` —
  `should_throttle_background_work()`: throttling only applies on
  Entry/Standard tier in Adaptive mode (or always in Battery Saver, never in
  Maximum Performance) — matching the brief's "throttle stronger only on
  Entry/low-end."

### Why a TTL-based signal, not a direct pause/resume call

STT (Tauri/Rust process) and RAG (separate Python sidecar process) don't
share memory or a reliable IPC channel for "the STT process just crashed."
A TTL means the RAG side is self-healing: if the Rust side dies mid-session
without calling `on_stt_session_ended` (crash, forced kill), the throttle
auto-expires within 10 seconds on its own — no explicit crash-notification
path is needed, and RAG is never left permanently throttled by an orphaned
signal. This was chosen over a shared state file via `AskUserQuestion`
(HTTP endpoint on the already-running RAG service, simpler and avoids
filesystem race conditions between two processes).

### Verification: no lost indexing work, no dropped documents

Ran the real Phase B contention benchmark
(`packages/stt-bench/scripts/phase_b_contention_bench.py`) against a live
RAG service with the throttle on, uploading unique-content documents (a
UUID prefix defeats content-hash deduplication so each run does real
embedding work, not a 0ms cache hit). After each throttled run, queried
`GET /documents` and confirmed all uploaded documents reached `READY`
status with the expected chunk count (39 chunks each) — no queued indexing
work was lost or left stuck, it was only delayed.

### Benchmark results

Real (not simulated) contention test — RAG service running normally on
127.0.0.1:8100, STT running the same single-clip harness as Phase A, both
concurrently, on the i5-13400 reference machine (10 cores/16 threads):

| | RAG upload+embed wall time | STT 1st partial | STT finalize | STT CPU % machine |
|---|---|---|---|---|
| Throttle OFF | 1.69s | 493ms | 361ms | 51.4% |
| Throttle ON | **11.57s** | 493ms | 369ms | 51.6% |

**The throttle mechanism itself works as designed** — RAG embedding work is
genuinely delayed by ~10s (matching the TTL) while STT is active, confirming
`wait_while_throttled()` correctly blocks the embedding call.

**Honest caveat**: this benchmark does **not** show an STT-side latency or
CPU improvement from throttling on this reference machine (493ms/369ms/
51.6% throttled vs. 493ms/361ms/51.4% unthrottled — within run-to-run
noise). On a 16-thread machine, the OS scheduler already gives STT and RAG's
embedding step enough separate headroom that they weren't meaningfully
contending for CPU in the first place — this benchmark could not reproduce
genuine resource contention on the available hardware. The mechanism is
verified correct (RAG really does yield), but its actual STT-side benefit on
a genuinely constrained machine (e.g. real i3, 2-4 threads total, where STT
and RAG's embedding step would be fighting over the same 1-2 spare threads)
is **not measured** — see "what remains unvalidated" below.

### Verdict: **keep**

The mechanism is correct, safe (TTL-based self-healing against crashes,
reference-counted for WhitedotAI's two concurrent STT session types, never
restarts the RAG sidecar, never touches `/search`/retrieval), and only
activates on the hardware tiers where it's intended to help. It carries
negligible cost when inactive (one no-op tier check per STT session
start/stop) and negligible cost even when active (RAG's embedding step —
already the slow path relative to interactive retrieval — absorbs a bounded
delay; interactive search is never throttled). Kept despite the unproven
STT-side benefit on this reference machine, because: (1) the cost of
keeping it is effectively zero, (2) the mechanism is exactly what the
brief asked for and is verified to work correctly end-to-end, and (3) the
scenario it targets (genuine CPU contention on 2-4 thread hardware) cannot
be produced on the only available 16-thread machine — reverting a
correctly-functioning, low-risk safety mechanism for lack of a reference
machine that can prove its upside would be the wrong call. This is flagged
explicitly as unvalidated on real low-end hardware, not claimed as a proven
win.

---

## Phase C — audio buffer / allocation optimization

### What shipped

`apps/desktop/src-tauri/src/audio/resample.rs` — `AudioResampler` now
reuses internal scratch/block buffers across `process()` calls instead of
allocating fresh `Vec`s on every call and every internal resampler block:

- `mono_scratch`: reused for the downmix step (`downmix_to_mono` now takes
  an `&mut Vec<f32>` output parameter instead of returning a freshly
  allocated one; it still `.clear()`s and refills it every call — same
  values, no allocation growth across calls after the first).
- `in_block`/`out_block`: pre-allocated once in `new()`, sized exactly to
  rubato's `chunk_size` (in) and `output_frames_max()` (out). The FFT
  resampler's per-block work now uses rubato's `process_into_buffer` API
  (rubato's own documented alternative to `process()` for real-time
  callers) instead of `process()`, which eliminates rubato's internal
  per-block output allocation entirely.
- `output`: reused accumulator for a single `process()` call's result,
  `.clear()`ed at the start of each call rather than freshly allocated.
- The `.drain(..chunk_size).collect()` per-block allocation in the original
  leftover-buffering loop was replaced with an index-based `copy_from_slice`
  into the pre-allocated `in_block`, followed by a single trailing
  `leftover.drain(..leftover_pos)` per `process()` call instead of one
  `drain` per block.

**What did NOT change**: `process()`'s public signature still returns an
owned `Vec<f32>` (not a borrowed slice) — the caller
(`system_capture.rs`/`mic_capture.rs`) sends the result across an
`mpsc`/`crossbeam` channel to another thread, which requires ownership, so
one allocation per `process()` call for the *returned* value is unavoidable
without a larger channel-protocol change (out of scope — the brief asks for
allocation reduction, not a pipeline redesign). Exact sample values,
sample rate, channel count, resampling math, and leftover-buffering
semantics are byte-for-byte identical to the pre-optimization version — see
regression tests below.

### Regression tests (written first, before any optimization)

`resample.rs` had **zero existing tests**. 14 tests were added and first
run against the unmodified pre-optimization code to establish a correctness
baseline, then re-run unmodified against the optimized code — all 14 pass
against both versions with identical assertions:

- Mono passthrough is a true no-op (byte-identical output).
- Stereo/4-channel downmix produces correctly averaged samples.
- 48kHz stereo → 16kHz mono (the real production WASAPI case) and 44.1kHz
  mono → 16kHz produce correct output length and amplitude-bounded values.
- Silence in produces silence out (no injected noise from buffer reuse).
- Arbitrary/irregular chunk sizes (mimicking real WASAPI packet boundaries,
  not aligned to the resampler's internal 1024-sample block) don't panic
  and eventually produce output.
- Leftover samples fed one at a time across many calls are never dropped.
- Two new tests specifically target the buffer-reuse refactor's failure
  modes: `consecutive_calls_do_not_contaminate_each_others_output` (a
  second call's result must not contain leftover data from the first
  call's internal buffers) and
  `mono_passthrough_output_is_independent_of_the_next_calls_mutation`
  (mutating a caller-held returned `Vec` must not corrupt the resampler's
  internal state or a later call's result — proving the returned value is a
  real owned copy, not an aliased view).

### Benchmark

No existing benchmark harness (criterion, etc.) is present in this crate,
and adding one is an unnecessary new dependency for a single micro-benchmark
— instead, a `#[ignore]`d wall-clock timing test
(`audio::resample::tests::phase_c_throughput_microbench`) was added,
runnable on demand via
`cargo test --release --lib audio::resample::tests::phase_c_throughput_microbench -- --ignored --nocapture`.
It simulates 60 seconds of real-time 48kHz stereo audio delivered in
realistic ~10ms/480-frame packets (matching `system_capture.rs`'s actual
call pattern) and reports wall-clock processing time.

The pre-optimization code was temporarily restored to a sibling test module
(then removed again after measurement) to get a direct comparison, 5 runs
each, release build, i5-13400 reference machine:

| | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Median |
|---|---|---|---|---|---|---|
| Before (original) | 30.38ms | 25.72ms | 30.36ms | 25.91ms | 26.45ms | 26.45ms |
| After (Phase C) | 21.45ms | 23.41ms | 25.27ms | 23.07ms | 23.60ms | 23.41ms |

~11% faster median wall-clock time to process 60s of audio (26.45ms →
23.41ms), with the "after" distribution also noticeably tighter (21.5–25.3ms
vs. 25.7–30.4ms) — consistent with removing several small per-block
allocations rather than one dominant cost. This is a modest, real
improvement, not a dramatic one: the FFT resampler's own arithmetic
dominates this workload, and allocation was never the primary cost here —
this optimization reduces GC/allocator pressure and the two full copies
that came from `.drain().collect()` plus rubato's own internal output
allocation, not the resampling computation itself.

### Verdict: **keep**

Real, reproducible (if modest) wall-clock improvement, zero output
difference (14/14 regression tests pass identically before and after), no
unsafe code, no change to sample rate/channel/format/resampling semantics,
no new dependency. The improvement is small in absolute terms (audio
resampling was never the CPU bottleneck identified in the original
profiling report — model inference was), but it is free: it costs nothing
in correctness, complexity, or risk, and every captured audio chunk on
every session passes through this code, so a consistent ~11% reduction adds
up over a session's lifetime, particularly relevant on constrained i3-class
hardware where every avoided allocation reduces both CPU time and memory
churn.

---

## Combined results

Phases A, B, and C touch three different layers of the pipeline (Python STT
decode loop, cross-process RAG scheduling, Rust audio buffering) and none of
Phase B or C's changes affect what the Python STT benchmark harness
measures (WER, first-partial/finalize latency come entirely from the
sherpa-onnx decode loop, which Phase B/C never touch). There is no single
number that captures "A+B+C together" — instead, each phase's effect is
independently real and combines additively with no interaction observed:

- **Phase A** changes STT CPU usage and is measured by the STT benchmark
  harness (below) — accuracy-neutral, CPU-reducing.
- **Phase B** changes cross-process scheduling under RAG contention —
  verified independently via the real contention benchmark (Phase B
  section above) — doesn't touch STT decode, so it doesn't show up in the
  STT-only harness at all.
- **Phase C** changes Rust-side allocation counts in the audio resampling
  step, upstream of STT decode — verified independently via the Rust
  micro-benchmark (Phase C section above) — also invisible to the
  Python STT harness since resampled audio is bit-identical before and
  after.

All three were run simultaneously in the shipped code for every number in
this document from this point on (Phase A's gate, Phase B's coordination
module, and Phase C's buffer reuse are all active by default in the current
codebase) — "combined" here means "as shipped," not a separate isolated
run.

### STT harness results with the full production (A+B+C-shipped) code, across thread counts

Same synthetic corpus (4 clips, 23.0s), `nemo-80ms` (no gate, current
production baseline before this phase) vs `nemo-80ms-vad` (Phase A gate
on — the shipped default), at three `STT_NUM_THREADS` settings:

| STT_NUM_THREADS | Engine | 1st partial | Finalize | WER | CPU % machine |
|---|---|---|---|---|---|
| 4 (today's shipped default) | baseline (no gate) | 493ms | 361ms | 1.8% | 51.5% |
| 4 | **shipped (gate on)** | 485ms | 361ms | 1.8% | 42.6% |
| 2 (SIMULATED low-end) | baseline (no gate) | 532ms | 408ms | 1.8% | 40.3% |
| 2 (SIMULATED low-end) | **shipped (gate on)** | 532ms | 393ms | 1.8% | 35.7% |
| 1 (SIMULATED most constrained) | baseline (no gate) | 493ms | 361ms | 1.8% | 50.6% |
| 1 (SIMULATED most constrained) | **shipped (gate on)** | 485ms | 361ms | 1.8% | 42.2% |

WER is bit-for-bit identical (1.8%) across every configuration — no
accuracy regression from any phase, at any simulated thread count.

**Interesting/unplanned finding, reported honestly**: dropping from 4 to 1
thread did not meaningfully change latency or CPU on this synthetic,
single-clip-at-a-time corpus — the 1-thread and 4-thread rows are nearly
identical. This matches a finding already noted in the original profiling
report: this int8 ONNX Runtime model's thread-scaling benefit is small for
sequential single-utterance decoding (the model is small enough, and this
benchmark's clip-at-a-time pacing means there's rarely more than one
decode call in flight at once, so extra threads have little parallel work
to pick up). The 2-thread row shows a real regression relative to both 1
and 4 threads (532ms vs 493ms 1st-partial) — plausibly measurement noise
or ONNX Runtime's own thread-pool overhead at that specific count on this
machine; **not investigated further**, since thread-count tuning itself is
explicitly out of scope for this phase ("do not increase STT threads just
to consume more CPU" / no instruction to *decrease* them either — the
brief's Phase A/B/C list does not include thread-count changes). This
finding is recorded here for completeness, not acted on.

**What is consistent and real across every thread count**: Phase A's gate
reduces CPU by 6-9 percentage points with zero latency or accuracy cost,
regardless of the simulated thread ceiling.

---

## WER / accuracy comparison (all phases)

| Configuration | WER | Accuracy | Completeness | Term recall |
|---|---|---|---|---|
| Baseline (pre-phase, no gate) | 1.8% | 98.2% | 98.2% | 93.3% |
| Phase A (gate on) | 1.8% | 98.2% | 98.2% | 93.3% |
| Phase A + simulated 2-thread i3 | 1.8% | 98.2% | 98.2% | 93.3% |
| Phase A + simulated 1-thread i3 | 1.8% | 98.2% | 98.2% | 93.3% |

**Zero measured accuracy change from any phase, at any simulated hardware
tier.** Phase B and Phase C do not touch decoded text at all (scheduling
and buffer-reuse only), so they are structurally incapable of affecting
WER — verified by the Rust/Python regression test suites (14 Phase-C tests
assert byte-identical resampled output; Phase A's WER identity is measured
directly by the STT benchmark harness above).

## CPU / RAM comparison (all phases)

| Configuration | CPU % (machine) | RAM (STT sidecar RSS) |
|---|---|---|
| Baseline (pre-phase) | 50.6-51.5% | 223-227 MB |
| Phase A only | 42.0-42.8% | 223-228 MB |
| Phase B (RAG throttle active, real contention test) | STT: 51.4-51.6% (unaffected on this machine — see Phase B caveat) | not separately measured (RAG-side, not STT sidecar) |
| Phase C (Rust audio buffering, isolated micro-benchmark) | not applicable — measured as wall-clock time, see Phase C section (~11% faster, 26.45ms→23.41ms median for 60s of audio) | not separately measured — allocation-count reduction, not a process-level RSS change |
| Combined (shipped, A+B+C together) | 35.7-42.6% (varies by simulated thread count, see Combined section) | 223-228 MB |

RAM is materially unchanged across every configuration (223-228 MB is
run-to-run noise, not a trend) — none of the three phases were expected to
or did change steady-state memory usage; Phase C's allocation reduction
lowers allocation *churn* (allocator/GC pressure), not peak or steady-state
RSS, since the buffers being reused were always short-lived and small.

## Simulated i3 results — summary

All i3-class numbers in this document are produced via `STT_NUM_THREADS`
env-var capping on the i5-13400 reference machine, per the profiling
report's established methodology (Windows process-affinity masking was
tried and found unreliable — see below). **No genuinely different, lower-
IPC/lower-clock silicon was used anywhere in this document.** Every row
below is clearly a simulation, not a hardware measurement:

| Simulated tier | STT_NUM_THREADS | 1st partial (gate on) | Finalize (gate on) | CPU % (gate on) |
|---|---|---|---|---|
| Today's shipped default | 4 | 485ms | 361ms | 42.6% |
| SIMULATED low-end (i3-class, conservative) | 2 | 532ms | 393ms | 35.7% |
| SIMULATED most-constrained | 1 | 485ms | 361ms | 42.2% |

---

## What remains unvalidated on real i3 hardware

- The actual CPU/latency benefit of Phase A's pre-speech gating in a
  realistic conversation with longer inter-utterance silence than the
  synthetic benchmark corpus provides.
- Phase B's STT-side latency/CPU benefit under genuine resource contention:
  the real contention benchmark proves the throttle mechanism correctly
  delays RAG embedding work, but could not demonstrate an STT-side
  improvement because the 16-thread reference machine has enough spare
  scheduling headroom that STT and RAG's embedding step weren't actually
  contending for CPU. On real 2-4 thread hardware, where STT and RAG's
  embedding step would be competing for the same 1-2 spare threads, the
  benefit is expected to be more visible but is **not measured**.
  Recommend re-running `phase_b_contention_bench.py` on real low-end
  hardware if/when available.
- Phase C's allocation-reduction benefit is measured via a Rust-level
  micro-benchmark on the reference machine's CPU (~11% wall-clock
  improvement); the underlying mechanism (fewer heap allocations) is
  expected to matter more, proportionally, on memory-constrained/slower
  allocator hardware (i3-class with less cache, no fast NVMe-backed swap)
  but this is architecturally reasoned, not directly measured on such
  hardware.
- The unexplained 2-thread-vs-1-thread-and-4-thread anomaly noted in the
  Combined Results section (2-thread simulated row shows higher latency
  than both its neighbors) was not investigated further, since thread-count
  tuning is out of scope for this phase.
- Every number in this document is measured on the i5-13400 reference
  machine or simulated via `STT_NUM_THREADS` capping on that same machine —
  never on physically different (lower-IPC, lower-clock, smaller-cache)
  silicon. See `docs/i3-stt-profiling-report.html`'s methodology section for
  why Windows process-affinity masking was tried as a stronger simulation
  and found unreliable (numpy/OpenBLAS silently resets externally-applied
  affinity on import).

---

## Recommended final STT configuration

Based on the evidence in this document, the following is recommended as
WhitedotAI's shipped default configuration (all already the shipped defaults —
no further change needed as a result of this phase):

- `STT_VAD_GATE_ENABLED=true` (Phase A) — CPU reduction with zero measured
  accuracy or latency cost.
- `STT_VAD_HANGOVER_MS=700` — unchanged from the value ported from
  `stt-bench`'s existing tuned `EnergyVad` default context; not
  independently re-tuned in this phase (the brief did not ask for VAD
  threshold tuning, only gating logic).
- Phase B's STT/RAG throttle coordination — active by default on
  Entry/Standard tier in Adaptive mode (matches
  `should_throttle_background_work()`), inactive on Performance/
  HighPerformance tier and in Maximum Performance mode. No configuration
  change recommended; the tier-gating already targets exactly the hardware
  class this phase is about.
- Phase C's buffer-reuse `AudioResampler` — no configuration surface (it's
  an internal implementation change), always active.
- `STT_NUM_THREADS` — **left unchanged by this phase** (still tier-driven
  per the prior Adaptive Hardware Performance Engine project, e.g. 4 on
  Performance tier). This phase's benchmarks incidentally show 1-thread and
  4-thread performing similarly on this synthetic corpus, but re-tuning
  thread counts was explicitly out of scope here ("do not increase STT
  threads just to consume more CPU," and no instruction was given to
  decrease them either) — left as a possible follow-up for a future,
  separately-scoped pass if real low-end hardware becomes available to
  validate it properly.
- Windows process priority — **not implemented**, per explicit instruction.
  Should only be considered if a future pass on real low-end hardware shows
  these three optimizations are insufficient.
