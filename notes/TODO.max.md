
### Fix

- Thinking about security / exploits: Limits on the number of docs, filters, etc. 
- Should Block.id be a UUID too?
- Is there a global setting for pydantic to forbid extra vals?

### Feats

- (admin) write endpoints (needs: AUTH) / dymic model/worker register

### Refactor


### Chore

- bump python version to 3.13 everywhere (toml, gateway/cpu dockerfile) once spacy, and google-re2 support https://github.com/explosion/spaCy/issues/13658


### Notes

- if adding custom voices index on (slug, model_id, user_id) @ voice
  - think about indices @ document/user/block, filter/user  if perf is bad
