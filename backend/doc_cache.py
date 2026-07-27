# backend/doc_cache.py
#
# Persistent, content-hash-keyed cache for the upload → parse → ingest pipeline.
#
# Problem this solves:
#   /api/upload always re-runs parse_file() on the raw bytes, and
#   /api/generate + /api/generate/ai always re-run ingest_document() on the
#   extracted text — even if the exact same file was already processed in an
#   earlier session (or an earlier run of the app, since `sessions` is
#   in-memory only and is wiped on restart).
#
# Fix:
#   - Hash the raw uploaded bytes (SHA-256) -> cache the parsed text.
#   - Hash the parsed text + chunking params -> cache the ingested chunks.
#   - Both caches are plain JSON files on disk under backend/.cache/, so they
#     survive process restarts. No DB dependency needed at this scale.
#
# Cache invalidation:
#   The chunk cache key includes CACHE_FORMAT_VERSION. Bump this constant any
#   time ingest_document()'s logic or CHUNK_SIZE_WORDS changes in a way that
#   should invalidate previously-cached chunks.

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import List, Optional

from models import DocumentChunk

# Bump this whenever ingestion logic changes in a way that should invalidate
# previously-cached chunks (e.g. new requirement-ID regex, new module rules).
CACHE_FORMAT_VERSION = "v1"

_CACHE_DIR   = Path(__file__).resolve().parent / ".cache"
_TEXT_DIR    = _CACHE_DIR / "text"      # raw-file-hash -> parsed text
_CHUNKS_DIR  = _CACHE_DIR / "chunks"    # text-hash+params -> ingested chunks

_TEXT_DIR.mkdir(parents=True, exist_ok=True)
_CHUNKS_DIR.mkdir(parents=True, exist_ok=True)


def hash_bytes(raw: bytes) -> str:
    """Content hash of raw uploaded file bytes."""
    return hashlib.sha256(raw).hexdigest()


def hash_text(text: str) -> str:
    """Content hash of extracted/parsed text (used as the ingestion cache key)."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _chunk_cache_key(text_hash: str, chunk_size_words: int) -> str:
    return f"{text_hash}_{chunk_size_words}_{CACHE_FORMAT_VERSION}"


# ── Parsed-text cache (skips file_parser.parse_file re-parsing) ─────────────

def get_cached_text(file_hash: str) -> Optional[str]:
    path = _TEXT_DIR / f"{file_hash}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("text")
    except Exception:
        return None  # corrupt cache entry — treat as a miss, caller will reparse


def set_cached_text(file_hash: str, filename: str, text: str) -> None:
    path = _TEXT_DIR / f"{file_hash}.json"
    try:
        path.write_text(
            json.dumps({"filename": filename, "text": text}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # caching is best-effort; never block the upload on a disk error


# ── Ingested-chunk cache (skips document_ingestion.ingest_document re-run) ──

def get_cached_chunks(text_hash: str, chunk_size_words: int) -> Optional[List[DocumentChunk]]:
    key  = _chunk_cache_key(text_hash, chunk_size_words)
    path = _CHUNKS_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [DocumentChunk.model_validate(c) for c in raw]
    except Exception:
        return None  # corrupt/stale cache entry — treat as a miss


def set_cached_chunks(text_hash: str, chunk_size_words: int, chunks: List[DocumentChunk]) -> None:
    key  = _chunk_cache_key(text_hash, chunk_size_words)
    path = _CHUNKS_DIR / f"{key}.json"
    try:
        path.write_text(
            json.dumps([c.model_dump() for c in chunks], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def cache_stats() -> dict:
    """Quick visibility into cache size — handy for a debug endpoint."""
    return {
        "cached_documents": len(list(_TEXT_DIR.glob("*.json"))),
        "cached_chunk_sets": len(list(_CHUNKS_DIR.glob("*.json"))),
        "cache_dir": str(_CACHE_DIR),
    }


def clear_cache() -> None:
    """Wipe both caches — useful after a genuine ingestion-logic change if you
    forgot to bump CACHE_FORMAT_VERSION, or for a manual reset."""
    for d in (_TEXT_DIR, _CHUNKS_DIR):
        for f in d.glob("*.json"):
            try:
                f.unlink()
            except Exception:
                pass
