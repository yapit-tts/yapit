
### Fix

- Thinking about security / exploits: Limits on the number of docs, filters, etc. 
- Should Block.id be a UUID too?

### Feats

- (admin) write endpoints (needs: AUTH) / dymic model/worker register


### Refactor

Follow fastapi best practices (https://github.com/zhanymkanov/fastapi-best-practices/blob/master/README.md):
- [use asnyc for insteadd of while True syntax](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#3-use-async-for-instead-of-while-true-on-websocket)
- NOTE: fastapi sync dependencies run in threadpool

- If I'm already changing document_id to doc_id, at least pull through with it and also change in db to be consistent.

### Chore

- bump python version to 3.13 everywhere (toml, .pyversion, cpu dockerfile) once spacy supports https://github.com/explosion/spaCy/issues/13658
