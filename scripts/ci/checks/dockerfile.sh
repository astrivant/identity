#!/usr/bin/env bash
# Run Docker's build checks against each maintained build context, without building images.
set -euo pipefail
cd "$(dirname "$0")/../../.."

# A target can prune unused stages, so check both application paths explicitly.
for target in production development; do
    docker buildx build --check --target "$target" --file services/witful/Dockerfile .
done
docker buildx build --check services/codegraph
