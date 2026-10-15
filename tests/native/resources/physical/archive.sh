#!/bin/sh
# Retain exact synthetic WAL segments in the disposable drill volume.
set -eu

# ret::exit_code -> ret::exit_code
# Remove only this invocation's incomplete candidate and preserve PostgreSQL's retry status.
cleanup() {
    status="$?"
    if [ -n "${temporary:-}" ]; then
        rm -f -- "$temporary"
    fi
    exit "$status"
}

# source::path name::string -> ret::exit_code
# Return zero only after atomic publication or verification of an identical prior archive.
archive_segment() {
    source="$1"
    destination="/drill/wal/$2"
    if [ -f "$destination" ]; then
        cmp -- "$source" "$destination"
        return "$?"
    fi
    temporary="$(mktemp /drill/wal/.pending.XXXXXX)"
    trap cleanup 0
    cp -- "$source" "$temporary"
    mv -- "$temporary" "$destination"
}

archive_segment "$@"
