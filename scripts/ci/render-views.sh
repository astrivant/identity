#!/usr/bin/env bash
# Rebuild the committed synthetic examples without reading any personal collection.
# arguments::string[] -> ret::exit_code
set -euo pipefail
witful checkpoints --repo examples/project-chapters build --output-dir ../../docs/assets/project-chapters
arguments=(--source examples/project-chapters/knowledge/checkpoints.jsonl --source 'pkg/witful/checkpoints/*.py'
    --source pkg/witful/knowledge/plotting.py --source 'scripts/ci/*.py' --source 'scripts/ci/*.sh' --source 'scripts/ci/*.graphql' --source pyproject.toml --source poetry.lock
    --source .github/workflows/ci.yml --output docs/assets/project-chapters/checkpoints.json
    --output docs/assets/project-chapters/checkpoint-transitions.svg --output docs/assets/project-chapters/checkpoint-transitions.png
    --output docs/assets/project-chapters/checkpoint-comparisons.svg --output docs/assets/project-chapters/checkpoint-comparisons.png
    --receipt docs/assets/project-chapters/view-provenance.json)
python scripts/ci/view_manifest.py "${arguments[@]}"
python scripts/ci/view_manifest.py "${arguments[@]}" --check
