# yapit

## Development

Set up the backend dev env:
```bash
uv sync --all-extras
echo "RUNPOD_API_KEY=asdf\nMISTRAL_API_KEY=asdf" > .env.local # env vars you do not want to commit 
```

If you want to use runpod workers, put `RUNPOD_API_KEY` in `.env.local`. Similarily with mistral OCR.
These `.env.local` entries have to exist (with any value) for the gateway to start up with the default `endpoints.dev.json` configuration.

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
make test-local  # or make test (needs runpod key)
```

### API Access

To get a bearer token for API access:
```bash
make token
```

This will authenticate the dev user (dev@example.com) and return a bearer token.

### Stack-Auth

The following admin user is created on startup:

```
username: dev@yap.it
password: yapit123
```

> **The admin user can only be used to access the stack-auth dashboard. It's not an application user**
