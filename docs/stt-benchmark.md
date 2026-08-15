# STT engine benchmark

Status: **implemented and verified in production.** The recommendation below was
approved and applied — see `docs/stt-migration.md` for what shipped and the
measurements taken against the live pipeline. This document is retained as the
evidence trail for *why* NeMo FastConformer 80 ms was chosen over the
alternatives.

Machine: i5-13400 (10 cores / 16 threads), 15.6 GB RAM, RTX 3050 8 GB.
All measurements CPU-only — a shipping desktop app cannot assume an NVIDIA card.

---

## 1. The headline finding is not about the engine

Before any recognizer question: **the audio pipeline is handing STT a broken
timeline, and that alone produces most of the symptoms you described.**

WASAPI loopback capture on an *idle* render endpoint delivers **no packets at
all**. Not silent packets — nothing. From `cargo run --bin audio_probe`, audio
delivered per second of wall time, with speech between t=5s and t=11s:

```
t= 1s  0.812s  ████████████████████████████████
t= 2s  0.000s                     ← nothing playing, no packets
t= 3s  0.000s
t= 4s  0.000s
t= 5s  0.257s  ██████████         ← playback starts
t= 6s  1.005s  ████████████████████████████████████████
t= 9s  0.994s  ████████████████████████████████████████
t=11s  0.406s  ████████████████   ← playback ends
t=12s  0.000s                     ← silence never reaches STT
t=13s  0.000s
```

Why this matters: **every** speech endpointer — PocketSphinx's `Endpointer`,
sherpa-onnx's `is_endpoint`, any VAD — decides an utterance is over by observing
*trailing silence*. If silence is never delivered, that trigger never fires. The
utterance stays open until the interviewer happens to speak again, at which point
two questions get glued together.

That single fact explains, without involving the recognizer at all:

- finals arriving seconds late, or not at all
- the last words of a sentence going missing
- separate questions merging into one segment

Swapping PocketSphinx for a better model **without fixing this** would leave a
large part of the problem in place.

The rest of the pipeline measured clean, so this is the only audio-side defect:

| Measurement | Result | Verdict |
|---|---|---|
| Device mix format | 48 kHz, 2 ch → 16 kHz mono | correct |
| Chunk size to STT | 342 samples (21.4 ms) p50 | good granularity, not too small |
| Chunk arrival gap | 20.1 ms p50 / 30.7 ms p99 | steady |
| Queue depth | 0 / 0 / 0 (p50/p99/max) | consumer keeps up, no backlog |
| Downmix + resample | 2.4% of one core | negligible |
| Resampler throughput | 99.9% of received samples | not dropping anything |
| WASAPI discontinuities | 1 at stream start (normal), 5 across playback transitions | minor |
| Delivered ÷ elapsed, endpoint active | 0.9989 | complete |
| Delivered ÷ elapsed, endpoint idle | **0.46 – 0.64** | **timeline holes** |

**Fix**: reconstruct the missing time. `audio::SilenceGapFiller` (added, not yet
wired into production) tracks how much audio *should* exist by wall clock versus
how much arrived, and emits real silence to close the gap. Verified in the live
spike: 9.7 s captured + 16.4 s synthesized = 26.1 s over a 26.0 s run, and the
first FINAL fired correctly — it does not fire without this.

---

## 2. Engine results

Ten configurations, identical audio, fed at **1x real time** in 100 ms chunks.
Each engine runs in its own process so peak RSS is measured against a clean
interpreter.

| Engine | Strategy | WER | 1st partial | Finalize | Partial int. | Size | RAM | CPU |
|---|---|---|---|---|---|---|---|---|
| whisper.cpp base.en | rolling | 0.0% | 391 ms | 579 ms | 379 ms | 148 MB | 283 MB | 14.9% |
| whisper.cpp small.en | rolling | 0.0% | 751 ms | 1601 ms | 773 ms | 488 MB | 751 MB | 20.4% |
| **Moonshine base EN** | rolling | 0.0% | **220 ms** | **406 ms** | 395 ms | 141 MB | 253 MB | 27.8% |
| Parakeet unified 0.6B offline | rolling | 0.0% | 657 ms | 865 ms | 433 ms | 663 MB | 884 MB | 48.1% |
| Zipformer EN Kroko 2025 | streaming | 0.0% | 1344 ms | 1582 ms | 1285 ms | 71 MB | 186 MB | 20.4% |
| **NeMo FastConformer 80 ms** | streaming | 1.8% | 509 ms | **384 ms** | **203 ms** | 138 MB | 228 MB | 45.5% |
| NeMo FastConformer 480 ms | streaming | 7.1% | 1102 ms | 1103 ms | 594 ms | 138 MB | 232 MB | 43.6% |
| PocketSphinx *(current)* | HMM | 10.7% | 531 ms | 379 ms | — | 7 MB | 108 MB | 0.5% |
| Parakeet unified streaming 560 ms | streaming | 14.3% | 2157 ms | 9172 ms | 453 ms | 663 MB | 838 MB | 59.0% |
| Parakeet unified streaming 240 ms | streaming | 16.1% | 3783 ms | 23516 ms | 863 ms | 663 MB | 834 MB | 59.3% |

CPU is percent of the whole 16-thread machine. Full per-sentence transcripts and
raw numbers: `packages/stt-bench/results/benchmark_synthetic.json`.

### Read the WER column with suspicion

**These accuracy numbers come from synthetic Windows TTS, not from human speech,
and they do not discriminate.** Six engines tie at exactly 0.0%, and PocketSphinx
scores 10.7% — far better than it behaves in real use. Clean synthetic speech has
none of the coarticulation, breath, or room tone that breaks recognizers.

The latency, CPU, RAM and streaming-behaviour columns are sound regardless of
corpus — those are properties of the engine and its decode loop. **The accuracy
ranking is not yet established.** See §5.

---

## 3. What the latency numbers actually show

**Parakeet 0.6B streaming cannot run in real time on this CPU.** Its 23.5-second
finalization is not endpointing lag — it is the decoder falling progressively
behind. A 7.4 s clip took 49.5 s of wall time to process, a real-time factor of
~6.6x. It is accurate, and unusable live without a GPU. Worth knowing: NVIDIA
*does* ship a genuine stateful streaming RNNT export (240 ms / 560 ms / 1120 ms
chunk variants), so the answer to "can Parakeet do incremental recognition" is
yes, natively, with no rolling-window workaround — it just costs more compute
than this class of machine has.

**Zipformer Kroko is real-time and accurate but updates too slowly.** Partials
every 1285 ms, because 1.28 s is the model's baked-in decode chunk. Not tunable
at runtime. Above your 200–500 ms target.

**Rolling-window partials are visibly unstable.** Each re-decode is independent,
so earlier words change after the fact. Observed on Moonshine:

```
"...observed Phoebe, turning a witch."      →
"...observed Phoebe, turning away her eye." →
"...observed Phoebe, turning away her eyes."
```

whisper showed the same ("very light" → "very like the old pole" → "old port"),
plus `[BLANK_AUDIO]` annotation artifacts that had to be stripped. In an overlay
this reads as flickering text. The streaming transducers do not do this — their
partials only ever extend.

**Nothing blocks the audio path.** `feed_audio()` max was 0.00 ms for the rolling
engines and 15–16 ms for the sherpa engines (one-time worker warm-up). The 172 ms
figure for PocketSphinx is an artifact of my harness decoding inline; production
already isolates it in a sidecar process.

---

## 4. Recommendation

**Adopt NeMo streaming FastConformer EN 80 ms (int8) via sherpa-onnx.**

It is the only candidate that comes close to every behavioural target at once
(first-partial lands 9 ms over the 500 ms line — effectively on target, but I am
not going to call it a pass):

| Target | Required | Measured |
|---|---|---|
| First visible text | < 500 ms | 509 ms — marginally over |
| Partial updates | 200–500 ms | 203 ms |
| Finalization | 300–800 ms | 384 ms |
| Real-time on CPU | yes | yes, with headroom |
| Offline after install | yes | yes |
| Model size | lightweight | 138 MB |

Partials extend monotonically rather than being rewritten, so the overlay will
not flicker. It is a native streaming transducer, so interim results are what the
decoder actually believes — not a re-decode of a growing buffer.

Two costs, stated plainly:

- **No punctuation or capitalization.** Output is `how did you handle false
  positives in your vulnerability classification model`. Fine for RAG retrieval
  and for an LLM prompt; less pretty in the overlay than Parakeet or Moonshine,
  which both punctuate.
- **45% of the machine's CPU.** Higher than I would like, and partly ONNX Runtime
  thread spin rather than real work — worth tuning `num_threads` down before
  shipping. Still leaves the UI responsive, and PocketSphinx's 0.5% is not a fair
  comparison since it is a 7 MB HMM doing far less.

**Runner-up: Moonshine base EN** — best raw latency (220 ms / 406 ms), punctuates
and capitalizes, 141 MB. Take this one if stable partials matter less than
formatting. Its rolling-window instability is the reason it is not first.

**Not recommended:** Parakeet 0.6B streaming (too slow on CPU), Zipformer Kroko
(partials too slow), whisper.cpp small.en (1.6 s finalization, 751 MB RAM).

---

## 5. What is still needed before you act on this

**Record the corpus.** This is the one gap. Two minutes:

```powershell
py -3 packages\stt-bench\scripts\record_corpus.py
```

It prompts you through the four sentences, checks level and clipping, and lets
you redo any take. Then:

```powershell
cd packages\stt-bench
.\.venv\Scripts\python.exe scripts\run_bench.py
```

That produces the real accuracy table on human speech — the number that decides
whether the recommendation holds. My expectation is that the gap between
PocketSphinx and the neural engines *widens* substantially, because clean TTS is
where PocketSphinx does best. But that is a prediction, not a measurement, and I
am not treating it as settled.

---

## 6. Recommended production architecture

```
WASAPI loopback (existing, unchanged)
      ↓
SilenceGapFiller          ← NEW, fixes the timeline holes in §1
      ↓
16 kHz mono ring buffer
      ↓
STTEngine trait           ← NEW seam
  ├── PocketSphinxSTT     (kept for comparison / fallback)
  └── StreamingLocalASR   (sherpa-onnx, NeMo FastConformer 80 ms)
      ↓  worker thread, never the UI thread
partial events → overlay (live, updates ~200 ms)
final events   → TranscriptManager (unchanged)
```

Deliberately unchanged: transcript manager, Tauri command surface, overlay, RAG,
FastAPI backend, OpenAI integration, analysis. The engine swap is behind the
`STTEngine` seam.

Ordered by value:

1. **Wire in `SilenceGapFiller`.** Biggest single win, independent of engine
   choice, low risk.
2. **Replace the sidecar's engine** with sherpa-onnx NeMo FastConformer 80 ms,
   keeping the existing stdin-PCM / stdout-JSON protocol so `sidecar.rs`,
   `TranscriptManager` and the commands are untouched.
3. **Tune `num_threads`** to trade CPU against latency.
4. **Move model download to setup**, into an AppData-managed directory. The
   registry in `sttbench/models.py` already honours `STT_MODEL_DIR`.

An alternative worth considering: sherpa-onnx has a C API and Rust bindings, so
the engine could live in-process in Rust and drop the Python sidecar entirely.
More work, but it removes the Python dependency and one process boundary. Happy
to scope it if you want it.

---

## 7. Answers to the specific questions asked

| # | Question | Answer |
|---|---|---|
| 1 | PocketSphinx results | 10.7% WER on synthetic (flattering); 531 ms first partial, 379 ms finalize, 7 MB, 0.5% CPU |
| 2 | whisper.cpp results | base.en 0.0%/391 ms/579 ms/148 MB; small.en 0.0%/751 ms/1601 ms/488 MB. No streaming mode — rolling window only, unstable partials |
| 3 | Other candidates | Moonshine, Zipformer Kroko, NeMo FastConformer ×2, Parakeet unified ×3 — see §2 |
| 4 | Best engine | NeMo streaming FastConformer EN 80 ms (int8) |
| 5 | Accuracy comparison | **Not yet established** — synthetic corpus does not discriminate. Needs your recording (§5) |
| 6 | First-partial latency | 220 ms (Moonshine) to 3783 ms (Parakeet streaming); recommended engine 509 ms |
| 7 | Finalization latency | 384 ms recommended; 23516 ms worst (Parakeet streaming, cannot keep up) |
| 8 | CPU usage | 0.5% (PocketSphinx) to 59.3% (Parakeet); recommended engine 45.5% of a 16-thread machine |
| 9 | RAM usage | 108 MB to 884 MB peak RSS; recommended engine 228 MB |
| 10 | GPU usage | None. All CPU. GPU sampling was enabled and no candidate used it |
| 11 | Model size | 7 MB to 663 MB on disk; recommended engine 138 MB |
| 12 | Offline capability | Every candidate is fully offline after a one-time download. No audio leaves the machine |
| 13 | Production architecture | §6 |

---

## 8. What was built

`packages/stt-bench/` — standalone, isolated from the app. Nothing in
`apps/desktop` imports it; it imports nothing from the production pipeline.

- `STTEngine` contract (`start` / `feed_audio` / `poll` / `stop`), engines swap
  without touching WASAPI, transcript, commands, overlay, RAG or LLM
- 1x-real-time runner with explicit latency definitions
- WER scorer with completeness and technical-term recall
- Per-engine process isolation for honest RAM numbers
- Corpus recorder, one-time model downloader, streaming smoke test, live demo

In `apps/desktop/src-tauri/` — additive only, no behaviour change:

- `audio/metrics.rs` — pipeline counters (`start_with_metrics`; the existing
  `start` delegates to it)
- `audio/gap_fill.rs` — `SilenceGapFiller`, **not yet wired into production**
- `bin/audio_probe.rs` — measures the real capture path
- `bin/stt_spike.rs` — live loopback → streaming ASR demo
- `lib.rs` — `mod audio` → `pub mod audio` so the probe drives the real code

Untouched, as instructed: overlay UI, RAG, FastAPI, OpenAI integration, interview
analysis, authentication, plans, billing.
