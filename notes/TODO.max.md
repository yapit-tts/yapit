

### Fix

- Thinking about security / exploits: Limits on the number of docs, filters, etc.
- Should Block.id be a UUID too?
- Is there a global setting for pydantic to forbid extra vals?

### Billing - Future Improvements

- Rate limiting for users with negative balance to prevent abuse

### Feats

- if a document processor does not support a format, it should just be converted to pdf via pandoc or converted to markdown (e.g. for things like epub, so we can directly move to text extraction... if the user wants to use ocr on their epub, they can convert it to pdf first... but who would like to pay for just having the images also displayed. i think it's reasonable to ask them to convert it to pdf in that case.)

- opus transcoding
  - depending on the intensity / scaling requirements, prlly best to do this in the gateway to save worker time?
- fun feature: show lifetime stats (words/seconds processed, etc.)
- idea: "batch jobs" (process on dedicated resources, potentially longer wait times), not just for ocr api, but for tts too. Only makes sense with generous audio retention.

### Refactor

- replace .get()+exception with get_one() and add global exception handler
- replace generic value errors with custom exceptions (in proper format...), , add appropriate error hanlers, (document responses in routes?)

- can we improve dependency handling without creating separate docker images?
  - see comments abt deps only some deployments need @ pyproject.toml
  - Search for "only needed for"   in the project.

### Chore

- bump python version to 3.13 everywhere (toml, gateway/cpu dockerfile) once spacy, and google-re2 support https://github.com/explosion/spaCy/issues/13658

### Notes

- if adding custom voices index on (slug, model_id, user_id) @ voice
  - think about indices @ document/user/block, filter/user if perf is bad
- (how to best?) remove runpod dep from worker images if deploying locally. Just duplicate them? build arg?

- ~~(admin) write endpoints (needs: AUTH) / dymic model/worker register~~ -> just config via env vars
