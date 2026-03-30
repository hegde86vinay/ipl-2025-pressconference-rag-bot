"""
Unit tests for chunker.py
Tests cover:
  1. chunk_text — correct token-window splitting with overlap
  2. make_chunk_id — deterministic, collision-resistant SHA-256 IDs
Run: pytest tests/test_chunker.py -v
"""

import sys
import os

# Allow imports from project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hashlib
import tiktoken

from chunker import chunk_text, make_chunk_id


# ─── shared encoder ───────────────────────────────────────────────────────────
enc = tiktoken.get_encoding("cl100k_base")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — chunk_text: overlapping token windows
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkText:
    """Verify that chunk_text splits text into correctly-sized, overlapping windows."""

    # Build a sample text that is clearly longer than one chunk
    SAMPLE_TEXT = " ".join([f"word{i}" for i in range(200)])  # ~200 tokens
    CHUNK_SIZE  = 50
    OVERLAP     = 10

    def test_chunk_count_is_correct(self):
        """
        Expected chunk count is derived from the actual token count so the
        test stays valid regardless of how tiktoken encodes the sample words.
          step     = CHUNK_SIZE - OVERLAP
          expected = ceil((total_tokens - CHUNK_SIZE) / step) + 1
        """
        import math
        total_tokens = len(enc.encode(self.SAMPLE_TEXT))
        step = self.CHUNK_SIZE - self.OVERLAP
        expected = math.ceil((total_tokens - self.CHUNK_SIZE) / step) + 1

        chunks = chunk_text(self.SAMPLE_TEXT, self.CHUNK_SIZE, self.OVERLAP)
        assert len(chunks) == expected, (
            f"Expected {expected} chunks for {total_tokens}-token text "
            f"with size={self.CHUNK_SIZE} overlap={self.OVERLAP}, got {len(chunks)}"
        )

    def test_each_chunk_within_token_limit(self):
        """Every chunk must be ≤ CHUNK_SIZE tokens."""
        chunks = chunk_text(self.SAMPLE_TEXT, self.CHUNK_SIZE, self.OVERLAP)
        for i, chunk in enumerate(chunks):
            token_count = len(enc.encode(chunk))
            assert token_count <= self.CHUNK_SIZE, (
                f"Chunk {i} has {token_count} tokens — exceeds limit of {self.CHUNK_SIZE}"
            )

    def test_overlap_tokens_appear_in_consecutive_chunks(self):
        """
        The last OVERLAP tokens of chunk[n] must match the first OVERLAP tokens
        of chunk[n+1], confirming the sliding window overlaps correctly.
        """
        chunks = chunk_text(self.SAMPLE_TEXT, self.CHUNK_SIZE, self.OVERLAP)
        for i in range(len(chunks) - 1):
            tail_tokens  = enc.encode(chunks[i])[-self.OVERLAP:]
            head_tokens  = enc.encode(chunks[i + 1])[:self.OVERLAP]
            assert tail_tokens == head_tokens, (
                f"Overlap mismatch between chunk {i} and chunk {i + 1}"
            )

    def test_single_chunk_for_short_text(self):
        """Text shorter than CHUNK_SIZE must produce exactly one chunk."""
        short_text = "Virat Kohli spoke about the IPL 2025 final."
        chunks = chunk_text(short_text, self.CHUNK_SIZE, self.OVERLAP)
        assert len(chunks) == 1, (
            f"Short text should produce 1 chunk, got {len(chunks)}"
        )

    def test_full_text_is_preserved_across_chunks(self):
        """
        Re-assembling chunks (de-duping the overlap) must recover the original
        token sequence — no tokens should be dropped.
        """
        chunks = chunk_text(self.SAMPLE_TEXT, self.CHUNK_SIZE, self.OVERLAP)

        # Rebuild token stream by taking non-overlapping portions of each chunk
        rebuilt_tokens = enc.encode(chunks[0])
        for chunk in chunks[1:]:
            rebuilt_tokens += enc.encode(chunk)[self.OVERLAP:]

        original_tokens = enc.encode(self.SAMPLE_TEXT)
        assert rebuilt_tokens == original_tokens, (
            "Token stream reconstructed from chunks does not match original text"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — make_chunk_id: deterministic, unique SHA-256 identifiers
# ═══════════════════════════════════════════════════════════════════════════════

class TestMakeChunkId:
    """Verify that make_chunk_id produces stable, collision-resistant 16-char IDs."""

    def test_id_length_is_16_characters(self):
        """Chunk IDs must always be exactly 16 hex characters."""
        chunk_id = make_chunk_id("https://espncricinfo.com/match/1", 0)
        assert len(chunk_id) == 16, (
            f"Expected ID of length 16, got {len(chunk_id)}: '{chunk_id}'"
        )

    def test_id_is_deterministic(self):
        """Same source_url + chunk_index must always yield the same ID."""
        url   = "https://espncricinfo.com/series/ipl-2025-1449924/match-1"
        index = 3
        id_first  = make_chunk_id(url, index)
        id_second = make_chunk_id(url, index)
        assert id_first == id_second, (
            "make_chunk_id is not deterministic — got different IDs for identical inputs"
        )

    def test_different_index_gives_different_id(self):
        """Same URL with different chunk indexes must produce different IDs."""
        url  = "https://espncricinfo.com/series/ipl-2025-1449924/match-1"
        id_0 = make_chunk_id(url, 0)
        id_1 = make_chunk_id(url, 1)
        assert id_0 != id_1, (
            "Chunk IDs for index=0 and index=1 of the same URL must differ"
        )

    def test_different_url_gives_different_id(self):
        """Different URLs with the same index must produce different IDs."""
        id_a = make_chunk_id("https://espncricinfo.com/match/rcb-vs-pbks", 0)
        id_b = make_chunk_id("https://cricbuzz.com/match/rcb-vs-pbks",    0)
        assert id_a != id_b, (
            "Chunk IDs for different URLs at the same index must differ"
        )

    def test_id_matches_expected_sha256(self):
        """
        ID must be the first 16 characters of the SHA-256 of '<url>::<index>',
        ensuring the implementation has not silently changed its hashing logic.
        """
        url   = "https://espncricinfo.com/ipl-final"
        index = 0
        raw   = f"{url}::{index}"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        assert make_chunk_id(url, index) == expected, (
            f"make_chunk_id returned unexpected hash for known input. "
            f"Expected: {expected}"
        )

    def test_id_contains_only_hex_characters(self):
        """IDs must be valid lowercase hex strings (a-f, 0-9)."""
        chunk_id = make_chunk_id("https://cricbuzz.com/some-article", 7)
        assert all(c in "0123456789abcdef" for c in chunk_id), (
            f"Chunk ID contains non-hex characters: '{chunk_id}'"
        )
