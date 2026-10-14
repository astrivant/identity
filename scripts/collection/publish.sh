#!/usr/bin/env bash
# Publish the verified generation atomically; branch protection and concurrent writers remain authoritative.
set -euo pipefail
set +x
: "${WITFUL_SECURE_TEMP:?Prepare and verify a candidate first}"
: "${GH_TOKEN:?Supply the job token}"
witful collection publish-refresh --output "$WITFUL_SECURE_TEMP/publication"
