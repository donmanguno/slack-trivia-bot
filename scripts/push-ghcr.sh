#!/usr/bin/env bash
# Push the slack-trivia-bot image to GitHub Container Registry (ghcr.io).
#
# Usage:
#   ./scripts/push-ghcr.sh <github-username> [tag]
#
# Examples:
#   ./scripts/push-ghcr.sh donmanguno
#   ./scripts/push-ghcr.sh donmanguno v1.2.0
#
# Authentication:
#   You need a GitHub Personal Access Token with the `write:packages` scope.
#   Generate one at: https://github.com/settings/tokens/new
#   Then export it before running this script:
#
#     export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
#
set -euo pipefail

GITHUB_USER="${1:-}"
IMAGE_TAG="${2:-latest}"
IMAGE_NAME="slack-trivia-bot"

if [[ -z "$GITHUB_USER" ]]; then
  echo "Error: GitHub username is required."
  echo "Usage: $0 <github-username> [tag]"
  exit 1
fi

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "Error: GITHUB_TOKEN environment variable is not set."
  echo "Export a token with write:packages scope:"
  echo "  export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx"
  exit 1
fi

REMOTE_IMAGE="ghcr.io/${GITHUB_USER}/${IMAGE_NAME}:${IMAGE_TAG}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
BUILDER_NAME="trivia-multiplatform"

echo "==> Logging in to ghcr.io as ${GITHUB_USER}..."
echo "${GITHUB_TOKEN}" | docker login ghcr.io --username "${GITHUB_USER}" --password-stdin

# Ensure a buildx builder with multi-platform support exists
if ! docker buildx inspect "${BUILDER_NAME}" &>/dev/null; then
  echo "==> Creating buildx builder '${BUILDER_NAME}'..."
  docker buildx create --name "${BUILDER_NAME}" --use
else
  docker buildx use "${BUILDER_NAME}"
fi

echo "==> Building and pushing multi-platform image (${PLATFORMS})..."
docker buildx build \
  --platform "${PLATFORMS}" \
  --tag "${REMOTE_IMAGE}" \
  --push \
  "$(dirname "$0")/.."

echo ""
echo "Done! Image available at:"
echo "  ${REMOTE_IMAGE}"
echo ""
echo "To run it:"
echo "  docker run -d --restart unless-stopped \\"
echo "    --env-file .env \\"
echo "    -v trivia-data:/data \\"
echo "    ${REMOTE_IMAGE}"
