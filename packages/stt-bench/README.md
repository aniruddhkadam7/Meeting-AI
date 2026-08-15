# STT benchmark spike

Standalone harness for choosing the speech-to-text engine. It is deliberately
isolated from the desktop app: nothing in `apps/desktop` imports it, and it
imports nothing from the production pipeline. Deleting this directory cannot
break the application.

Everything runs locally. No audio and no transcript leaves the machine; the only
network access is the one-time model download.

## Setup

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\download_models.py     # ~2.2 GB, once
```

Models land in `models/stt-bench/` at the repo root (override with
`STT_MODEL_DIR`). Re-running the downloader is free — installed models are
skipped without touching the network, which is the same behaviour the shipping
app needs.

## Recording the corpus

Accuracy is scored against four fixed sentences, recorded once in a real voice
and then replayed byte-identically through every engine.

```powershell
py -3 scripts\record_corpus.py
```

Writes `corpus/human/s1.wav` .. `s4.wav` (16 kHz mono). The script checks each
take for level and clipping and lets you redo any of them.

A synthetic corpus generated with the built-in Windows voice lives in
`corpus/synthetic/`. It is useful for checking the harness end to end, but it
flatters every engine — clean TTS has none of the coarticulation, breath, or
room tone that real speech does. Do not draw conclusions from it.

## Running

```powershell
py -3 scripts\run_bench.py                                  # all engines, human corpus
py -3 scripts\run_bench.py --engines nemo-80ms pocketsphinx
py -3 scripts\run_bench.py --corpus corpus\synthetic
```

Audio is fed at **1x real time** in 100 ms chunks. An engine cannot look fast by
being handed the file all at once, and one that cannot keep up shows it as
growing lag rather than as a short total runtime.

## Checking that an engine really streams

```powershell
py -3 scripts\smoke_test.py nemo-80ms
```

Prints every partial with the audio offset and wall-clock time at which it
appeared. Progressive output means the engine is genuinely incremental;
everything appearing at the end means it is not, whatever its docs claim.

## Live loopback demo

End-to-end on real system audio, using the app's own WASAPI capture path:

```powershell
cargo run --bin stt_spike --manifest-path ..\..\apps\desktop\src-tauri\Cargo.toml | `
  .\.venv\Scripts\python.exe scripts\live_spike.py nemo-80ms
```

Interim text is rewritten in place; finals are committed to their own line.

## Measuring the audio pipeline

```powershell
cargo run --bin audio_probe --manifest-path ..\..\apps\desktop\src-tauri\Cargo.toml -- 20
```

Reports sample rate, channel count, chunk size distribution, queue depth,
resample cost, WASAPI discontinuity flags, and audio delivered per second of
wall time. This is what surfaced the loopback timeline gap documented in
`docs/stt-benchmark.md`.

## Layout

```
sttbench/
  sentences.py      the four reference sentences + technical terms
  audio.py          16 kHz mono WAV IO, chunking, silence padding
  vad.py            lightweight energy VAD ("is someone speaking", nothing more)
  models.py         model registry + one-time downloader
  runner.py         1x-real-time driver and latency definitions
  metrics/
    wer.py          WER, completeness, technical-term recall
    resources.py    CPU / RAM / GPU sampling
  engines/
    base.py             STTEngine contract
    pocketsphinx_engine.py  baseline, mirrors the production sidecar
    sherpa_streaming.py     native streaming transducers
    rolling.py              rolling-window driver for offline models
    sherpa_offline.py       Moonshine, Parakeet offline
    whispercpp_engine.py    whisper.cpp via pywhispercpp
scripts/
  record_corpus.py   download_models.py   run_bench.py
  smoke_test.py      live_spike.py
```

## Adding an engine

Implement `STTEngine` (`start` / `feed_audio` / `poll` / `stop`), register it in
`ENGINES` in `scripts/run_bench.py`, and it is picked up by the runner, the
smoke test, and the live demo. `feed_audio` must not block on inference — do the
work on a worker thread and surface results through `poll()`. The benchmark
measures and reports whether you did.
