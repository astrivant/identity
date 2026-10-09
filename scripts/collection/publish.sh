#!/usr/bin/env bash
# Commit only current generated collection outputs without overwriting a newer main revision.
set -euo pipefail
set +x

: "${GITHUB_SHA:?Run from the private main workflow}"
: "${GITHUB_REPOSITORY:?Select the private collection repository}"
: "${GH_TOKEN:?Supply the job token}"

# Use the token through gh's credential helper; never persist it in remote URLs or checkout configuration.
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' fetch origin main
if [[ "$(git rev-parse origin/main)" != "$GITHUB_SHA" ]]; then
    echo 'Main advanced while rendering. Refresh the latest main revision; this run will not overwrite it.' >&2
    exit 1
fi

paths=(README.md collection/figures.enc.json collection/figures.enc.json.sigstore.json collection/figures.enc.json.sha256)
if [[ -d docs/collection ]] || git ls-files --error-unmatch 'docs/collection/*' >/dev/null 2>&1; then
    paths+=(docs/collection)
fi
git add -A -- "${paths[@]}"
if git diff --cached --quiet; then
    exit 0
fi

git -c user.name='github-actions[bot]' -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    commit --only -m 'docs: refresh encrypted collection figures' -- "${paths[@]}"
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin HEAD:refs/heads/main
