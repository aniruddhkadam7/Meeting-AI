"""Local PocketSphinx STT sidecar.

Spawned as a child process by the Tauri/Rust desktop app. Never touches the
network. Reads raw 16kHz mono 16-bit PCM audio frames from stdin (each frame
length-prefixed with a 4-byte little-endian uint32), runs them through a
PocketSphinx `Endpointer` (energy/VAD-based speech boundary detection — not
semantic "question detection") plus a streaming `Decoder`, and writes one JSON
object per line to stdout for each partial or final transcript event.

Protocol (stdin):  [u32 len LE][len bytes of PCM16 mono @16kHz] ...
                    A zero-length frame means "flush/end of stream".
Protocol (stdout, one JSON object per line):
    {"type": "partial", "text": "...", "source": "SYSTEM_AUDIO"}
    {"type": "final",   "text": "...", "source": "SYSTEM_AUDIO",
     "start_time": 12.34, "end_time": 13.02}
    {"type": "ready"}
    {"type": "error", "message": "..."}

The `source` tag is passed once at startup via argv and stamped on every event;
this sidecar itself does not distinguish audio sources, it just decodes
whatever PCM it is given.

End-silence tuning (Step 10b): the `Endpointer`'s `window` parameter is the
length of the trailing-silence decision window used to decide "speech has
ended" — with the library default of `window=0.3, ratio=0.9`, only about 270ms
of trailing silence (90% of a 300ms window) is needed to trigger finalization.
In practice this was cutting off the last word of a sentence and fragmenting
one spoken utterance into several finalized segments on any brief pause. This
sidecar now reads `STT_END_SILENCE_MS` (default 450, per spec) and passes
`window = STT_END_SILENCE_MS / 1000` to the Endpointer, trading a little extra
latency at the end of each utterance for materially more complete text —
deliberately not raised further than ~600ms, since that starts to feel
noticeably laggy in a live interview overlay.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import time
from pathlib import Path

from pocketsphinx import Config, Decoder, Endpointer

DEFAULT_END_SILENCE_MS = 450
MIN_END_SILENCE_MS = 150
MAX_END_SILENCE_MS = 2000

# Supplementary pronunciation dictionary for tech/interview vocabulary absent
# from PocketSphinx's bundled CMU dictionary (e.g. "APIs", "LLM", "Kubernetes").
# Merged into a temp copy of the base dictionary at startup — see
# `_build_dictionary_path`. This only adds words the decoder can *spell*; it
# does not change the trigram language model's probability for them, so it
# helps words that already have reasonable LM support under their component
# tokens but not truly novel/rare terms (see docs/progress.md STT tuning
# notes for the measured limits of this approach).
TECH_VOCAB_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "models"
    / "pocketsphinx"
    / "tech_vocab.dict"
)


def _build_dictionary_path(base_dict_path: str) -> str:
    """Merges the base CMU dictionary with the tech-vocabulary supplement into
    a temp file and returns its path, or the original path unchanged if the
    supplement is missing/unreadable (never fatal — STT still works with just
    the base dictionary)."""
    if not TECH_VOCAB_PATH.exists():
        return base_dict_path
    try:
        with open(base_dict_path, encoding="latin-1") as f:
            base_lines = f.readlines()
        with open(TECH_VOCAB_PATH, encoding="utf-8") as f:
            supp_lines = [line for line in f if line.strip()]
        supp_words = {line.split()[0].lower() for line in supp_lines}
        filtered_base = [
            line for line in base_lines if line.split()[0].lower() not in supp_words
        ]

        fd, merged_path = tempfile.mkstemp(suffix=".dict", prefix="ia_merged_")
        with os.fdopen(fd, "w", encoding="latin-1") as f:
            f.writelines(filtered_base)
            f.writelines(supp_lines)
        return merged_path
    except OSError:
        return base_dict_path


def _resolve_end_silence_seconds() -> float:
    raw = os.environ.get("STT_END_SILENCE_MS", "").strip()
    ms = DEFAULT_END_SILENCE_MS
    if raw:
        try:
            ms = int(raw)
        except ValueError:
            ms = DEFAULT_END_SILENCE_MS
    ms = max(MIN_END_SILENCE_MS, min(MAX_END_SILENCE_MS, ms))
    return ms / 1000.0


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_exact(stream, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "SYSTEM_AUDIO"
    end_silence_s = _resolve_end_silence_seconds()

    try:
        config = Config()
        config["samprate"] = 16000
        base_dict = config.get_string("dict")
        if base_dict:
            config["dict"] = _build_dictionary_path(base_dict)
        decoder = Decoder(config)
        endpointer = Endpointer(sample_rate=16000, window=end_silence_s)
    except Exception as exc:  # noqa: BLE001 - report and exit, don't crash silently
        emit({"type": "error", "message": f"failed to initialize decoder: {exc}"})
        return 1

    emit({"type": "ready", "end_silence_ms": int(end_silence_s * 1000)})

    stdin = sys.stdin.buffer
    in_utt = False
    utt_start_time = None
    frame_bytes = endpointer.frame_bytes
    pending = bytearray()

    def start_utt_if_needed():
        nonlocal in_utt, utt_start_time
        if not in_utt:
            decoder.start_utt()
            in_utt = True
            utt_start_time = time.monotonic()

    def finalize_utt():
        nonlocal in_utt, utt_start_time
        if not in_utt:
            return
        decoder.end_utt()
        hyp = decoder.hyp()
        text = hyp.hypstr.strip() if hyp else ""
        end_time = time.monotonic()
        if text:
            emit(
                {
                    "type": "final",
                    "text": text,
                    "source": source,
                    "start_time": utt_start_time,
                    "end_time": end_time,
                }
            )
        in_utt = False
        utt_start_time = None

    try:
        while True:
            header = read_exact(stdin, 4)
            if header is None:
                break
            (length,) = struct.unpack("<I", header)
            if length == 0:
                # Explicit flush/end-of-stream marker from the Rust side.
                finalize_utt()
                continue

            payload = read_exact(stdin, length)
            if payload is None:
                break
            pending.extend(payload)

            while len(pending) >= frame_bytes:
                frame = bytes(pending[:frame_bytes])
                del pending[:frame_bytes]

                prev_in_speech = endpointer.in_speech
                speech = endpointer.process(frame)

                if speech is not None:
                    start_utt_if_needed()
                    decoder.process_raw(speech, no_search=False, full_utt=False)

                    if not endpointer.in_speech and prev_in_speech:
                        # Speech-to-silence transition: finalize this utterance.
                        finalize_utt()
                    else:
                        hyp = decoder.hyp()
                        if hyp and hyp.hypstr.strip():
                            emit(
                                {
                                    "type": "partial",
                                    "text": hyp.hypstr.strip(),
                                    "source": source,
                                }
                            )

        finalize_utt()
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
