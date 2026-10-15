#!/usr/bin/env bash
set -euo pipefail

# Restore the lock by default; --update deliberately resolves a new dependency lock.
# args::string[] -> ret::exit_code (0 success, 2 usage error, otherwise Helm failure)
main() {
    local action=build
    if [ "$#" -eq 1 ] && [ "$1" = --update ]; then
        action=update
    elif [ "$#" -ne 0 ]; then
        echo 'Usage: dependencies.sh [--update]' >&2
        return 2
    fi

    local project_root
    project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
    cd -- "$project_root"
    mkdir -p .cache/helm/repository

    # Register only this chart's repository; never refresh the caller's unrelated repositories.
    local repository_options=(
        --repository-config .cache/helm/repositories.yaml
        --repository-cache .cache/helm/repository
    )
    helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts "${repository_options[@]}"
    if [ "$action" = update ] || [ ! -f .cache/helm/repository/cloudnative-pg-index.yaml ]; then
        helm repo update cloudnative-pg "${repository_options[@]}"
    fi
    exec helm dependency "$action" helm/witful --skip-refresh \
        "${repository_options[@]}"
}

main "$@"
