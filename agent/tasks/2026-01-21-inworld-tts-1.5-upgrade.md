---
status: done
started: 2026-01-21
completed: 2026-01-24
---

# Task: Inworld TTS-1.5 Upgrade

Upgrade from Inworld TTS-1 to TTS-1.5 models. Change slugs to invalidate cache.

## Intent

Replace TTS-1 with TTS-1.5:
- `inworld` → `inworld-1.5` (TTS-1.5-Mini, $5/1M chars, ~120ms P50)
- `inworld-max` → `inworld-1.5-max` (TTS-1.5-Max, $10/1M chars, ~200ms P50)

Benefits: 4x faster latency, 40% lower WER, 30% more expressive, Hindi support (15 languages total).

Changing slugs ensures `variant_hash` changes → cache invalidation → users get new model quality immediately.

## Sources

**MUST READ:**
- [TTS-1.5 docs](https://docs.inworld.ai/docs/tts/tts) — model overview
- [Generating Audio docs](https://docs.inworld.ai/docs/tts/capabilities/generating-audio) — API parameters

**Related tasks (separate implementations):**
- [[2026-01-18-inworld-temperature-setting]] — temperature slider
- [[2026-01-12-audio-cache-opus-compression]] — Opus codec

## Implementation Dry-Run

### Backend

**`yapit/gateway/__init__.py:165`** — API model IDs + our slugs:
```python
# OLD
for model_id, model_slug in [("inworld-tts-1", "inworld"), ("inworld-tts-1-max", "inworld-max")]:

# NEW (note: dots in 1.5, not dashes!)
for model_id, model_slug in [("inworld-tts-1.5-mini", "inworld-1.5"), ("inworld-tts-1.5-max", "inworld-1.5-max")]:
```

**`yapit/gateway/seed.py:96-139`** — model definitions:
```python
# Lines 97-104: inworld model
slug="inworld"        → slug="inworld-1.5"
name="Inworld TTS-1"  → name="Inworld TTS-1.5"

# Lines 107-115: inworld_max model
slug="inworld-max"        → slug="inworld-1.5-max"
name="Inworld TTS-1-Max"  → name="Inworld TTS-1.5-Max"
```

**`yapit/workers/adapters/inworld.py`** — no changes (takes model_id as param)

**`tests/integration/test_tts.py:12`** — test fixture:
```python
pytest.param("inworld", "ashley", ...)  → pytest.param("inworld-1.5", "ashley", ...)
```

**`dashboard/theme.py:38-39,62`** — color mappings:
```python
"inworld-max": "#58a6ff"  → "inworld-1.5-max": "#58a6ff"
"inworld": "#ff7b72"      → "inworld-1.5": "#ff7b72"
# Also update line 62 list
```

### Frontend

**`frontend/src/lib/voiceSelection.ts`**

Line 3 — ModelType enum:
```typescript
// OLD
export type ModelType = "kokoro" | "kokoro-server" | "higgs" | "inworld" | "inworld-max";

// NEW
export type ModelType = "kokoro" | "kokoro-server" | "higgs" | "inworld-1.5" | "inworld-1.5-max";
```

Lines 7, 15-18 — getBackendModelSlug():
```typescript
// OLD
case "inworld":
  return "inworld";
case "inworld-max":
  return "inworld-max";

// NEW
case "inworld-1.5":
  return "inworld-1.5";
case "inworld-1.5-max":
  return "inworld-1.5-max";
```

Line 24 — isServerSideModel():
```typescript
// OLD
return model === "higgs" || model === "kokoro-server" || model === "inworld" || model === "inworld-max";

// NEW
return model === "higgs" || model === "kokoro-server" || model === "inworld-1.5" || model === "inworld-1.5-max";
```

**`frontend/src/hooks/useInworldVoices.ts:54`** — API fetch slug:
```typescript
fetchPromise = fetchVoices("inworld");  → fetchPromise = fetchVoices("inworld-1.5");
```

**`frontend/src/components/voicePicker.tsx`**

Lines 89-91, 98-99, 121-123, 165 — model checks (use find/replace):
```typescript
"inworld"      → "inworld-1.5"
"inworld-max"  → "inworld-1.5-max"
```

Lines 372, 383, 391 — UI labels:
```typescript
"TTS-1-Max uses a larger model..."  → "TTS-1.5-Max uses a larger model..."
"TTS-1"     → "TTS-1.5"
"TTS-1-Max" → "TTS-1.5-Max"
```

**`frontend/src/components/soundControl.tsx:510`**:
```typescript
// OLD
const isUsingInworld = voiceSelection.model === "inworld" || voiceSelection.model === "inworld-max";

// NEW
const isUsingInworld = voiceSelection.model === "inworld-1.5" || voiceSelection.model === "inworld-1.5-max";
```

**`frontend/src/pages/SubscriptionPage.tsx:463`**:
```typescript
"TTS-1-Max uses 2× quota"  → "TTS-1.5-Max uses 2× quota"
```

**`frontend/src/hooks/useSubscription.tsx`** — no changes needed (just uses `canUseInworld` boolean)

### Production Database

Direct SQL — slugs are unique, so UPDATE in place. BlockVariant.model_id is integer FK to ttsmodel.id, not slug — no FK breakage.

```sql
-- Update slugs and names
UPDATE ttsmodel SET slug = 'inworld-1.5', name = 'Inworld TTS-1.5' WHERE slug = 'inworld';
UPDATE ttsmodel SET slug = 'inworld-1.5-max', name = 'Inworld TTS-1.5-Max' WHERE slug = 'inworld-max';

-- Voice slugs unchanged, but they reference model by model_id (integer), so no update needed
```

Old BlockVariant rows have hashes computed with old slugs — they become orphaned (never matched), effectively invalidating cache.

### User localStorage

Users with old slugs in localStorage fall back to default (kokoro) and re-select Inworld manually. One-time inconvenience, no migration code needed.

## Deployment Order

1. Deploy backend first (new slugs in DB + gateway)
2. Deploy frontend (new slugs in code)
3. Old frontend talking to new backend: API calls to `/v1/models/inworld/voices` would 404, but voices are cached client-side and synthesis uses WebSocket with model slug from frontend — brief window of issues
4. Alternative: Deploy simultaneously or backend-then-frontend within minutes

## Done When

- [x] Backend: gateway model IDs + slugs
- [x] Backend: seed.py slugs + names
- [x] Backend: test fixture slug
- [x] Backend: dashboard theme colors
- [x] Frontend: voiceSelection.ts (ModelType, getBackendModelSlug, isServerSideModel)
- [x] Frontend: useInworldVoices.ts fetch slug
- [x] Frontend: voicePicker.tsx model checks + labels
- [x] Frontend: soundControl.tsx model check
- [x] Frontend: SubscriptionPage.tsx label
- [x] Production DB: UPDATE slugs and names
- [x] Test locally end-to-end
- [x] Deploy and verify

**Also done:**
- Added 5 new voices (Manoj/Hindi, Nour+Omar/Arabic, Oren+Yael/Hebrew)
- Added Arabic and Hebrew language support to frontend
- Refactored: `INWORLD_SLUG`/`INWORLD_MAX_SLUG` constants + `isInworldModel()` helper
- Removed deprecated HIGGS model support entirely
