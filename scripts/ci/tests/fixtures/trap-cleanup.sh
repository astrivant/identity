#!/usr/bin/env bash
# Run an extracted production handler against synthetic files and controlled command failures.
# handler_file::path -> ret::exit_code (the production EXIT handler decides the final status).
set -euo pipefail
: "${TEST_DIRECTORY:?Synthetic directory required}"
: "${TEST_COMMAND_STATUS:?Command status required}"
: "${TEST_CLEANUP_FAIL:?Cleanup outcome required}"

raw_directory="$TEST_DIRECTORY/raw findings"
payload="$TEST_DIRECTORY/view payload"
signing_dir="$TEST_DIRECTORY/signing backup"
export raw_directory payload signing_dir

# Record cleanup calls and simulate permission failure without changing real filesystem permissions.
# arguments::string[] -> ret::exit_code (23 for an injected failure, otherwise the real rm status).
rm() {
    printf '%s\n' cleanup >>"$TEST_DIRECTORY/cleanup.calls"
    if [ "$TEST_CLEANUP_FAIL" = true ]; then
        return 23
    fi
    command rm "$@"
}

# The test supplies only the production function and its actual trap registration.
# shellcheck source=/dev/null
source "$1"
(exit "$TEST_COMMAND_STATUS")
