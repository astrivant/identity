#!/usr/bin/env bash
# Fake bounded GitHub responses without network access or credential values.
# arguments::string[] -> ret::exit_code
set -euo pipefail
if [[ $2 == graphql ]]; then
    cp "$4" "$QA_CAPTURE"
    if [[ $QA_MODE == race ]]; then
        touch "$QA_RACE"
        exit 1
    fi
    echo '{"data":{"createCommitOnBranch":{"commit":{"oid":"synthetic","url":"https://github.com/example/private/commit/synthetic"}}}}'
elif [[ $2 == */commits/main ]]; then
    if [[ $QA_MODE == stale || -e $QA_RACE ]]; then
        echo newer
    else
        echo "$GITHUB_SHA"
    fi
elif [[ $QA_MODE == public ]]; then
    echo false
else
    echo true
fi
