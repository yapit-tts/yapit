

### Fix

- Tune runpod worker idle timeout (maybe 2min or even 3min is good to avoid cold starts for infrquent use + our pre-fetching pattern+block duration...)
  - (needs refinement to be useful for proper analysis) Break even / visualization for tuning params: https://claude.ai/public/artifacts/aaba7fde-3307-4fc0-857e-a50681ce22ac | chat: https://claude.ai/chat/e6250ab2-36fe-4520-9486-09741c99c528
  - => CREATE A SEPARATE ENDPOINT FOR CI (with 0 idle timeout)
  - => vllm only makes sense with acive workers / regular traffic with decent idle timeout
- Upload size restrictions for upload endpoint
- Mistral: Dont assume pages are returned in order, sort them by explicitly returned page number before returning
- Thinking about security / exploits: Limits on the number of docs, filters, etc.
- Should Block.id be a UUID too?
- Is there a global setting for pydantic to forbid extra vals?

### Billing - Future Improvements

- Rate limiting for users with negative balance to prevent abuse

### Feats

- deploy a non-vllm version of the higgs worker as a baseline / comparison
- opus transcoding
  - depending on the intensity / scaling requirements, prlly best to do this in the gateway to save worker time?
- Custom voice creation
  - needs to be model specific...
  - higgs has prompts (essential feature)
  - kokoro can mix existing voices (low low prio)
  - easy import / export of custom voices, and/or some way to share them
- idea: "batch jobs" (process on dedicated resources, potentially longer wait times), not just for ocr api, but for tts too. Only makes sense with generous audio retention.
- fun feature: show lifetime stats (words/seconds processed, etc.)
  - voice usage (self)
  - voice usage (all, public voices)
- Measure how often the block variant merge case is actually hit

### Refactor

- configure runpod endpoitns via code

- can we improve dependency handling without creating separate docker images?
  - see comments abt deps only some deployments need @ pyproject.toml
  - Search for "only needed for"   in the project.

### Chore

- bump python version to 3.13 everywhere (toml, gateway/cpu dockerfile) once spacy, and google-re2 support https://github.com/explosion/spaCy/issues/13658

### Notes / Open Questions

- for higgs we might need to always use reference voices, or send previous chunks of text and audio as context...
- if adding custom voices index on (slug, model_id, user_id) @ voice
  - think about indices @ document/user/block, filter/user if perf is bad
- (how to best?) remove runpod dep from worker images if deploying locally. Just duplicate them? build arg?

- ~~(admin) write endpoints (needs: AUTH) / dymic model/worker register~~ -> just config via env vars
