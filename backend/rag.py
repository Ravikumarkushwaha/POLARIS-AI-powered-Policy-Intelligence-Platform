from __future__ import annotations

import re
from dataclasses import dataclass


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]{2,}")
_STOP_WORDS = {
    "about", "after", "along", "also", "among", "been", "being", "could", "from",
    "have", "into", "more", "policy", "should", "that", "their", "there", "these",
    "they", "this", "those", "will", "with", "would", "within", "your",
}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str


def compact_text(text: str, max_characters: int = 6000) -> str:
    """Keep prompts below provider limits while retaining document beginning and ending."""
    if len(text) <= max_characters:
        return text
    marker = "\n\n[...middle of document omitted...]\n\n"
    available = max(0, max_characters - len(marker))
    head_size = available * 3 // 4
    tail_size = available - head_size
    return f"{text[:head_size]}{marker}{text[-tail_size:] if tail_size else ''}"


def compact_policy_text(text: str, max_characters: int = 6000, segments: int = 6) -> str:
    """Sample a long policy across its full length for representative parsing."""
    if len(text) <= max_characters:
        return text
    segments = max(2, segments)
    labels = [f"\n[Policy excerpt {index + 1}/{segments}]\n" for index in range(segments)]
    available = max_characters - sum(len(label) for label in labels)
    excerpt_size = max(100, available // segments)
    last_start = max(0, len(text) - excerpt_size)
    starts = [round(index * last_start / (segments - 1)) for index in range(segments)]
    return "".join(
        f"{label}{text[start:start + excerpt_size]}"
        for label, start in zip(labels, starts)
    )[:max_characters]


def _terms(value: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(value) if word.lower() not in _STOP_WORDS}


def chunk_document(text: str, *, words_per_chunk: int = 180, overlap: int = 35) -> list[Chunk]:
    words = text.split()
    if not words:
        return []
    step = max(1, words_per_chunk - overlap)
    chunks: list[Chunk] = []
    for start in range(0, len(words), step):
        chunk_words = words[start : start + words_per_chunk]
        if not chunk_words:
            break
        chunks.append(Chunk(f"policy-{len(chunks) + 1:03d}", " ".join(chunk_words)))
        if start + words_per_chunk >= len(words):
            break
    return chunks


def retrieve_chunks(text: str, query: str, *, top_k: int = 5) -> list[dict[str, str | float]]:
    chunks = chunk_document(text)
    query_terms = _terms(query)
    scored: list[tuple[float, int, Chunk]] = []
    for index, chunk in enumerate(chunks):
        chunk_terms = _terms(chunk.text)
        overlap = len(query_terms & chunk_terms)
        score = overlap / max(1, len(query_terms))
        scored.append((score, index, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = scored[:top_k]
    return [
        {"chunk_id": chunk.chunk_id, "text": chunk.text, "relevance": round(score, 4)}
        for score, _index, chunk in selected
    ]
