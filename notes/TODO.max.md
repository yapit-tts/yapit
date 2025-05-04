
### Fix


### Feats

- write endpoints (needs: AUTH) / dymic model/worker register


### Refactor

Follow fastapi best practices (https://github.com/zhanymkanov/fastapi-best-practices/blob/master/README.md):
- make better use of dependencies
- make sure async is used properly
- [use asnyc for insteadd of while True syntax](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#3-use-async-for-instead-of-while-true-on-websocket)
- NOTE: fastapi sync dependencies run in threadpool

### Chore

- bump python version to 3.13 everywhere (toml, .pyversion, cpu dockerfile) once spacy supports https://github.com/explosion/spaCy/issues/13658
