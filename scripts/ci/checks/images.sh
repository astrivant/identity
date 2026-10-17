#!/usr/bin/env bash
# Exercise exact locally built images with no network or registry fallback.
set -euo pipefail
cd "$(dirname "$0")/../../.."

# Check image configuration and the actual runtime without mounting any host collection.
# image::sha256_id target::string -> ret::exit_code; fails on any violated image contract.
verify_image() {
    local image="$1" target="$2"
    if [[ ! "$image" =~ ^sha256:[0-9a-f]{64}$ ]]; then
        printf 'Expected an immutable local image ID for %s.\n' "$target" >&2
        return 64
    fi
    test "$(docker image inspect --format '{{.Config.User}}' "$image")" = '10001:10001'
    test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$image")" = '["/usr/bin/tini","-g","--","witful"]'
    test "$(docker image inspect --format '{{.Config.StopSignal}}' "$image")" = SIGTERM
    test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.licenses"}}' "$image")" = BUSL-1.1
    if [ -n "${GITHUB_SHA:-}" ]; then
        test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")" = "$GITHUB_SHA"
    fi

    local -a options=(--pull=never --rm --network none --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m)
    # Production permits writes only to explicit ephemeral working mounts.
    if [ "$target" = production ]; then
        options+=(--read-only
            --tmpfs "/run/witful:rw,noexec,nosuid,nodev,mode=0700,uid=10001,gid=10001"
            --tmpfs "/home/witful:rw,noexec,nosuid,nodev,mode=0700,uid=10001,gid=10001")
    fi
    docker run "${options[@]}" "$image" --help >/dev/null
    docker run "${options[@]}" "$image" lessons --help >/dev/null
    docker run "${options[@]}" --interactive --entrypoint /usr/bin/tini "$image" -g -- python - "$target" \
        <scripts/ci/containers/runtime.py
    printf 'Verified %s image %s\n' "$target" "$image"
}

verify_image "${PRODUCTION_IMAGE:?Set the built production image ID}" production
verify_image "${DEVELOPMENT_IMAGE:?Set the built development image ID}" development
docker compose -f services/compose.development.yaml --profile development config --quiet
