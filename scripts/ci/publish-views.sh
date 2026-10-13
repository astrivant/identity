#!/usr/bin/env bash
# Publish generated views atomically through GitHub's verified commit API.
# environment::GitHub_Actions -> ret::exit_code
set -euo pipefail
umask 077
: "${GITHUB_REPOSITORY:?Repository required}"
: "${GITHUB_SHA:?Source revision required}"
: "${RUNNER_TEMP:?Temporary directory required}"

# This helper is only for explicitly selected private collection repositories.
gh api "repos/$GITHUB_REPOSITORY" --jq .private | jq -e '. == true' >/dev/null

# path::string -> ret::exit_code
# Restrict generated outputs to the explicit collection publication contract.
allowed() {
    case "$1" in
        docs/assets/*.svg | docs/assets/*.png | knowledge/schemas/*.json) return 0 ;;
        docs/assets/knowledge-graph.json | docs/assets/life.json | docs/assets/checkpoints.json | docs/assets/repertoire.json | docs/assets/instances.json | docs/assets/view-provenance.json) return 0 ;;
        *) return 1 ;;
    esac
}
current=$(gh api "repos/$GITHUB_REPOSITORY/commits/main" --jq .sha)
if [[ "$current" != "$GITHUB_SHA" ]]; then
    echo '::notice::Main advanced; its newer workflow owns the figure refresh.'
    exit 0
fi

# Validate the current source and downloaded bytes before using the write token.
receipt=docs/assets/view-provenance.json
python3 scripts/ci/view_manifest.py --receipt "$receipt" --revision "$GITHUB_SHA" --verify-receipt

# Stage only the existing generated-output contract, never private source journals.
generated=()
while IFS= read -r -d '' name; do
    if allowed "$name"; then
        generated+=("$name")
    fi
done < <(git ls-files --cached --others --exclude-standard -z -- docs/assets knowledge/schemas)
if [[ ${#generated[@]} -gt 0 ]]; then
    git add -- "${generated[@]}"
fi
if git diff --cached --quiet; then
    echo 'Generated views are unchanged.'
    exit 0
fi
if [[ -n $(git diff --cached --name-only --diff-filter=D) ]]; then
    echo 'Generated deletions require review.' >&2
    exit 1
fi

payload=$(mktemp "$RUNNER_TEMP/identity-views.XXXXXX")
trap 'rm -f "$payload" "$payload.rows" "$payload.response" "$payload.encoded"' EXIT
: >"$payload.rows"
while IFS= read -r -d '' name; do
    if ! allowed "$name"; then
        echo 'Unexpected staged path; refusing publication.' >&2
        exit 1
    fi
    if [[ -L "$name" || ! -f "$name" ]]; then
        echo 'Generated outputs must be regular files.' >&2
        exit 1
    fi
    # File-backed input avoids Linux's per-argument size limit and keeps figure bytes out of argv.
    base64 <"$name" | tr -d '\n' >"$payload.encoded"
    jq -nc --arg path "$name" --rawfile contents "$payload.encoded" '{path:$path,contents:$contents}' >>"$payload.rows"
done < <(git diff --cached --name-only -z)

# The expected head fences concurrent writers; GitHub signs the one atomic commit.
jq -n --rawfile query scripts/ci/publish-views.graphql \
    --arg repository "$GITHUB_REPOSITORY" --arg revision "$GITHUB_SHA" --slurpfile additions "$payload.rows" \
    '{query:$query,variables:{input:{branch:{repositoryNameWithOwner:$repository,branchName:"main"},
      expectedHeadOid:$revision,message:{headline:"Refresh evidence and project checkpoint views"},
      fileChanges:{additions:$additions}}}}' >"$payload"
if gh api graphql --input "$payload" >"$payload.response" &&
    jq -e '.errors == null and .data.createCommitOnBranch.commit.oid != null' "$payload.response" >/dev/null; then
    jq -r '.data.createCommitOnBranch.commit.url' "$payload.response"
else
    current=$(gh api "repos/$GITHUB_REPOSITORY/commits/main" --jq .sha)
    if [[ "$current" != "$GITHUB_SHA" ]]; then
        echo '::notice::Main changed during publication; its newer workflow will regenerate views.'
        exit 0
    fi
    echo 'Generated-view publication failed; inspect this run without force-pushing.' >&2
    exit 1
fi
