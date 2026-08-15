"""Word error rate and the accuracy breakdown the report needs.

Normalization is aggressive and applied identically to reference and
hypothesis: lowercase, strip punctuation, collapse whitespace, and map spelled
digits. This matters because the candidates disagree about surface form —
Parakeet emits "Can you explain the RAG architecture?" with punctuation and
casing, while the LibriSpeech-trained Zipformer emits "CAN YOU EXPLAIN THE RAG
ARCHITECTURE". Scoring raw strings would rank engines by their formatting
conventions instead of by what they heard.

The alignment is standard Levenshtein over word tokens with unit costs, which
is the definition WER is conventionally reported against.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_PUNCT = re.compile(r"[^\w\s']")
_WS = re.compile(r"\s+")

#: Engines differ on numerals vs words; neither is an error for our purposes.
_NUMBER_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
    "10": "ten",
}


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("-", " ")
    text = _PUNCT.sub(" ", text)
    text = _WS.sub(" ", text).strip()
    if not text:
        return []
    return [_NUMBER_WORDS.get(tok, tok) for tok in text.split(" ")]


@dataclass(frozen=True)
class WerResult:
    reference: str
    hypothesis: str
    ref_words: int
    hits: int
    substitutions: int
    deletions: int
    insertions: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def wer(self) -> float:
        """Errors per reference word. Can exceed 1.0 when an engine inserts
        heavily (which PocketSphinx does, so the metric must allow it)."""
        if self.ref_words == 0:
            return 0.0 if self.errors == 0 else 1.0
        return self.errors / self.ref_words

    @property
    def accuracy(self) -> float:
        """1 - WER, floored at 0 so a catastrophic hypothesis reads as 0%
        rather than a confusing negative number."""
        return max(0.0, 1.0 - self.wer)

    @property
    def completeness(self) -> float:
        """Share of reference words the engine got right — ignores insertions.
        Answers 'how much of the sentence survived', which is what determines
        whether a question is still understandable."""
        if self.ref_words == 0:
            return 1.0
        return self.hits / self.ref_words


def score(reference: str, hypothesis: str) -> WerResult:
    ref = normalize(reference)
    hyp = normalize(hypothesis)

    n, m = len(ref), len(hyp)
    # dist[i][j] plus the operation counts that produced it. Full matrix is
    # fine here: sentences are tens of words, not thousands.
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    ops = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]  # (hit, sub, del, ins)

    for i in range(1, n + 1):
        dist[i][0] = i
        ops[i][0] = (0, 0, i, 0)
    for j in range(1, m + 1):
        dist[0][j] = j
        ops[0][j] = (0, 0, 0, j)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dist[i][j] = dist[i - 1][j - 1]
                h, s, d, ins = ops[i - 1][j - 1]
                ops[i][j] = (h + 1, s, d, ins)
                continue

            sub = dist[i - 1][j - 1] + 1
            dele = dist[i - 1][j] + 1
            ins_ = dist[i][j - 1] + 1
            best = min(sub, dele, ins_)
            dist[i][j] = best
            if best == sub:
                h, s, d, ins = ops[i - 1][j - 1]
                ops[i][j] = (h, s + 1, d, ins)
            elif best == dele:
                h, s, d, ins = ops[i - 1][j]
                ops[i][j] = (h, s, d + 1, ins)
            else:
                h, s, d, ins = ops[i][j - 1]
                ops[i][j] = (h, s, d, ins + 1)

    hits, subs, dels, inss = ops[n][m]
    return WerResult(
        reference=reference,
        hypothesis=hypothesis,
        ref_words=n,
        hits=hits,
        substitutions=subs,
        deletions=dels,
        insertions=inss,
    )


def term_recall(reference: str, hypothesis: str, terms: tuple[str, ...]) -> tuple[int, int, list[str]]:
    """Checks which domain terms present in the reference survived into the
    hypothesis. Returns `(found, expected, missed)`.

    Reported separately from WER because these words carry the meaning: an
    engine that drops "RAG" and "semantic" but nails every filler word has a
    respectable WER and is still useless for a technical interview.
    """
    ref = normalize(reference)
    hyp = set(normalize(hypothesis))
    expected = [t for t in terms if t in ref]
    missed = [t for t in expected if t not in hyp]
    return len(expected) - len(missed), len(expected), missed
