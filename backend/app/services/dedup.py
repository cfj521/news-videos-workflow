import hashlib
import math
import re
import struct
from difflib import SequenceMatcher
from urllib.parse import urlparse

from app.logging import get_logger
from app.providers.base import RawArticleData

log = get_logger("service.dedup")

# ── URL normalization (Horizon style: host + path only) ──

def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = (p.hostname or "").removeprefix("www.").removeprefix("m.").lower()
        path = p.path.rstrip("/") or "/"
        return f"{host}{path}"
    except Exception:
        return url.lower().strip()


# ── Tokenization (Chinese-aware) ─────────────────────────

_NON_ALPHA = re.compile(r"\W", re.UNICODE)
_CJK_RANGE = re.compile(r"[一-鿿㐀-䶿]")

_jieba_loaded = False
_jieba = None


def _ensure_jieba():
    global _jieba_loaded, _jieba
    if _jieba_loaded:
        return _jieba
    try:
        import jieba
        jieba.setLogLevel(20)
        _jieba = jieba
    except ImportError:
        _jieba = None
    _jieba_loaded = True
    return _jieba


def _tokenize(text: str) -> list[str]:
    text = text.lower().strip()
    if not text:
        return []
    if _CJK_RANGE.search(text):
        jb = _ensure_jieba()
        if jb:
            return [t for t in jb.cut(text) if t.strip()]
        return [ch for ch in text if ch.strip()]
    return [t for t in _NON_ALPHA.split(text) if t]


def _shingles(tokens: list[str], n: int = 3) -> set[bytes]:
    if len(tokens) < n:
        if tokens:
            return {" ".join(tokens).encode("utf-8")}
        return set()
    return {" ".join(tokens[i:i + n]).encode("utf-8") for i in range(len(tokens) - n + 1)}


# ── xxhash (with fallback to hashlib) ────────────────────

try:
    import xxhash

    def _hash32(data: bytes, seed: int = 0) -> int:
        return xxhash.xxh3_64_intdigest(data, seed) & 0xFFFFFFFF
except ImportError:
    log.warning("xxhash not installed, falling back to md5 (slower). pip install xxhash")

    def _hash32(data: bytes, seed: int = 0) -> int:
        return int(struct.unpack("<I", hashlib.md5(data + seed.to_bytes(4, "little")).digest()[:4])[0])


# ── MinHash with LSH banding (text-dedup style) ─────────

_MAX_HASH = (1 << 32) - 1
_PRIME = (1 << 32) - 5


def _optimal_param(threshold: float, num_perm: int) -> tuple[int, int]:
    """Find (bands, rows) that maximizes recall at threshold, capped at rows<=3 for news dedup.
    We verify candidates with real Jaccard, so false positives from LSH are cheap."""
    best = (num_perm, 1)
    best_recall = 0.0
    for r in range(1, 4):
        b = num_perm // r
        if b < 1:
            continue
        recall_at_threshold = 1 - (1 - threshold ** r) ** b
        if recall_at_threshold > best_recall:
            best_recall = recall_at_threshold
            best = (b, r)
    return best


def _integrate(f, a: float, b: float, steps: int = 50) -> float:
    dx = (b - a) / steps
    return sum(f(a + (i + 0.5) * dx) * dx for i in range(steps))


class MinHasher:
    def __init__(self, num_perm: int = 128, threshold: float = 0.5, seed: int = 42):
        self.num_perm = num_perm
        self.threshold = threshold
        import random
        rng = random.Random(seed)
        self._a = [rng.randint(1, _PRIME - 1) for _ in range(num_perm)]
        self._b = [rng.randint(0, _PRIME - 1) for _ in range(num_perm)]
        self.bands, self.rows = _optimal_param(threshold, num_perm)
        log.debug("MinHash: num_perm=%d threshold=%.2f bands=%d rows=%d", num_perm, threshold, self.bands, self.rows)

    def signature(self, shingle_set: set[bytes]) -> list[int]:
        sig = [_MAX_HASH] * self.num_perm
        for s in shingle_set:
            h = _hash32(s)
            for i in range(self.num_perm):
                val = ((self._a[i] * h + self._b[i]) % _PRIME) & _MAX_HASH
                if val < sig[i]:
                    sig[i] = val
        return sig

    def lsh_buckets(self, sig: list[int]) -> list[tuple[int, bytes]]:
        buckets = []
        for band_idx in range(self.bands):
            start = band_idx * self.rows
            end = start + self.rows
            if end > self.num_perm:
                break
            band_hash = hashlib.md5(bytes(str(sig[start:end]), "utf-8")).digest()
            buckets.append((band_idx, band_hash))
        return buckets

    def jaccard_estimate(self, sig1: list[int], sig2: list[int]) -> float:
        return sum(1 for a, b in zip(sig1, sig2) if a == b) / self.num_perm


# ── DedupService ─────────────────────────────────────────

class DedupService:
    def __init__(self, title_threshold: float = 0.85, content_threshold: float = 0.45,
                 num_perm: int = 128, ngram_size: int = 2):
        self.title_threshold = title_threshold
        self.content_threshold = content_threshold
        self.ngram_size = ngram_size
        self._hasher = MinHasher(num_perm=num_perm, threshold=content_threshold)

    def deduplicate(self, articles: list[RawArticleData], history_fingerprints: list[str] | None = None) -> list[RawArticleData]:
        history_fps = set(history_fingerprints or [])
        seen_urls: set[str] = set()
        seen_titles: list[str] = []
        seen_fps: set[str] = set()
        result: list[RawArticleData] = []

        # LSH index: bucket -> list of (article_index, signature)
        lsh_index: dict[tuple[int, bytes], list[tuple[int, list[int]]]] = {}
        result_sigs: dict[int, list[int]] = {}

        dup_history = 0
        dup_url = 0
        dup_title = 0
        dup_content = 0

        for idx, article in enumerate(articles):
            fp = self.fingerprint(article.title)

            # Layer 1: history
            if fp in history_fps or fp in seen_fps:
                dup_history += 1
                continue

            # Layer 2: URL (host + path only)
            norm_url = _normalize_url(article.source_url)
            if norm_url and norm_url in seen_urls:
                dup_url += 1
                continue

            # Layer 3: title similarity
            if self._is_title_similar(article.title, seen_titles):
                dup_title += 1
                continue

            # Layer 4: MinHash + LSH content similarity
            if article.content and len(article.content) > 50:
                tokens = _tokenize(article.content)
                shing = _shingles(tokens, self.ngram_size)
                if shing:
                    sig = self._hasher.signature(shing)
                    if self._lsh_find_similar(sig, lsh_index, result_sigs):
                        dup_content += 1
                        continue
                    # Add to LSH index
                    for bucket_key in self._hasher.lsh_buckets(sig):
                        lsh_index.setdefault(bucket_key, []).append((idx, sig))
                    result_sigs[idx] = sig

            seen_fps.add(fp)
            if norm_url:
                seen_urls.add(norm_url)
            seen_titles.append(article.title)
            result.append(article)

        removed = dup_history + dup_url + dup_title + dup_content
        if removed:
            log.info("Dedup: %d removed (history=%d url=%d title=%d content=%d)",
                     removed, dup_history, dup_url, dup_title, dup_content)
        return result

    def _lsh_find_similar(self, sig: list[int], lsh_index: dict, result_sigs: dict) -> bool:
        """Check LSH buckets for candidate matches, verify with Jaccard."""
        candidates: set[int] = set()
        for bucket_key in self._hasher.lsh_buckets(sig):
            for other_idx, _ in lsh_index.get(bucket_key, []):
                candidates.add(other_idx)

        for other_idx in candidates:
            other_sig = result_sigs.get(other_idx)
            if other_sig and self._hasher.jaccard_estimate(sig, other_sig) >= self.content_threshold:
                return True
        return False

    def _is_title_similar(self, title: str, existing: list[str]) -> bool:
        normalized = title.lower().strip()
        for et in existing:
            if SequenceMatcher(None, normalized, et.lower().strip()).ratio() >= self.title_threshold:
                return True
        return False

    def fingerprint(self, text: str) -> str:
        return hashlib.md5(text.lower().strip().encode()).hexdigest()
