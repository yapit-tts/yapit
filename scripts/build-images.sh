#!/usr/bin/env bash
# Build and push all Docker images to GitHub Container Registry
# Used by: CI, or locally for manual deploys
#
# Prerequisites:
#   docker login ghcr.io -u <github-user> -p <github-token>
#
# Environment variables:
#   GIT_COMMIT - Tag for images (default: current HEAD)
set -euo pipefail

cd "$(dirname "$0")/.."

GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse HEAD)}"
REGISTRY="ghcr.io/yapit-tts"

echo "==> Building images for commit: ${GIT_COMMIT:0:7}"

# Images to build: name:context:dockerfile
IMAGES=(
  "frontend:./frontend:./frontend/Dockerfile"
  "gateway:.:./yapit/gateway/Dockerfile"
  "kokoro-cpu:.:./yapit/workers/kokoro/Dockerfile.cpu"
  "stack-auth:.:./docker/Dockerfile.stackauth"
)

for image_spec in "${IMAGES[@]}"; do
  IFS=: read -r name context dockerfile <<< "$image_spec"

  echo ""
  echo "==> Building $name..."

  docker build \
    --build-arg GIT_COMMIT="$GIT_COMMIT" \
    -t "$REGISTRY/$name:$GIT_COMMIT" \
    -t "$REGISTRY/$name:latest" \
    -f "$dockerfile" \
    "$context"

  echo "==> Pushing $name..."
  docker push "$REGISTRY/$name:$GIT_COMMIT"
  docker push "$REGISTRY/$name:latest"
done

echo ""
echo "==> All images built and pushed!"
echo "    Tags: $GIT_COMMIT, latest"
