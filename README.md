# yapit

## Development

To start the backend services:
```bash
make dev-cpu  # make dev-mac if you are on mac
```
Login to the frontend with the test user credentials from `dev-cpu`, after starting it:
```bash
cd frontend && npm run dev
```

To run integration tests, .env.prod must exist, even if it's not used.
```bash
cp .env.prod.example .env.prod
make test-integration
```

Before committing, make sure pre-commit is installed:
```bash
uv venv .venv
uv pip install ".[gateway,test]"
uv pip install pre-commit
pre-commit install
```

### Stack-Auth

The following admin user is created on startup:

```
username: dev@yap.it
password: yapit123
```

> **The admin user can only be used to access the stack-auth dashboard. It's not an application user**

