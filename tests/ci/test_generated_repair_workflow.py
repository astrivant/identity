"""
Keep privileged conflict repair separate from source execution and release jobs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GUARD = "github.event_name != 'pull_request_target' && github.event_name != 'schedule'"


def test_repair_uses_trusted_code_with_narrow_permissions() -> None:
    """
    Permit a bounded PR writer without candidate checkout or secret access.

    Returns:
        None: Trusted source, event scope and leaf permissions remain explicit.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    caller = workflow["jobs"]["generated-repair"]
    stage = yaml.load((ROOT / ".github/workflows/stage-repair.yml").read_text(), Loader=yaml.BaseLoader)
    job = stage["jobs"]["repair"]
    assert set(stage["on"]) == {"workflow_call"}
    assert caller["uses"] == "./.github/workflows/stage-repair.yml"
    assert "needs" not in caller
    assert "pull_request_target" in caller["if"] and "schedule" in caller["if"]
    assert "github.event.pull_request.base.ref" not in caller["if"]
    assert "branches" not in workflow["on"]["pull_request_target"]
    assert "branches-ignore" not in workflow["on"]["pull_request_target"]
    assert caller["permissions"] == job["permissions"] == {"contents": "write", "pull-requests": "read"}
    assert "secrets" not in caller and "environment" not in job
    assert job["concurrency"] == {"group": "generated-conflict-repair", "cancel-in-progress": "false"}
    steps = job["steps"]
    assert len(steps) == 3
    assert steps[0]["with"] == {"ref": "${{ github.sha }}", "persist-credentials": "false", "fetch-depth": "0"}
    assert steps[-1]["uses"].startswith("actions/github-script@")
    assert "scripts/ci/repair/repair.mjs" in steps[-1]["with"]["script"]
    assert set(workflow["on"]["pull_request_target"]["types"]) == {
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "edited",
        "closed",
    }


def test_repair_events_cannot_run_other_jobs() -> None:
    """
    Check every existing consumer instead of relying on transitive skip behavior.

    Returns:
        None: All source, secret and publication jobs exclude repair-only events.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    explicit_events = {
        "coverage-badge": "github.event_name == 'push'",
        "generated-updates": "github.event_name == 'push'",
        "publish": "github.event_name == 'push'",
        "release-feedback": "github.event_name == 'push'",
        "collection": "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')",
        "trivy-pr-comment": "github.event_name == 'pull_request'",
    }
    for name, job in jobs.items():
        if name == "generated-repair":
            continue
        if name in explicit_events:
            assert explicit_events[name] in job["if"]
        else:
            assert job["if"] == ("always() && " if name == "quality-gate" else "") + GUARD
    assert "generated-repair" not in jobs["quality-gate"]["needs"]
    assert "generated-repair" not in jobs["publish"]["needs"]
    assert set(jobs["quality-gate"]["needs"]) == set(jobs["publish"]["needs"])


def test_inventory_and_ownership_are_checked_locally_and_in_ci() -> None:
    """
    Keep local generated-output checks aligned with the source validation stage.

    Returns:
        None: Both boundaries validate the inventory and ownership normalization.
    """
    hooks = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    local = {hook["id"]: hook for hook in hooks["repos"][0]["hooks"]}
    assert local["generated-artifact-inventory"]["entry"] == "python scripts/ci/repair/plan.py --check"
    assert local["codeowners-tree"]["entry"] == "python -m scripts.ownership --write"
    assert local["codeowners-tree-push"]["stages"] == ["pre-push"]
    assert local["codeowners-tree-push"]["entry"] == "python -m scripts.ownership --check --revision HEAD"
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "python scripts/ci/repair/plan.py --check" in workflow
    assert "python -m scripts.ownership --check" in workflow
