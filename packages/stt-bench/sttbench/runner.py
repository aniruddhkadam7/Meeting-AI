"""Benchmark driver.

The one rule that makes these numbers mean anything: **audio is fed at 1x real
time**. Every engine gets a 100 ms chunk, then the runner sleeps until the wall
clock catches up with the audio clock. An engine cannot look fast by being
handed the whole file at once, and an engine that cannot keep up shows it as
growing lag rather than as a fast total runtime.

Latency definitions, all measured against the same per-clip speech boundaries
so they are comparable across engines:

    t0                 wall clock when feeding started
    speech_start_s     audio offset where the speaker began (VAD, computed once
                       per clip and reused for every engine)
    speech_end_s       audio offset where the speaker stopped

    first_partial_ms   wall(first partial)  - (t0 + speech_start_s)
                       "how long after they start talking does text appear"
    finalization_ms    wall(last final)     - (t0 + speech_end_s)
                       "how long after they stop talking does the text settle"
    partial_interval_ms  median gap between consecutive partial events

`feed_block_ms_p99` is the 99th-percentile time `feed_audio()` itself took. In
the real app that call happens on the audio path, so anything large there is a
direct UI-stall risk. It is the check for requirement 10, "STT must not block
the UI thread".
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .audio import Clip, chunk, pad_silence
from .engines.base import EngineUnavailable, STTEngine, SttEvent
from .metrics import wer as wer_metrics
from .metrics.resources import ResourceMonitor, ResourceStats
from .sentences import TECHNICAL_TERMS, Sentence
from .vad import EnergyVad, VadConfig

#: Chunk handed to the engine per step. 100 ms matches the order of magnitude of
#: the app's WASAPI packets after resampling and is small enough that it does
#: not itself dominate first-partial latency.
FEED_CHUNK_MS = 100

#: Silence appended after each clip so endpointing engines can actually fire.
#: Paced in real time like everything else, and long enough that a slow
#: finalizer is measured rather than truncated.
TRAILING_SILENCE_MS = 2000


@dataclass
class ClipResult:
    sentence_id: str
    reference: str
    hypothesis: str
    wer: float
    accuracy: float
    completeness: float
    substitutions: int
    deletions: int
    insertions: int
    ref_words: int
    terms_found: int
    terms_expected: int
    terms_missed: list[str]
    first_partial_ms: float | None
    finalization_ms: float | None
    partial_interval_ms: float | None
    partial_count: int
    final_count: int
    partial_revisions: int
    feed_block_ms_p99: float
    feed_block_ms_max: float
    audio_duration_s: float
    speech_start_s: float
    speech_end_s: float


@dataclass
class EngineResult:
    engine_name: str
    strategy: str
    model_name: str
    model_size_mb: float
    supports_partials: bool
    offline: bool
    notes: str
    available: bool = True
    unavailable_reason: str = ""
    load_time_s: float = 0.0
    clips: list[ClipResult] = field(default_factory=list)
    resources: dict = field(default_factory=dict)

    # -- aggregates used by the report --------------------------------------

    @property
    def overall_wer(self) -> float:
        """Corpus-level WER: total errors over total reference words. This is
        the standard aggregation, and unlike averaging per-clip WERs it does not
        let one short sentence dominate."""
        if not self.clips:
            return 1.0
        errors = sum(c.substitutions + c.deletions + c.insertions for c in self.clips)
        words = sum(c.ref_words for c in self.clips)
        return errors / words if words else 1.0

    @property
    def overall_accuracy(self) -> float:
        return max(0.0, 1.0 - self.overall_wer)

    @property
    def overall_completeness(self) -> float:
        if not self.clips:
            return 0.0
        hits = sum(c.ref_words - c.deletions - c.substitutions for c in self.clips)
        words = sum(c.ref_words for c in self.clips)
        return hits / words if words else 0.0

    @property
    def term_recall(self) -> float:
        expected = sum(c.terms_expected for c in self.clips)
        found = sum(c.terms_found for c in self.clips)
        return found / expected if expected else 0.0

    def _median(self, attr: str) -> float | None:
        values = [getattr(c, attr) for c in self.clips if getattr(c, attr) is not None]
        return statistics.median(values) if values else None

    @property
    def median_first_partial_ms(self) -> float | None:
        return self._median("first_partial_ms")

    @property
    def median_finalization_ms(self) -> float | None:
        return self._median("finalization_ms")

    @property
    def median_partial_interval_ms(self) -> float | None:
        return self._median("partial_interval_ms")

    @property
    def max_feed_block_ms(self) -> float:
        return max((c.feed_block_ms_max for c in self.clips), default=0.0)


def speech_bounds(clip: Clip) -> tuple[float, float]:
    """Finds where speech starts and ends in a clip, using the same VAD for
    every engine so latency numbers share one definition of 'they started
    talking'."""
    vad = EnergyVad(VadConfig(hangover_ms=300))
    frame_s = 0.02
    first: float | None = None
    last: float | None = None
    for index, (is_speech, _frame) in enumerate(vad.process(clip.samples)):
        if is_speech:
            if first is None:
                first = index * frame_s
            last = (index + 1) * frame_s
    if first is None:
        return 0.0, clip.duration_s
    return first, last if last is not None else clip.duration_s


def run_clip(
    engine: STTEngine,
    sentence: Sentence,
    clip: Clip,
    bounds: tuple[float, float],
) -> ClipResult:
    speech_start_s, speech_end_s = bounds
    padded = pad_silence(clip, TRAILING_SILENCE_MS)
    chunks = chunk(padded, FEED_CHUNK_MS)

    events: list[SttEvent] = []
    feed_block_ms: list[float] = []

    t0 = time.monotonic()
    audio_time = 0.0
    for block in chunks:
        before = time.monotonic()
        engine.feed_audio(block)
        feed_block_ms.append((time.monotonic() - before) * 1000.0)

        events.extend(engine.poll())

        # Pace to real time: wait until the wall clock reaches the audio clock.
        audio_time += len(block) / 16000.0
        sleep_for = (t0 + audio_time) - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            events.extend(engine.poll())

    events.extend(engine.stop())

    partials = [e for e in events if not e.is_final]
    finals = [e for e in events if e.is_final]

    first_partial_ms = None
    if partials:
        first_partial_ms = (partials[0].wall_time_s - (t0 + speech_start_s)) * 1000.0

    finalization_ms = None
    if finals:
        finalization_ms = (finals[-1].wall_time_s - (t0 + speech_end_s)) * 1000.0

    partial_interval_ms = None
    if len(partials) >= 2:
        gaps = [
            (b.wall_time_s - a.wall_time_s) * 1000.0
            for a, b in zip(partials, partials[1:])
        ]
        partial_interval_ms = statistics.median(gaps)

    hypothesis = " ".join(e.text.strip() for e in finals if e.text.strip()).strip()
    # An engine that produced partials but never finalized would otherwise score
    # 100% WER and hide the real behaviour; fall back to the last partial and
    # let the finalization metric report the miss.
    if not hypothesis and partials:
        hypothesis = partials[-1].text.strip()

    result = wer_metrics.score(sentence.text, hypothesis)
    found, expected, missed = wer_metrics.term_recall(
        sentence.text, hypothesis, TECHNICAL_TERMS
    )

    revisions = getattr(engine, "partial_revisions", 0)

    return ClipResult(
        sentence_id=sentence.id,
        reference=sentence.text,
        hypothesis=hypothesis,
        wer=result.wer,
        accuracy=result.accuracy,
        completeness=result.completeness,
        substitutions=result.substitutions,
        deletions=result.deletions,
        insertions=result.insertions,
        ref_words=result.ref_words,
        terms_found=found,
        terms_expected=expected,
        terms_missed=missed,
        first_partial_ms=first_partial_ms,
        finalization_ms=finalization_ms,
        partial_interval_ms=partial_interval_ms,
        partial_count=len(partials),
        final_count=len(finals),
        partial_revisions=revisions,
        feed_block_ms_p99=_percentile(feed_block_ms, 99),
        feed_block_ms_max=max(feed_block_ms, default=0.0),
        audio_duration_s=clip.duration_s,
        speech_start_s=speech_start_s,
        speech_end_s=speech_end_s,
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1))))
    return ordered[index]


def run_engine(
    build_engine,
    sentences: list[Sentence],
    clips: dict[str, Clip],
    bounds: dict[str, tuple[float, float]],
    *,
    watch_gpu: bool = False,
) -> EngineResult:
    """Runs one engine over the whole corpus. An engine whose model or runtime
    is missing is reported as unavailable rather than aborting the run."""
    try:
        engine = build_engine()
    except EngineUnavailable as exc:
        return EngineResult(
            engine_name=str(exc),
            strategy="",
            model_name="",
            model_size_mb=0.0,
            supports_partials=False,
            offline=True,
            notes="",
            available=False,
            unavailable_reason=str(exc),
        )

    info = engine.info
    load_time = 0.0
    with ResourceMonitor(watch_gpu=watch_gpu) as monitor:
        # Model loading is excluded from the resource numbers throughout: it is
        # a one-time start-up cost, not the steady-state load the app has to
        # live with while someone is talking.
        monitor.pause()
        try:
            load_started = time.monotonic()
            engine.start()
            load_time = time.monotonic() - load_started
        except EngineUnavailable as exc:
            return EngineResult(
                engine_name=info.name,
                strategy=info.strategy,
                model_name=info.model_name,
                model_size_mb=info.model_size_bytes / 1e6,
                supports_partials=info.supports_partials,
                offline=info.offline,
                notes=info.notes,
                available=False,
                unavailable_reason=str(exc),
            )
        monitor.resume()

        clip_results: list[ClipResult] = []
        for sentence in sentences:
            clip = clips[sentence.id]
            if clip_results:
                # Fresh decoder state per sentence, matching how the app treats
                # each interviewer turn.
                monitor.pause()
                engine.start()
                monitor.resume()
            clip_results.append(run_clip(engine, sentence, clip, bounds[sentence.id]))

    stats: ResourceStats = monitor.stats()
    info = engine.info  # re-read: size is known only after the model loaded

    return EngineResult(
        engine_name=info.name,
        strategy=info.strategy,
        model_name=info.model_name,
        model_size_mb=info.model_size_bytes / 1e6,
        supports_partials=info.supports_partials,
        offline=info.offline,
        notes=info.notes,
        load_time_s=load_time,
        clips=clip_results,
        resources={
            "cpu_percent_mean_one_core": round(stats.cpu_percent_mean, 1),
            "cpu_percent_peak_one_core": round(stats.cpu_percent_peak, 1),
            "cpu_percent_mean_of_machine": round(stats.cpu_percent_of_machine, 1),
            "cpu_percent_peak_of_machine": round(stats.cpu_peak_of_machine, 1),
            "cpu_logical_cores": stats.cpu_cores,
            "rss_mb_peak": round(stats.rss_mb_peak, 1),
            "rss_mb_delta": round(stats.rss_mb_delta, 1),
            "gpu_percent_peak": stats.gpu_percent_peak,
            "gpu_mem_mb_peak": stats.gpu_mem_mb_peak,
            "samples": stats.samples,
        },
    )


def save_results(results: list[EngineResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "feed_chunk_ms": FEED_CHUNK_MS,
        "trailing_silence_ms": TRAILING_SILENCE_MS,
        "engines": [
            {
                **asdict(r),
                "overall_wer": r.overall_wer,
                "overall_accuracy": r.overall_accuracy,
                "overall_completeness": r.overall_completeness,
                "term_recall": r.term_recall,
                "median_first_partial_ms": r.median_first_partial_ms,
                "median_finalization_ms": r.median_finalization_ms,
                "median_partial_interval_ms": r.median_partial_interval_ms,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
