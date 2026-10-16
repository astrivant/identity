"""
Bind contributor notification to publication verification in the same logical workflow.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_reporting_stage_is_tag_scoped_and_serializes_comment_writers() -> None:
    """
    Prevent PR runs, failed publication or concurrent reruns from announcing success.

    Returns:
        None: The terminal stage owns its verification, permissions and receipt retention.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["release-feedback"]
    assert job["needs"] == ["publish"]
    assert "!cancelled()" in job["if"]
    assert "github.event_name == 'push'" in job["if"]
    assert "refs/tags/v" in job["if"]
    assert "github.repository == 'astrivant/identity'" in job["if"]
    assert job["with"]["publication-result"] == "${{ needs.publish.result }}"
    assert job["with"]["fingerprint"] == "${{ needs.publish.outputs.fingerprint }}"
    assert job["permissions"] == {"contents": "read", "pull-requests": "write"}
    stage = yaml.load((ROOT / ".github/workflows/stage-release-feedback.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(stage["on"]) == {"workflow_call"}
    feedback = stage["jobs"]["feedback"]
    assert feedback["concurrency"]["cancel-in-progress"] == "false"
    assert "inputs.tag" in feedback["concurrency"]["group"]
    steps = feedback["steps"]
    assert steps[0]["run"] == 'test "$PUBLICATION_RESULT" = success'
    notification = next(step for step in steps if "scripts.release.report" in step.get("run", ""))
    assert "notify" in notification["run"] and "--fingerprint" in notification["run"]
    assert steps[-1]["if"] == "always()"
    assert steps[-1]["with"]["name"] == "release-feedback"


def test_publisher_signs_inventory_and_preserves_existing_note_details() -> None:
    """
    Keep release communication bound to the signed payload and accepted source build.

    Returns:
        None: The existing publisher signs the inventory and uses the shared notes renderer.
    """
    script = (ROOT / "scripts/release/publish.sh").read_text()
    assert script.index("scripts.release.report prepare") < script.index("cosign sign-blob")
    assert "./RELEASE.json >SHA256SUMS" in script
    assert "fingerprint=$fingerprint" in script
    assert '--notes-file "$notes"' in script
    template = (ROOT / "scripts/release/notes.md").read_text()
    assert template.startswith("## Release details\n")
    assert "pip install witful" in template and "cosign verify-blob" in template and "sha256sum --check" in template
