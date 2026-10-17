"""
Exercise comment recognition and move-safe Markdown links on independent language fixtures.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from documentation.source_links import BEGIN, END, declare, main, render, updates
from witful.intent.docrefs import discover, references

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "comment", "definition"),
    [
        ("a.py", "#", "class Model: pass"),
        ("a.go", "//", "type Model struct{}"),
        ("a.ts", "//", "interface Model {}"),
        ("a.rs", "//", "struct Model;"),
        ("a.sql", "--", "SELECT 1;"),
        ("a.sh", "#", "true"),
    ],
)
def test_language_comments(name: str, comment: str, definition: str) -> None:
    """
    Retain the same explicit contract across maintained language lexers.

    Args:
        name (str): Source filename selecting a builtin lexer.
        comment (str): Native single-line comment prefix.
        definition (str): Source line named by the breadcrumb.

    Returns:
        None: Exact offsets, IDs and line destinations are verified.
    """
    raw = f"{comment} docref:1 model -> docs/api.md\n{definition}\n".encode()
    (item,) = references(name, raw)
    assert item.id == "model" and item.line == 2
    assert raw[item.start : item.end].decode() == item.text
    assert item.digest == hashlib.sha256(raw).hexdigest()


def test_strings_are_not_comments() -> None:
    """
    Ignore fake directives inside strings and multiline docstrings.

    Returns:
        None: Only the actual source comment is admitted.
    """
    source = b'"""\n# docref:1 fake -> bad.md\n"""\ns = "# docref:1 fake -> bad.md"\n'
    assert references("a.py", source) == ()
    assert references("a.ts", b"const x = `// docref:1 fake -> bad.md`;") == ()
    assert references("guide.md", b"```python\n# docref:1 fake -> bad.md\n```") == ()


@pytest.mark.parametrize(
    "comment",
    [
        "# docref:2 model -> docs/api.md\nclass X: pass\n",
        "x = 1 # docref:1 model -> docs/api.md\nclass X: pass\n",
        "# docref:1 model -> ../outside.md\nclass X: pass\n",
        "# docref:1 model -> docs/api.md docs/api.md\nclass X: pass\n",
        "# docref:1 model -> docs/api.md\n\nclass X: pass\n",
        "# docref:1 model -> docs/api.md\n# another comment\nclass X: pass\n",
        "# docref:1 model -> docs/api.md\n",
    ],
)
def test_invalid_declarations(comment: str) -> None:
    """
    Refuse ambiguous metadata instead of silently binding it elsewhere.

    Args:
        comment (str): Invalid fixture declaration.

    Returns:
        None: Every malformed declaration fails.
    """
    with pytest.raises(ValueError):
        references("a.py", comment.encode())


def test_moves_and_idempotence() -> None:
    """
    Follow a stable ID after a source move while preserving authored prose.

    Returns:
        None: Both path and line move, and repeated generation is unchanged.
    """
    raw = b"# docref:1 model -> docs/api.md\nclass Model: pass\n"
    document = b"# API\n\nRead [`Model`][code:model].\n"
    original = {"pkg/a.py": raw, "docs/api.md": document}
    updated = updates(original)
    assert b"../pkg/a.py#L2" in updated["docs/api.md"]
    assert original["docs/api.md"] == document
    assert updates({**original, **updated}) == {}
    moved = {"pkg/new/b.py": b"# heading\n" + raw, **updated}
    output = updates(moved)["docs/api.md"]
    assert b"../pkg/new/b.py#L3" in output and output.startswith(document)
    with pytest.raises(ValueError, match="Duplicate"):
        discover({"a.py": raw, "b.py": raw})
    with pytest.raises(ValueError, match="Removed"):
        updates(updated)


def test_missing_unused_and_fenced_consumers() -> None:
    """
    Require a real consumer link instead of a convincing code example.

    Returns:
        None: Missing and unused references fail without changing any input.
    """
    raw = b"# docref:1 model -> docs/api.md\nclass Model: pass\n"
    with pytest.raises(ValueError, match="Missing"):
        updates({"a.py": raw})
    for document in (b"No links.\n", b"```md\n[Model][code:model]\n```\n"):
        with pytest.raises(ValueError, match="Unused"):
            updates({"a.py": raw, "docs/api.md": document})
    fenced = f"```md\n{BEGIN}\n{END}\n```\n"
    assert render("example.md", fenced, ()) == fenced


def test_preserve_authored_content() -> None:
    """
    Refuse to erase unexpected prose placed in a managed block.

    Returns:
        None: The user must resolve the ambiguity explicitly.
    """
    with pytest.raises(ValueError, match="Authored"):
        render("doc.md", f"{BEGIN}\nPrivate note\n{END}\n", ())


def test_unicode_offsets() -> None:
    """
    Bind UTF-8 byte offsets independently of lexer character offsets.

    Returns:
        None: Non-ASCII preceding text does not shift the retained evidence.
    """
    raw = "# café\n# docref:1 model -> docs/api.md\nclass Model: pass\n".encode()
    (item,) = references("a.py", raw)
    assert raw[item.start : item.end].decode() == item.text and item.line == 3


def test_cli_rejects_non_repository(tmp_path: Path) -> None:
    """
    Keep operational failures explicit without creating repositories or writing outputs.

    Args:
        tmp_path (Path): Empty temporary directory.

    Returns:
        None: An invalid workspace returns a nonzero diagnostic status.
    """
    assert main(["--repo", str(tmp_path), "--check"]) == 2


def test_direct_links_cannot_replace_declared_reference() -> None:
    """
    Require each reserved reference label even if a different link reaches the same line.

    Returns:
        None: Coincidentally equal URLs do not satisfy the explicit consumer contract.
    """
    declaration = references("a.py", b"# docref:1 model -> doc.md\nclass Model: pass\n")
    with pytest.raises(ValueError, match="Unused"):
        render("doc.md", "[Other](a.py#L2) and [Model][code:typo].\n", declaration)
    with pytest.raises(ValueError, match="Unresolved"):
        render("doc.md", "[Model][code:model] and [Missing][code:missing].\n", declaration)


def test_byte_budget_and_symlink(tmp_path: Path) -> None:
    """
    Bound file reads and refuse tracked aliases before the compiler writes anything.

    Args:
        tmp_path (Path): Disposable repository used only for this boundary test.

    Returns:
        None: Low budgets and symlink escapes fail visibly.
    """
    import subprocess

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    source = tmp_path / "a.py"
    source.write_text("class Model: pass\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    assert main(["--repo", str(tmp_path), "--max-bytes", "1"]) == 2
    source.unlink()
    source.symlink_to(tmp_path / ".git" / "HEAD")
    assert main(["--repo", str(tmp_path), "--write"]) == 2


def test_explicit_comment_enrollment() -> None:
    """
    Insert the declared source comment and its links together, refusing string positions and duplicate IDs.

    Returns:
        None: Enrollment remains explicit, deterministic and reviewable.
    """
    sources = {"a.py": b"class Model: pass\n", "doc.md": b"Read [Model][code:model].\n"}
    changes = declare(sources, "a.py", 1, "model", ["doc.md"], "#")
    assert changes["a.py"].startswith(b"# docref:1 model -> doc.md\n")
    assert b"a.py#L2" in changes["doc.md"] and updates({**sources, **changes}) == {}
    assert sources["a.py"] == b"class Model: pass\n"
    with pytest.raises(ValueError, match="already exists"):
        declare({**sources, **changes}, "a.py", 2, "model", ["doc.md"], "#")
    with pytest.raises(ValueError, match="not recognized"):
        declare({**sources, "a.py": b'"""\ntext\n"""\n'}, "a.py", 2, "model", ["doc.md"], "#")


@pytest.mark.parametrize("suffix", ["md", "MD", "Md", "markdown", "MARKDOWN", "MarkDown"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_crlf_and_markdown_suffixes(suffix: str, newline: str) -> None:
    """
    Preserve native source offsets and detect removed anchors across document suffixes.

    Args:
        suffix (str): Supported Markdown extension, preserving case.
        newline (str): Native source and document line ending.

    Returns:
        None: Native line endings do not corrupt IDs or conceal dangling references.
    """
    consumer = f"docs/API.{suffix}"
    raw = f"# docref:1 model -> {consumer}{newline}class Model: pass{newline}".encode()
    (reference,) = references("model.py", raw)
    assert reference.line == 2 and raw[reference.start : reference.end].decode() == reference.text
    sources = {"model.py": raw, consumer: f"[Model][code:model]{newline}".encode()}
    changed = updates(sources)
    assert b"model.py#L2" in changed[consumer]
    assert sources["model.py"] == raw
    assert updates({**sources, **changed}) == {}
    with pytest.raises(ValueError, match="Removed"):
        updates(changed)
