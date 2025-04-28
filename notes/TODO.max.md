
### Feats

- **make voices configurable for kokoro worker (add interface @ adapter)**
- write endpoints (needs: AUTH) / dymic model/worker register


### Refactor

Set up a proper project structure:
- pyproject toml with dev & test dependencies -> update ci.yml (https://docs.astral.sh/uv/guides/integration/github/ -- )
- clarify the todo in / the necessity of the docker-compose.dev.yaml

Follow fastapi best practices (https://github.com/zhanymkanov/fastapi-best-practices/blob/master/README.md):
- make better use of dependencies
- make sure async is used properly
- [use asnyc for insteadd of while True syntax](https://github.com/Kludex/fastapi-tips?tab=readme-ov-file#3-use-async-for-instead-of-while-true-on-websocket)
- NOTE: fastapi sync dependencies run in threadpool
