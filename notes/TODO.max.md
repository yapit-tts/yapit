### Fix

- Thinking about security / exploits: Limits on the number of docs, filters, etc.
- Should Block.id be a UUID too?
- Is there a global setting for pydantic to forbid extra vals?

### Billing - Future Improvements

- Rate limiting for users with negative balance to prevent abuse

### Feats

- opus transcoding
  - depending on the intensity / scaling requirements, prlly best to do this in the gateway to save worker time?
- fun feature: show lifetime stats (words/seconds processed, etc.)
- idea: "batch jobs" (process on dedicated resources, potentially longer wait times), not just for ocr api, but for tts too. Only makes sense with generous audio retention.

### Refactor

- replace .get()+exception with get_one() and add global exception handler

- can we improve dependency handling without creating separate docker images?
  - see comments abt deps only some deployments need @ pyproject.toml
  - Search for "only needed for"   in the project.

### Perf

- For OCR: Don't download pdf from url, get page count from pdf streaming, pass url to mistral api.

### Chore

- bump python version to 3.13 everywhere (toml, gateway/cpu dockerfile) once spacy, and google-re2 support https://github.com/explosion/spaCy/issues/13658

### Notes

- if adding custom voices index on (slug, model_id, user_id) @ voice
  - think about indices @ document/user/block, filter/user if perf is bad
- (how to best?) remove runpod dep from worker images if deploying locally. Just duplicate them? build arg?

- ~~(admin) write endpoints (needs: AUTH) / dymic model/worker register~~ -> just config via env vars
