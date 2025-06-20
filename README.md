# yapit

## Development

Set up the backend dev env:
```bash
uv sync --all-extras
cp .env.prod.example .env.prod # .env.prod must exist, even if it's not used in dev
touch .env.local # put keys that you also want to use in dev but dont want to commit here
```

If you want to also use runpod workers (or don't want to change the default dev endpoint config), put RUNPOD_API_KEY in `.env.local` (with any value, it just needs to exist).

Start the backend services:
```bash
make dev-cpu  # make dev-mac if you are on mac
```

Start the frontend and login at `http://localhost/auth/signin` with the test user credentials printed by `dev-cpu`:
```bash
cd frontend && npm run dev
```

Check if everything works (needs runpod key):
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

