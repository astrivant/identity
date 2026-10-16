#!/usr/bin/env bash
# Sign verified distribution bytes, publish to PyPI, and attach the complete verification set to a draft release.
set -euo pipefail
set +x
umask 077

: "${COSIGN_PRIVATE_KEY:?Set the repository signing secret}"
: "${POETRY_PYPI_TOKEN_PYPI:?Select this repository for the organization PyPI secret}"
: "${RELEASE_TAG:?Run this command for a version tag}"
: "${GITHUB_REPOSITORY:?Supply the release repository}"
export COSIGN_PASSWORD="${COSIGN_PASSWORD:-}"

if [[ ! "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo 'Expected a stable vMAJOR.MINOR.PATCH tag.' >&2
    exit 2
fi

mkdir -p .cache/release
cp dist/* .cache/release/
artifact_dir="$PWD/.cache/release"
python -m scripts.release.cli prepare --output "$RUNNER_TEMP/release-feedback"
cp "$RUNNER_TEMP/release-feedback/RELEASE.json" "$artifact_dir/RELEASE.json"
cosign public-key --key env://COSIGN_PRIVATE_KEY >"$artifact_dir/cosign.pub"
openssl pkey -pubin -in "$artifact_dir/cosign.pub" -outform DER |
    openssl dgst -sha256 >"$artifact_dir/public-key.sha256"

# Bind each immutable deliverable before generating a manifest covering the full verification payload.
for artifact in "$artifact_dir"/*.whl "$artifact_dir"/*.tar.gz; do
    cosign sign-blob --yes --key env://COSIGN_PRIVATE_KEY --bundle "$artifact.sigstore.json" "$artifact"
    cosign verify-blob --key "$artifact_dir/cosign.pub" --bundle "$artifact.sigstore.json" "$artifact"
done
(
    cd "$artifact_dir"
    sha256sum ./*.whl ./*.tar.gz ./*.sigstore.json ./cosign.pub ./public-key.sha256 ./SOURCE.json ./RELEASE.json >SHA256SUMS
    cosign sign-blob --yes --key env://COSIGN_PRIVATE_KEY --bundle SHA256SUMS.sigstore.json SHA256SUMS
    cosign verify-blob --key cosign.pub --bundle SHA256SUMS.sigstore.json SHA256SUMS
    sha256sum --check SHA256SUMS
)

notes="$RUNNER_TEMP/release-feedback/release-notes.md"

# A completed release is immutable; retry only an existing draft or create one with reviewed bytes.
if gh release view "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --json isDraft --jq .isDraft >"$RUNNER_TEMP/release-state" 2>/dev/null; then
    if [ "$(cat "$RUNNER_TEMP/release-state")" != true ]; then
        echo 'Release is already published; refusing to replace its artifacts.' >&2
        exit 1
    fi
else
    gh release create "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --verify-tag --draft --title "Witful $RELEASE_TAG" --notes-file "$notes"
fi

gh release upload "$RELEASE_TAG" "$artifact_dir"/* --repo "$GITHUB_REPOSITORY" --clobber

# Poetry publishes only downloaded build artifacts, never a rebuild. A failed upload leaves the release as a draft.
poetry publish --no-interaction --skip-existing
gh release edit "$RELEASE_TAG" --repo "$GITHUB_REPOSITORY" --draft=false --notes-file "$notes"

# Pass public trust material independently from the subsequently downloaded release assets.
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    fingerprint="$(awk '{print $NF}' "$artifact_dir/public-key.sha256")"
    echo "fingerprint=$fingerprint" >>"$GITHUB_OUTPUT"
fi
