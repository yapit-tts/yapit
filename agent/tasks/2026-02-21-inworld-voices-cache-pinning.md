---
status: done
refs:
  - "[[inworld-tts]]"
  - "[[frontend]]"
---

# Add missing Inworld voices, pin showcase cache, voice picker search

## Intent

We're missing 48 English voices from the Inworld TTS v1 API. Adding them means the voice picker needs search (73 EN voices in a flat list is unusable), and the cache warming system needs rethinking — the daily systemd timer is a smell that adds unnecessary API load, distorts metrics, and fights LRU eviction.

The fix: pin showcase audio in the cache so it's never evicted, warm once (or on voice addition), kill the daily timer.

## Scope

Three coupled changes in one PR:

### 1. Add 48 missing Inworld voices

Update `yapit/data/inworld/voices.json` with all voices from `GET /tts/v1/voices`.

Missing voices (all EN, 48 total): Abby, Amina, Anjali, Arjun, Brian, Callum, Celeste, Chloe, Claire, Darlene, Derek, Elliot, Ethan, Evan, Evelyn, Gareth, Graham, Grant, Hamish, Hank, Jake, James, Jason, Jessica, Kayla, Kelsey, Lauren, Liam, Loretta, Malcolm, Marlene, Miranda, Mortimer, Nate, Oliver, Pippa, Rupert, Saanvi, Sebastian, Serena, Simon, Snik, Tessa, Tyler, Veronica, Victor, Victoria, Vinny.

Prod: direct SQL INSERT for new Voice rows (data, not schema — not an Alembic migration). Seed script updated for future deployments / self-host / dev.

### 2. Cache pinning — replace daily warming

Add `pinned` column to SQLite cache. Pinned entries are exempt from LRU eviction.

- `ALTER TABLE cache ADD COLUMN pinned INTEGER DEFAULT 0`
- `_enforce_max_size` skips `WHERE pinned=0`
- Warming script sets `pinned=1` on store
- Retroactive pinning: recompute hashes for existing showcase entries, bulk UPDATE
- Remove daily systemd timer — warming becomes a one-shot on voice/showcase changes

### 3. Voice picker search bar

Text filter at the top of the Inworld voice picker tab. Matches against voice name + description. Simple substring/includes match — no fuzzy needed. User searches "calm", "australian", "villain", finds what they want.

## Assumptions

- The Inworld synthesis API (`POST /tts/v1/voice:stream`) and the voices themselves are NOT deprecated — only the listing endpoint is (July 2026). The voices will keep working.
- The voice list from the v1 API is the canonical source. No v1alpha voices (those are the old Inworld Studio game character voices, different product).
- 73 English voices with search + star/pin is fine UX. No subcategories needed.
- Warming budget: ~$7 one-time for Attention paper × 48 new voices on inworld-1.5 only. inworld-1.5-max warming for showcase docs deferred until revenue justifies it.

## Done When

- voices.json has all 113 voices from Inworld v1 API
- Voice picker has working search (name + description) in the Inworld tab
- SQLite cache supports pinned entries, LRU eviction skips them
- Warming script pins entries on store
- Existing showcase cache entries are retroactively pinned
- Daily warming systemd timer removed
- One-time warm executed for new voices (inworld-1.5 only for Attention paper)
