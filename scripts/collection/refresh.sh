#!/usr/bin/env bash
# Keep decrypted collection data, plotting caches, and temporary files in nonswappable memory.
set -euo pipefail
set +x
umask 077
ulimit -c 0
: "${WITFUL_SECURE_TEMP:?Prepare a private memory-backed working directory first}"
export TMPDIR="$WITFUL_SECURE_TEMP"
export MPLCONFIGDIR="$WITFUL_SECURE_TEMP/matplotlib"
export XDG_CACHE_HOME="$WITFUL_SECURE_TEMP/cache"
witful collection check-storage --path "$WITFUL_SECURE_TEMP"
witful collection refresh
