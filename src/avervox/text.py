"""Sentence splitting shared by the LLM stream and the speech pipeline.

Both need the same notion of "a chunk worth speaking": the LLM stream splits
tokens as they arrive so playback can start before the reply is finished, and
the bridge daemon splits a finished reply so it can stream audio back frame by
frame. One definition, so the two never drift.
"""

from __future__ import annotations

import re
from typing import Generator, Iterable

# Deliberately coarse. TTS sounds better on short utterances, so breaking at a
# colon or semicolon is wanted here even though a grammarian would not.
SENTENCE_END = re.compile(r'[.!?:;]\s')


def split_sentences(text: str) -> list[str]:
    """Break finished text into speakable chunks."""
    return list(iter_sentences([text]))


def iter_sentences(tokens: Iterable[str]) -> Generator[str, None, None]:
    """Yield each sentence as soon as the tokens forming it have arrived."""
    buffer = ""
    for token in tokens:
        buffer += token
        while True:
            match = SENTENCE_END.search(buffer)
            if not match:
                break
            sentence = buffer[: match.end()].strip()
            buffer = buffer[match.end():]
            if sentence:
                yield sentence
    tail = buffer.strip()
    if tail:
        yield tail
