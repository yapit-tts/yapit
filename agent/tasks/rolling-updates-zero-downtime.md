---
status: active
started: 2025-01-04
---

# Task: Rolling Updates / Zero-Downtime Deployments

## Intent

Eliminate the noticeable downtime during production deployments. Currently, deploying causes all containers to stop briefly before new ones start, causing Bad Gateway errors and service interruption.

## Current State

**Architecture:**
- Dokploy (self-hosted PaaS) on Hetzner VPS
- Docker Compose with Traefik for routing
- Deploy via `scripts/deploy.sh` → syncs secrets → triggers Dokploy API → waits 90s → smoke test

**Why downtime occurs:**
- Dokploy's Docker Compose deployments use `docker compose up -d --build`
- This stops existing containers, rebuilds, starts new ones
- During the stop-start gap, Traefik has no backend → 502 errors

## Sources

**MUST READ:**
- [[hetzner-deployment]] - deployment architecture context
- [[dokploy-operations]] - Dokploy API patterns, Traefik recovery

**Research:**
- [Dokploy Zero Downtime Docs](https://docs.dokploy.com/docs/core/applications/zero-downtime) - **only for "Applications", NOT Compose** - this was the key finding that led us to Docker Stack
- [Dokploy Docker Compose docs](https://docs.dokploy.com/docs/core/docker-compose) - explains Compose vs Stack modes, `composeType` setting
- [Dokploy Troubleshooting](https://docs.dokploy.com/docs/core/troubleshooting) - Stack mode differences: `deploy.labels` required, ports auto-exposed
- [GitHub Issue #2497](https://github.com/Dokploy/dokploy/issues/2497) - confirms Compose zero-downtime not supported, suggests `start-first` workaround
- [GitHub Discussion #492](https://github.com/Dokploy/dokploy/discussions/492) - best practices for zero-downtime, Swarm health checks
- [docker-rollout](https://github.com/wowu/docker-rollout) - alternative third-party tool (rejected: awkward Dokploy integration)
- [Docker Compose deploy spec](https://docs.docker.com/reference/compose-file/deploy/) - `update_config.order: start-first` for rolling updates
- [Reintech guide](https://reintech.io/blog/zero-downtime-deployments-docker-compose-rolling-updates) - good overview of `update_config` settings

## Key Findings

### Dokploy's Limitation

Dokploy supports zero-downtime **only for Applications** (single-container deployments), not Docker Compose services. The feature uses Docker Swarm health checks under the hood.

For Compose deployments, Dokploy just runs `docker compose up -d` which does stop-first (downtime).

### Options Analyzed

**Option A: Switch to Docker Stack Deploy (Swarm mode)**

Uses Docker Swarm's native `update_config.order: start-first`:

```yaml
services:
  gateway:
    image: ghcr.io/yapit-tts/gateway:${GIT_COMMIT}
    deploy:
      replicas: 1
      update_config:
        order: start-first
        failure_action: rollback
      rollback_config:
        order: stop-first
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Pros:
- Native Docker, no external tools
- Built-in rollback on failure
- Works with existing Dokploy infrastructure (Swarm already initialized)

Cons:
- **`build:` directive not supported in Swarm mode** - must pre-build and push images to registry
- Need to set up GitHub Container Registry (ghcr.io) or similar
- More CI complexity (build → push → deploy vs current build-on-VPS)
- Some compose features differ in stack mode

**Option B: docker-rollout Plugin**

Third-party CLI plugin that does the scale-up/wait/scale-down pattern for regular Docker Compose:

```bash
# Instead of: docker compose up -d gateway
docker rollout gateway
```

Pros:
- Drop-in replacement, minimal changes to current workflow
- Works with `build:` directive
- No registry needed

Cons:
- Third-party dependency
- Requires: no `container_name`, no explicit `ports` (use `expose`)
- Current issue: `stack-auth` has `ports: "127.0.0.1:8101:8101"` for SSH tunnel
- Each service rolled individually (script would call multiple times)

**Option C: Hybrid - Dokploy Applications for stateless services**

Split the deployment:
- Use Dokploy "Application" deployments for gateway, frontend (get zero-downtime)
- Keep Compose for infra: postgres, redis, stack-auth (rarely change anyway)

Pros:
- Uses Dokploy's built-in zero-downtime feature
- Infra services that rarely update don't need rolling updates

Cons:
- Multiple deployment targets to manage
- Lose single docker-compose.prod.yml as source of truth
- More complex IaC

**Option D: Manual Blue-Green Script**

Deploy to new compose project, switch Traefik routing via labels, tear down old.

Pros:
- Full control, atomic switchover

Cons:
- Most complex to implement
- Double resource usage during switch
- More failure modes

## Recommendation: Docker Stack (Option A)

After further research, **Docker Stack is the cleaner path** because:
1. Dokploy natively supports it (just change `composeType` from `"docker-compose"` to `"stack"`)
2. No third-party tools needed
3. Native Swarm rolling updates with `update_config`
4. Built-in rollback on failure

**Trade-off:** Requires pre-built images (ghcr.io) instead of build-on-VPS, but this is actually better:
- Faster deploys (just pull, no build)
- VPS CPU not taxed during deploy
- Build happens on GitHub runners (free tier)

## Dokploy Stack Mode - How It Works

**Current setting:**
```bash
# Check current
curl ... compose.one | jq ".composeType"  # Returns "docker-compose"
```

**To switch:**
```bash
curl -X POST ... compose.update -d '{"json":{"composeId":"...", "composeType":"stack"}}'
```

When `composeType: "stack"`, Dokploy runs `docker stack deploy` instead of `docker compose up`.

## Compose File Changes for Stack Mode

### 1. Replace `build:` with `image:`

```yaml
# Before (docker-compose mode)
gateway:
  build:
    context: .
    dockerfile: yapit/gateway/Dockerfile

# After (stack mode)
gateway:
  image: ghcr.io/yapit-tts/gateway:${GIT_COMMIT:-latest}
```

### 2. Move Traefik labels to `deploy.labels`

```yaml
# Before
frontend:
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.yapit-frontend.rule=Host(`yaptts.org`)"

# After
frontend:
  deploy:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.yapit-frontend.rule=Host(`yaptts.org`)"
```

### 3. Add `deploy.update_config` for rolling updates

```yaml
gateway:
  image: ghcr.io/yapit-tts/gateway:${GIT_COMMIT:-latest}
  deploy:
    replicas: 1
    update_config:
      order: start-first        # Start new before stopping old
      failure_action: rollback  # Auto-rollback on failure
      delay: 10s
    rollback_config:
      order: stop-first
    labels:
      - "traefik.enable=true"
      # ... rest of labels
```

### 4. Change `ports:` to `expose:` (except for SSH tunnel)

Stack mode auto-exposes ports, so explicit `ports:` breaks things:

```yaml
# Before
stack-auth:
  ports:
    - "127.0.0.1:8101:8101"

# After - use Traefik for all access, remove localhost binding
stack-auth:
  expose:
    - "8101"
    - "8102"
```

**Note:** SSH tunnel to dashboard would need alternative (Traefik auth middleware, or accept using auth.yaptts.org only).

### 5. Services that DON'T need rolling updates

Postgres and Redis rarely change and are stateful - keep them simple:

```yaml
postgres:
  image: postgres:16-alpine  # Already using image, no change needed
  deploy:
    replicas: 1
    update_config:
      order: stop-first  # Stateful = stop old before starting new
```

## GitHub Actions Workflow (New)

```yaml
# .github/workflows/build-and-deploy.yml
name: Build and Deploy

on:
  push:
    branches: [main]

env:
  REGISTRY: ghcr.io

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to Container Registry
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push images
        run: |
          GIT_COMMIT=${{ github.sha }}

          # Build and push each service
          for service in frontend gateway kokoro-cpu stack-auth; do
            docker build -f <dockerfile-path> -t ghcr.io/yapit-tts/$service:$GIT_COMMIT .
            docker push ghcr.io/yapit-tts/$service:$GIT_COMMIT
          done

      - name: Trigger Dokploy deployment
        run: |
          # SSH to VPS and trigger deploy via API
          # (or use Dokploy webhook)
```

## Gotchas

- **Stack mode requires `deploy.labels`** - regular `labels:` are ignored for Traefik routing
- **No `build:` in stack mode** - must use pre-built images from registry
- **Health checks critical** - Swarm waits for healthy before routing traffic
- **Private registry needs `--with-registry-auth`** - Dokploy should handle this, but verify
- **Stateful services (postgres, redis)** - use `update_config.order: stop-first`, not `start-first`
- **The 90s sleep in deploy.sh** - no longer needed, Swarm handles waiting for healthy

## Implementation Done

### Files Changed
- `docker-compose.prod.yml` - converted to Stack mode (images, deploy.labels, update_config)
- `.github/workflows/deploy.yml` - new CI/CD workflow with build + deploy
- `scripts/deploy.sh` - simplified to SSH + tRPC API
- `scripts/build-images.sh` - local image building (optional)

### GitHub Secrets Needed
- `VPS_SSH_KEY` - SSH private key for root@78.46.242.1

### Migration Steps

1. **Add GitHub Secret**: `gh secret set VPS_SSH_KEY < ~/.ssh/your_deploy_key`
2. **Merge dev → main**: Transition to main branch workflow
3. **Switch Dokploy to Stack mode**:
   ```bash
   ssh root@78.46.242.1 'TOKEN=$(cat /root/.dokploy-token); \
     curl -X POST -H "x-api-key: $TOKEN" -H "Content-Type: application/json" \
     "http://localhost:3000/api/trpc/compose.update" \
     -d "{\"json\":{\"composeId\":\"Fmex638n6F7Nrw81Lubc_\",\"composeType\":\"stack\"}}"'
   ```
4. **First deploy**: Push to main, CI builds images, deploys
5. **Verify**: Check https://yaptts.org works, no 502s

### Quick Deploy (skip tests)
```bash
gh workflow run deploy.yml -f skip_tests=true
```

## Resource Considerations

During rolling update, services briefly run 2× instances:
- Gateway: ~500MB → 1GB peak
- Kokoro-cpu ×2: ~2.4GB → 4.8GB peak
- Total peak: ~6.5GB (fits in 8GB CX33)

Swarm handles sequential rollout automatically.
