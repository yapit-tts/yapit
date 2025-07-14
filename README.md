# yapit

## Development

Set up the backend dev env:
```bash
uv sync --all-extras
cp .env.prod.example .env.prod # .env.prod must exist, even if it's not used in dev
echo "RUNPOD_API_KEY=asdf\nMISTRAL_API_KEY=asdf" > .env.local # env vars you do not want to commit 
```

If you want to also use runpod workers, put `RUNPOD_API_KEY` in `.env.local`.
This entry also needs to exist (with any value) for the gateway to start up wiith the default `endpoints.dev.json` configuration.

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

### Stack-Auth

The following admin user is created on startup:

```
username: dev@yap.it
password: yapit123
```

> **The admin user can only be used to access the stack-auth dashboard. It's not an application user**

