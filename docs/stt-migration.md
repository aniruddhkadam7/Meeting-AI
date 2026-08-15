# STT migration: PocketSphinx → NeMo FastConformer 80 ms

What shipped, and what was measured against the live pipeline afterwards.
Engine selection rationale and the rejected alternatives are in
`docs/stt-benchmark.md`.

## What changed

**Two changes, in the order they matter.**

### 1. Silence gap-fill in the capture pipeline

WASAPI loopback delivers *no packets at all* while the render endpoint is idle —
not silent packets, nothing. Every speech endpointer decides an utterance is over
by observing trailing silence, so without that silence the final for a question
never fired until the interviewer happened to speak again. This produced late or
missing finals, lost last words, and separate questions glued into one segment.

`audio::SilenceGapFiller` tracks how much audio *should* exist by wall clock
against how much arrived, and emits real silence to close the difference. The
sidecar now always sees a continuous 16 kHz timeline.

Pause-aware: entering pause flushes the sidecar so a half-decoded question is
committed rather than left in the decoder, and resuming calls `resync()` to drop
the deficit accumulated across the pause instead of dumping the whole paused
duration into the decoder as one burst.

### 2. Engine replacement

`packages/stt/streaming_asr_sidecar/sidecar.py` (sherpa-onnx, NVIDIA NeMo
streaming FastConformer EN 80 ms int8) replaces the PocketSphinx sidecar. It
speaks the **identical wire protocol**, so `stt/sidecar.rs`, `TranscriptManager`,
the Tauri command surface, Interview Mode and the overlay are unchanged.

The model is loaded **once** at sidecar startup and stays resident. Between
questions the decoder state is cleared with `recognizer.reset(stream)` — a cheap
state reset; the ~130 MB of weights are never reloaded.

PocketSphinx remains reachable via `STT_ENGINE=pocketsphinx` for A/B on the same
machine without a rebuild.

### Supporting refactor

The capture → gap-fill → STT loop moved from `commands.rs` into
`audio::run_stt_pipeline`, free of Tauri types. The Tauri command passes an emit
closure; `src/bin/pipeline_test.rs` passes a print closure. This exists so the
headless test drives *the code that ships* rather than a copy of it.

## Measured on the live pipeline

Driven through `pipeline_test`, which runs `SystemAudioCapture` →
`run_stt_pipeline` → `SttSidecar` → `TranscriptManager` — the same path as the
Start button, minus the window.

### Accuracy

Three questions with clean silence between them, transcribed **verbatim**:

```
ref: Can you explain the RAG architecture you implemented and why you selected semantic search
got: can you explain the rag architecture you implemented and why you selected semantic search

ref: How did you handle false positives in your vulnerability classification model
got: how did you handle false positives in your vulnerability classification model

ref: I worked on integrating multiple security tools and used APIs to collect and normalize security data
got: i worked on integrating multiple security tools and used api's to collect and normalize security data
```

Zero word errors. The only deviations are surface form — `api's` for `APIs`,
`trade offs` for `tradeoffs`, and no capitalization or sentence punctuation.

For contrast, PocketSphinx on the same machine and the same audio source turned
"retrieval augmented generation" into "retrieval **on reddit** generation",
"chunk your documents" into "**jog** your documents", and "new **series**" into
"new **theories**".

### Latency

| Metric | Target | Measured |
|---|---|---|
| First partial | ~500 ms | ~790 ms from speech onset, including TTS spin-up |
| Partial updates | ~200 ms | 150–200 ms |
| Finalization | < 1 s | **461, 467, 476, 481, 487, 510, 600, 620, 708 ms** |

Finalization is the number the product feels, and it is consistently inside
budget. Partials extend monotonically — no rewriting or flicker.

### Lifecycle

Start → Pause → Resume → Stop, with speech timestamped against the pause window
to make the result provable:

| Spoken at | Content | In transcript | Correct |
|---|---|---|---|
| t=2.5 s (recording) | "Tell me about the vulnerability classification model you built" | yes, verbatim | ✅ |
| t=11.1 s (**paused**) | "MUST NOT APPEAR — spoken while the recorder is paused" | absent | ✅ |
| t=21.1 s (resumed) | "Can you explain how you deployed the application and handled monitoring in production" | yes | ✅ |

Segment count went 0 → 1 on pause: the flush committed the in-flight question
rather than losing it, which is the intended behaviour.

### A note on segment merging

An earlier run showed questions merging into one segment. That was **not** a
defect: a podcast was playing on the machine at the same time as the test speech,
so there was genuinely no silence to endpoint on. With real gaps between
questions, segmentation is clean (three questions → three segments above). No
change was made — shortening the silence window to "fix" it would have started
cutting real sentences in half.

This does mean a genuinely continuous speaker produces long segments. That is the
deliberate trade: `rule3_min_utterance_length` is effectively disabled because
truncating a question mid-sentence on a timer is worse than a long one.

## Setup

```powershell
py -3 -m venv packages\stt\.venv
packages\stt\.venv\Scripts\python.exe -m pip install sherpa-onnx numpy
py -3 packages\stt\scripts\install_model.py     # ~103 MB, once
```

The application never downloads at start-up and never contacts the network
during recording. Transcription is fully offline; no audio leaves the machine.

## Tuning

| Variable | Default | Effect |
|---|---|---|
| `STT_END_SILENCE_MS` | 600 | Trailing silence before finalizing. Lower = snappier finals, more risk of splitting mid-sentence |
| `STT_NUM_THREADS` | 4 | ONNX Runtime threads. More did not reduce latency and spent noticeably more CPU spinning |
| `STT_MODEL_DIR` | `models/stt/nemo-fastconformer-80ms-int8` | Model location |
| `STT_ENGINE` | `streaming` | Set `pocketsphinx` to fall back to the old engine |

## Known limitations

- **No punctuation or capitalization.** Fine for RAG retrieval and LLM prompting;
  less pretty in the overlay. Moonshine and Parakeet punctuate but were rejected
  for partial instability and CPU cost respectively.
- **~45% of a 16-thread machine** during active decoding. Worth revisiting
  `STT_NUM_THREADS` on lower-core laptops.
- **Model directory is repo-relative.** Should move to AppData before packaging;
  `STT_MODEL_DIR` already exists for that.
- **Python sidecar retained.** sherpa-onnx has a C API and Rust bindings, so this
  could move in-process and drop the Python dependency entirely. Not attempted —
  it would have changed far more than the engine.

## Not touched

RAG, FastAPI backend, OpenAI integration, interview analysis, authentication,
plans, billing, overlay UI, transcript manager, Tauri command surface.
