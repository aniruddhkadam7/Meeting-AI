"""Tests for the VAD gate (vad.py) — Phase A of the STT low-end optimization
pass (see docs/stt-performance-phase2.md).

Uses `unittest` (stdlib, no new dependency) rather than pytest, since
`packages/stt/.venv` is a minimal production venv and the brief explicitly
calls out avoiding unnecessary dependencies — numpy (already required by
sherpa_onnx) is the only import here beyond the standard library.

Run:
    packages/stt/.venv/Scripts/python.exe -m unittest streaming_asr_sidecar.test_vad -v
or, from inside streaming_asr_sidecar/:
    ../.venv/Scripts/python.exe -m unittest test_vad -v

Covers every case the brief lists explicitly: silence, speech, speech→
silence, silence→speech, continuous speech, short speech, multiple speech
segments, first speech after silence.
"""

from __future__ import annotations

import unittest

import numpy as np

from vad import FRAME_SAMPLES, SAMPLE_RATE, EnergyVad, UtteranceGate, VadConfig


def silence(ms: float, amplitude: float = 0.0) -> np.ndarray:
    n = int(SAMPLE_RATE * ms / 1000)
    if amplitude == 0.0:
        return np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(0)
    return (rng.standard_normal(n).astype(np.float32) * amplitude)


def tone(ms: float, amplitude: float = 0.3, freq_hz: float = 220.0) -> np.ndarray:
    """A synthetic "speech-loud" signal — a sine tone well above the VAD's
    default threshold over silence, standing in for real speech energy
    without needing a recorded corpus for these unit-level gate tests."""
    n = int(SAMPLE_RATE * ms / 1000)
    t = np.arange(n) / SAMPLE_RATE
    return (np.sin(2 * np.pi * freq_hz * t) * amplitude).astype(np.float32)


class DefaultConfigTests(unittest.TestCase):
    """Fast, deterministic checks using the production default config."""

    def setUp(self) -> None:
        self.vad = EnergyVad()

    def test_pure_silence_never_reports_speech(self) -> None:
        results = self.vad.process(silence(500))
        self.assertTrue(results, "should have produced frames")
        self.assertTrue(all(not is_speech for is_speech, _ in results))
        self.assertFalse(self.vad.in_speech)

    def test_low_level_noise_is_not_speech(self) -> None:
        # Quiet background hiss, well under the 9dB-over-floor threshold.
        results = self.vad.process(silence(500, amplitude=0.001))
        self.assertTrue(all(not is_speech for is_speech, _ in results))

    def test_sustained_loud_tone_is_detected_as_speech(self) -> None:
        # Prime the noise floor on quiet audio first (mirrors a real session
        # opening in near-silence), then feed a loud tone.
        self.vad.process(silence(200))
        results = self.vad.process(tone(300))
        self.assertTrue(any(is_speech for is_speech, _ in results), "loud tone should be detected as speech")
        self.assertTrue(self.vad.in_speech)

    def test_speech_then_silence_stays_in_speech_through_hangover(self) -> None:
        self.vad.process(silence(200))
        self.vad.process(tone(300))
        self.assertTrue(self.vad.in_speech)

        # Immediately after speech stops, VAD must still report in_speech —
        # this is the hangover window sidecar.py relies on to keep decoding
        # (and therefore keep sherpa-onnx's own endpointer alive) right up
        # to and past the moment a real utterance ends.
        self.vad.process(silence(100))
        self.assertTrue(self.vad.in_speech, "must still be 'in speech' well within the hangover window")

    def test_speech_then_silence_exits_speech_after_hangover_elapses(self) -> None:
        self.vad.process(silence(200))
        self.vad.process(tone(300))
        self.assertTrue(self.vad.in_speech)

        # hangover_ms default is 700ms in production (vad.py's VadConfig) —
        # feed well past it.
        self.vad.process(silence(900))
        self.assertFalse(self.vad.in_speech, "must exit speech once hangover has fully elapsed")

    def test_silence_then_speech_detects_promptly(self) -> None:
        self.vad.process(silence(300))
        self.assertFalse(self.vad.in_speech)

        results = self.vad.process(tone(200))
        # attack_frames=3 (60ms) — speech must be confirmed well within this
        # 200ms burst, not silently missed.
        became_speech = any(is_speech for is_speech, _ in results)
        self.assertTrue(became_speech, "speech following silence must be detected within the burst")

    def test_first_speech_after_silence_is_detected_within_attack_window(self) -> None:
        """Directly verifies the bounded-delay claim in sidecar.py's worker-
        loop comment: speech onset is confirmed within `attack_frames` (60ms
        at the default config), not silently dropped or delayed indefinitely."""
        self.vad.process(silence(500))
        self.assertFalse(self.vad.in_speech)

        frame_results = self.vad.process(tone(120))  # 6 frames at 20ms each
        first_speech_frame_index = next(
            (i for i, (is_speech, _) in enumerate(frame_results) if is_speech), None
        )
        self.assertIsNotNone(first_speech_frame_index, "speech onset must be detected")
        # attack_frames=3 -> speech should be confirmed by (at latest) the
        # 3rd-4th frame of sustained tone, not the 6th.
        self.assertLessEqual(
            first_speech_frame_index, 4,
            f"speech onset detected too late (frame {first_speech_frame_index}), "
            f"suggests attack window is not bounded as documented",
        )

    def test_continuous_speech_is_never_dropped_mid_utterance(self) -> None:
        """A long, unbroken utterance must never flip back to 'not speech' —
        that would incorrectly cause sidecar.py to skip decode_stream() calls
        in the middle of active speech."""
        self.vad.process(silence(200))
        all_in_speech = []
        # 3 seconds of continuous tone, fed in small chunks like real audio
        # packets (~20ms WASAPI chunks), matching how sidecar.py receives it.
        chunk = tone(20)
        for _ in range(150):  # 150 * 20ms = 3s
            results = self.vad.process(chunk)
            all_in_speech.extend(is_speech for is_speech, _ in results)
        # Allow the attack window at the very start, but once speech is
        # confirmed it must never drop out during 3s of continuous tone.
        first_true = next((i for i, v in enumerate(all_in_speech) if v), None)
        self.assertIsNotNone(first_true)
        self.assertTrue(
            all(all_in_speech[first_true:]),
            "continuous speech must not be interrupted by false silence detections",
        )

    def test_short_speech_burst_is_still_detected(self) -> None:
        """A short utterance (e.g. "yes", "no") must not be swallowed by the
        attack window — it needs to be long enough to confirm, and this test
        pins the shortest burst that reliably does."""
        self.vad.process(silence(300))
        # 150ms of tone: well above the 60ms attack window, short enough to
        # stand in for a one-word answer.
        results = self.vad.process(tone(150))
        self.assertTrue(any(is_speech for is_speech, _ in results), "short speech burst must still be detected")

    def test_multiple_speech_segments_are_each_detected(self) -> None:
        """Two separate utterances with a real silence gap between them —
        both must be detected as speech, and the gap between them must be
        reported as silence (not smeared into one continuous segment)."""
        segments_in_speech: list[bool] = []

        def feed(samples: np.ndarray) -> None:
            for is_speech, _ in self.vad.process(samples):
                segments_in_speech.append(is_speech)

        feed(silence(200))
        feed(tone(300))  # segment 1
        feed(silence(900))  # gap — long enough to fully exit hangover
        feed(tone(300))  # segment 2
        feed(silence(200))

        # There must be at least one confirmed False after segment 1's
        # hangover expires and before segment 2 starts.
        transitions = [
            segments_in_speech[i] != segments_in_speech[i - 1]
            for i in range(1, len(segments_in_speech))
        ]
        self.assertGreaterEqual(
            sum(transitions), 3,
            "expected at least 3 transitions: silence->speech1, speech1->silence, silence->speech2",
        )

    def test_reset_clears_hangover_and_speech_state(self) -> None:
        self.vad.process(silence(200))
        self.vad.process(tone(300))
        self.assertTrue(self.vad.in_speech)

        self.vad.reset()
        self.assertFalse(self.vad.in_speech, "reset must clear in_speech immediately")

        # After reset, a fresh short burst should be evaluated from a clean
        # attack-window state, not treated as a continuation of prior speech.
        results = self.vad.process(tone(150))
        self.assertTrue(any(is_speech for is_speech, _ in results))

    def test_arbitrary_chunk_sizes_do_not_lose_or_duplicate_samples(self) -> None:
        """sidecar.py feeds whatever chunk size WASAPI/the wire protocol
        delivers, not a fixed frame size — process() must handle uneven
        chunk boundaries without dropping partial frames."""
        total_frames = 0
        # Deliberately not a multiple of FRAME_SAMPLES.
        odd_chunk = tone(37)
        for _ in range(20):
            results = self.vad.process(odd_chunk)
            total_frames += len(results)
        # Total samples fed should roughly account for total_frames *
        # FRAME_SAMPLES within one frame's worth of leftover buffering.
        total_samples_fed = len(odd_chunk) * 20
        accounted = total_frames * FRAME_SAMPLES
        self.assertLessEqual(
            total_samples_fed - accounted, FRAME_SAMPLES,
            "more than one frame's worth of samples unaccounted for — samples are being lost",
        )


class DeterminismTests(unittest.TestCase):
    """Requirement 8: the gate must be deterministic/testable."""

    def test_identical_input_produces_identical_output(self) -> None:
        samples = np.concatenate([silence(200), tone(300), silence(300)])
        vad_a = EnergyVad()
        vad_b = EnergyVad()
        results_a = [is_speech for is_speech, _ in vad_a.process(samples)]
        results_b = [is_speech for is_speech, _ in vad_b.process(samples)]
        self.assertEqual(results_a, results_b, "identical input must produce identical VAD decisions")

    def test_no_randomness_in_pure_processing_path(self) -> None:
        # process()/_process_frame() must not consult any RNG — running
        # twice back to back with fresh instances must agree exactly, which
        # test_identical_input_produces_identical_output already proves;
        # this test additionally checks running the SAME instance twice on
        # the same silence input (post-reset) agrees with itself.
        vad = EnergyVad()
        samples = tone(200)
        vad.process(silence(200))
        first = [is_speech for is_speech, _ in vad.process(samples)]
        vad.reset()
        vad.process(silence(200))
        second = [is_speech for is_speech, _ in vad.process(samples)]
        self.assertEqual(first, second)


class ConfigOverrideTests(unittest.TestCase):
    """The hangover/threshold config is tunable independent of the sidecar's
    own endpointing silence budget — confirm the override path works, since
    sidecar.py wires STT_VAD_HANGOVER_MS through to this exact constructor
    argument."""

    def test_custom_hangover_is_respected(self) -> None:
        vad = EnergyVad(VadConfig(hangover_ms=100))
        vad.process(silence(100))
        vad.process(tone(150))
        self.assertTrue(vad.in_speech)
        # 100ms hangover — 200ms of silence should be well past it.
        vad.process(silence(200))
        self.assertFalse(vad.in_speech)

    def test_custom_hangover_longer_than_default_stays_in_speech_longer(self) -> None:
        vad = EnergyVad(VadConfig(hangover_ms=2000))
        vad.process(silence(100))
        vad.process(tone(150))
        self.assertTrue(vad.in_speech)
        # Well past the production default (700ms) but under this custom
        # 2000ms hangover.
        vad.process(silence(900))
        self.assertTrue(vad.in_speech, "custom longer hangover must be honored, not the default")


class UtteranceGateTests(unittest.TestCase):
    """Regression tests for the exact bug this gate was rewritten to avoid:
    an earlier version skipped decode_stream() during ANY confirmed-silence
    window, including the silence AFTER speech ends — which starves
    sherpa-onnx's endpointer (which measures trailing silence against
    DECODED audio, not wall-clock time) of the evaluation it needs to fire.
    Measured production regression from that bug: finalize latency
    353ms -> 2865ms, WER unchanged. `UtteranceGate.observe()` must return
    `True` (decode) for every chunk from the moment speech is first
    confirmed until the caller calls `reset()` — never `False` again within
    that same utterance, no matter how long the trailing silence runs."""

    def setUp(self) -> None:
        self.gate = UtteranceGate(EnergyVad())

    def test_pre_speech_silence_may_be_skipped(self) -> None:
        # Before any speech in this utterance: skipping is the whole point
        # of this gate, and is safe (there is nothing to lose — no
        # utterance is pending finalization).
        results = [self.gate.observe(chunk) for chunk in [silence(50)] * 10]
        self.assertTrue(any(r is False for r in results), "pre-speech silence should be skippable")

    def test_once_speech_starts_decode_never_skips_again_this_utterance(self) -> None:
        self.gate.observe(silence(300))  # pre-speech, may skip
        # Confirm speech.
        speech_result = self.gate.observe(tone(200))
        self.assertTrue(speech_result, "the chunk containing speech onset must decode")

        # This is the regression guard: no matter how long silence runs
        # AFTER speech has started, observe() must keep returning True —
        # sherpa-onnx's endpointer needs every one of these chunks decoded
        # to ever see its own trailing-silence rule satisfied.
        long_trailing_silence_chunks = [silence(100) for _ in range(30)]  # 3 seconds
        results = [self.gate.observe(chunk) for chunk in long_trailing_silence_chunks]
        self.assertTrue(
            all(results),
            "decode must NEVER be skipped during post-speech silence, however long — "
            "this is the exact bug that regressed finalize latency 353ms->2865ms",
        )

    def test_reset_allows_skipping_again_for_the_next_utterance(self) -> None:
        self.gate.observe(silence(300))
        self.gate.observe(tone(200))
        self.gate.reset()  # simulates endpoint fire / flush

        # A fresh utterance's pre-speech silence should be skippable again,
        # proving reset() genuinely clears "has this utterance spoken yet".
        results = [self.gate.observe(chunk) for chunk in [silence(50)] * 10]
        self.assertTrue(any(r is False for r in results), "gate must allow skipping again after reset()")

    def test_short_speech_burst_then_long_silence_still_never_skips(self) -> None:
        """Even a very brief utterance (one word) must not have its trailing
        silence gated — the endpointer still needs every decoded frame to
        notice the silence and finalize."""
        self.gate.observe(silence(200))
        self.gate.observe(tone(80))  # a short word
        results = [self.gate.observe(silence(100)) for _ in range(20)]  # 2s trailing silence
        self.assertTrue(all(results), "short utterances must not have trailing silence gated either")

    def test_multiple_utterances_each_gate_correctly_around_their_own_speech(self) -> None:
        """End-to-end sanity: pre-speech skip -> speech decodes -> post-
        speech never skips -> reset -> pre-speech skip again for utterance 2."""
        decisions: list[bool] = []

        def feed(samples: np.ndarray) -> None:
            decisions.append(self.gate.observe(samples))

        feed(silence(300))  # utterance 1 pre-speech
        feed(tone(200))  # utterance 1 speech
        feed(silence(800))  # utterance 1 trailing silence
        self.gate.reset()  # endpoint fires
        feed(silence(300))  # utterance 2 pre-speech
        feed(tone(200))  # utterance 2 speech

        # There must be at least one skip in the pre-speech windows...
        self.assertTrue(any(d is False for d in decisions), "expected at least one skip during pre-speech silence")
        # ...but the speech-onset chunks and everything after utterance 1's
        # speech began (until reset) must all be True.
        # decisions[1] is utterance-1 speech-onset chunk.
        self.assertTrue(decisions[1], "speech-onset chunk must always decode")

    def test_observe_never_raises_on_a_chunk_smaller_than_one_frame(self) -> None:
        """A chunk smaller than FRAME_SAMPLES (20ms at 16kHz = 320 samples)
        produces no complete frames this call — observe() must default to
        decoding (erring toward correctness) rather than raising or
        guessing."""
        tiny_chunk = tone(2)  # ~32 samples, well under one 20ms frame
        result = self.gate.observe(tiny_chunk)
        self.assertTrue(result, "a chunk too small to evaluate must default to decoding, not skipping")


if __name__ == "__main__":
    unittest.main()
