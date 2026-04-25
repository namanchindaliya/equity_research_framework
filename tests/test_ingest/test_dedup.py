"""Tests for dedup.py: content hashing and index management."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from equity_os.ingest.dedup import (
    content_hash,
    is_duplicate,
    lookup,
    register,
)


class TestContentHash:
    def test_returns_64_char_hex(self):
        h = content_hash("hello")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert content_hash("apple") == content_hash("apple")

    def test_different_text_different_hash(self):
        assert content_hash("apple") != content_hash("apple ")

    def test_empty_string(self):
        h = content_hash("")
        assert len(h) == 64


class TestRegisterAndLookup:
    def test_lookup_after_register(self, tmp_path: Path):
        eid = uuid4()
        register(tmp_path, "abc123", eid, "inputs/AAPL/doc.txt")
        found = lookup(tmp_path, "abc123")
        assert found == str(eid)

    def test_lookup_missing_hash_returns_none(self, tmp_path: Path):
        assert lookup(tmp_path, "doesnotexist") is None

    def test_lookup_nonexistent_dir_returns_none(self, tmp_path: Path):
        assert lookup(tmp_path / "nodir", "anyhash") is None

    def test_multiple_registers_accumulate(self, tmp_path: Path):
        e1, e2 = uuid4(), uuid4()
        register(tmp_path, "hash1", e1, "f1.txt")
        register(tmp_path, "hash2", e2, "f2.txt")
        assert lookup(tmp_path, "hash1") == str(e1)
        assert lookup(tmp_path, "hash2") == str(e2)

    def test_first_match_wins_on_duplicate_hash(self, tmp_path: Path):
        e1, e2 = uuid4(), uuid4()
        register(tmp_path, "samehash", e1, "f1.txt")
        register(tmp_path, "samehash", e2, "f2.txt")
        assert lookup(tmp_path, "samehash") == str(e1)  # first wins

    def test_creates_directory_if_needed(self, tmp_path: Path):
        new_dir = tmp_path / "nested" / "dir"
        register(new_dir, "h", uuid4(), "f.txt")
        assert new_dir.is_dir()

    def test_index_file_is_jsonl(self, tmp_path: Path):
        register(tmp_path, "h1", uuid4(), "f.txt")
        index = tmp_path / "_index.jsonl"
        assert index.exists()
        lines = [l for l in index.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        import json
        rec = json.loads(lines[0])
        assert "content_hash" in rec
        assert "evidence_id" in rec


class TestIsDuplicate:
    def test_new_text_not_duplicate(self, tmp_path: Path):
        is_dup, h = is_duplicate(tmp_path, "unique text document content")
        assert not is_dup
        assert len(h) == 64

    def test_registered_text_is_duplicate(self, tmp_path: Path):
        text = "this is a document"
        h = content_hash(text)
        register(tmp_path, h, uuid4(), "f.txt")
        is_dup, returned_hash = is_duplicate(tmp_path, text)
        assert is_dup
        assert returned_hash == h

    def test_different_text_not_duplicate(self, tmp_path: Path):
        text1 = "document one"
        text2 = "document two"
        h1 = content_hash(text1)
        register(tmp_path, h1, uuid4(), "f1.txt")
        is_dup, _ = is_duplicate(tmp_path, text2)
        assert not is_dup
