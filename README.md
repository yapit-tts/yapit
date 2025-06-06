# yapit

## Development

Set up the backend dev env:
```bash
uv venv .venv
source .vent/bin/activate
uv pip install ".[gateway,test]"
uv pip install pre-commit
pre-commit install
cp .env.prod.example .env.prod # .env.prod must exist, even if it's not used in dev
```

Start the backend services:
```bash
make dev-cpu  # make dev-mac if you are on mac
```

Start the frontend and login at `http://localhost/auth/signin` with the test user credentials printed by `dev-cpu`:
```bash
cd frontend && npm run dev
```

Check if everything works:
```bash
make test
```

### Stack-Auth

The following admin user is created on startup:

```
username: dev@yap.it
password: yapit123
```

> **The admin user can only be used to access the stack-auth dashboard. It's not an application user**

