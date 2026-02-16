---
status: done
started: 2026-01-23
---

**Resolution:** Moved to R2 for cloud; local/self-host path skipped (won't reach scale where sharding matters).

# Task: Image Directory Sharding + Extraction Cache Compression

## Intent

Two infrastructure improvements for scale:

1. **Image directory sharding**: Prevent filesystem performance degradation as image count grows. At 10K MAU with ~10 docs/user/month, we'd have ~1M document directories within a year.

2. **Extraction cache compression**: Add gzip to extraction cache entries. Markdown compresses ~10:1, significantly reducing disk usage and I/O.

## Assumptions

- ext4 filesystem (standard for Linux VPS)
- Current image count is small enough that migration is quick
- Extraction cache uses SQLite (keeping SQLite, just adding compression)
- No need for backwards compatibility — can migrate all existing data

## Sources

**Key code files:**
- MUST READ: `yapit/gateway/document/extraction.py` — `store_image()`, `store_figure()`
- MUST READ: `yapit/gateway/api/v1/images.py` — image serving endpoint
- MUST READ: `yapit/gateway/api/v1/documents.py` — image cleanup on delete
- MUST READ: `yapit/gateway/cache.py` — SqliteCache implementation
- MUST READ: `yapit/gateway/document/processing.py` — extraction cache usage

**Knowledge files:**
- [[document-processing]] — image storage context

## Design

### Image Directory Sharding

**Current structure:**
```
images_dir/
  {content_hash}/
    0_0.png
    0_1.png
    ...
```

**New structure:**
```
images_dir/
  {hash[0:2]}/
    {hash[2:4]}/
      {content_hash}/
        0_0.png
        0_1.png
        ...
```

This limits directories per level to 256 (hex 00-ff), scaling to billions of documents without performance issues.

**Changes needed:**

1. `store_image()` and `store_figure()` in `extraction.py`:
   ```python
   def _get_image_dir(images_dir: Path, content_hash: str) -> Path:
       return images_dir / content_hash[:2] / content_hash[2:4] / content_hash
   ```

2. Image serving in `images.py`:
   ```python
   file_path = images_dir / doc_hash[:2] / doc_hash[2:4] / doc_hash / filename
   ```

3. Cleanup in `documents.py`:
   ```python
   images_path = images_dir / content_hash[:2] / content_hash[2:4] / content_hash
   ```

4. Migration script for existing images:
   ```python
   for old_dir in images_dir.iterdir():
       if old_dir.is_dir() and len(old_dir.name) == 64:  # SHA256 hash
           new_dir = images_dir / old_dir.name[:2] / old_dir.name[2:4] / old_dir.name
           new_dir.parent.mkdir(parents=True, exist_ok=True)
           old_dir.rename(new_dir)
   ```

### Extraction Cache Compression

Add gzip compression to SqliteCache for extraction entries.

**Option A: Transparent compression in SqliteCache**

Add compression flag to cache config:
```python
class CacheConfig(BaseModel):
    path: Path | str | None = None
    max_size_mb: int | None = None
    compress: bool = False  # New field
```

Modify store/retrieve:
```python
async def store(self, key: str, data: bytes) -> str | None:
    if self.config.compress:
        data = gzip.compress(data)
    # ... existing logic

async def retrieve_data(self, key: str) -> bytes | None:
    # ... existing logic
    if row and self.config.compress:
        return gzip.decompress(row[0])
    return row[0] if row else None
```

**Option B: Compress at call site**

Leave SqliteCache unchanged, compress in processing.py:
```python
await cache.store(key, gzip.compress(markdown.encode()))
markdown = gzip.decompress(await cache.retrieve_data(key)).decode()
```

**Recommendation**: Option A (transparent compression). Cleaner API, compression logic in one place.

**Migration**: No migration needed. New entries are compressed, old entries can be detected by trying to decompress (gzip has magic bytes `1f 8b`). Or just let old entries expire naturally.

### Size Tracking

With compression, the `size` column in cache table should store compressed size (what's actually on disk), not original size. This is already correct if we compress before storing.

## Done When

- [ ] Image directories use `{hash[:2]}/{hash[2:4]}/{hash}/` structure
- [ ] Existing images migrated to new structure
- [ ] Image serving works with new paths
- [ ] Image cleanup on document delete works with new paths
- [ ] Extraction cache entries are gzip compressed
- [ ] Cache size limits account for compressed sizes
- [ ] Tests pass

## Considered & Rejected

**Filesystem-based extraction cache**: Benchmarked — SQLite is faster for small values (5-20μs vs 50-100μs per read) due to directory lookup overhead and syscall batching. Keeping SQLite.

**3-level sharding**: `{hash[:2]}/{hash[2:4]}/{hash[4:6]}/` — overkill. 2 levels gives 65K buckets, sufficient for billions of documents.

**Compress audio cache**: Audio is already opus-encoded (compressed). Gzip on compressed audio = ~0% savings + wasted CPU.

## Discussion

- Compression ratio for markdown: ~10:1. A 20KB page becomes ~2KB.
- Sharding overhead: Two extra directory lookups per image access. Negligible compared to file read.
- Migration can run while service is live — new structure is backwards compatible during transition (just check both paths in image serving temporarily).
