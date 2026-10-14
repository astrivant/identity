#!/usr/bin/env bash
# Validate every workflow and require ShellCheck rather than silently skipping inline shell analysis.
set -euo pipefail

# The pinned pre-commit environment provides actionlint; the locked Python environment provides ShellCheck.
shellcheck_path="$(command -v shellcheck)"
exec actionlint -shellcheck "$shellcheck_path" "$@"
