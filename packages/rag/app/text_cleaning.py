"""Text cleaning for extracted document content.

Deliberately conservative: this only normalizes whitespace and obvious
extraction artifacts. It must never mangle technical tokens like "C++", "C#",
".NET", or "AWS Lambda" — see the regression tests in tests/test_text_cleaning.py
for the exact cases this guards against.
"""

from __future__ import annotations

import re

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_WHITESPACE = re.compile(r"[ \t]+\n")
_MULTI_SPACES = re.compile(r"[ \t]{2,}")
# A line ending mid-sentence (lowercase letter, no terminal punctuation)
# immediately followed by a line starting with a lowercase letter is very likely
# a PDF-extraction line-wrap artifact, not an intentional paragraph break.
_BROKEN_WRAP = re.compile(r"(?<=[a-z,])\n(?=[a-z])")


def clean_text(raw: str) -> str:
    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Join lines that were clearly wrapped mid-sentence by the source PDF/DOCX
    # renderer, before collapsing other whitespace.
    text = _BROKEN_WRAP.sub(" ", text)

    text = _TRAILING_WHITESPACE.sub("\n", text)
    text = _MULTI_SPACES.sub(" ", text)
    text = _MULTI_BLANK_LINES.sub("\n\n", text)

    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()
