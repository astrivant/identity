# Link documentation to code

Make a type name clickable where readers first need its contract. Use compact
superscript references for supporting explanations that would interrupt the main
sentence. A reference should land on the relevant section, definition or footnote,
not just the repository home page.

For example, write `a reviewed source binding<sup>[\[1\]](guide.md#bindings)</sup>`.
Reuse the same number for the same destination within a document and number
references in order of first appearance. Use a Markdown footnote when the extra
explanation belongs in this document. Keep essential operating instructions in
the main text. Check the rendered link, superscript and footnote on the target host.

## Source comments and consumers

A short source comment makes the relationship travel with the code:

```python
# docref:1 intent.state -> docs/intent-graphs.md
@frozen
class State:
    ...
```

The versioned dialect is `docref:1 ID -> CONSUMER [CONSUMER ...]`. IDs are stable,
repository-local lowercase identifiers using letters, digits, dots, underscores
and hyphens. Consumers are canonical repository-relative Markdown paths. Move the
comment with its definition; retain the ID through file moves and symbol renames.
Add a short ordinary intent comment elsewhere if a non-obvious reason needs prose.
The marker itself declares that the named document describes this code.

Use the language's single-line comment syntax: `#`, `//`, `--` or `;`. A builtin
[Pygments lexer](https://pygments.org/docs/api/#lexers) must recognize the complete
line as a comment. Quoted strings, Python docstrings and Markdown examples are
not declarations. This is a common dialect, not a new language parser. Unsupported
lexers and malformed declarations fail validation; multiline comment forms are
not supported. Put the marker immediately before the declaration or its decorator.
The compiler links that next line; it does not claim to prove the symbol's meaning.

In the named consumer, write a reference link such as
``[`State`][code:intent.state]``. The compiler owns only its delimited reference
block. It resolves the stable ID to the current source file and line, keeping the
surrounding prose intact. Relative GitHub links resolve at the revision being
viewed, so code moves and documentation updates can be reviewed in one commit.
Use immutable commit permalinks separately when citing historical evidence.

When an admitted Intent Graph prepares a draft, these same comments become exact
`intent_declaration` evidence. Each document becomes an inferred consumer assertion
with a dependency on the source anchor. The `affected` query traverses those edges;
source changes require fresh bindings and review. Source comments cannot approve
claims, grant permissions, run commands or count as semantic reading.

The declaration stays within one repository and its existing protected graph scope.
External links and cross-project dependencies remain explicitly reviewed evidence;
this compiler does not fetch or edit another repository. It updates navigation,
not explanatory prose. A valid link does not establish that the explanation is current.

## Regenerate and check

Use the locked project environment from an existing checkout:

```bash
python scripts/documentation/source-links.py --write
python scripts/documentation/source-links.py --check
```

To enroll another reference, add its Markdown reference label, then select the
source line and its language's comment prefix explicitly:

```bash
python scripts/documentation/source-links.py --write --declare pkg/example.py \
  --line 10 --id example.model --consumer docs/example.md --comment-prefix '#'
```

This inserts the source comment and generates the document links in one reviewed
change. It refuses duplicate IDs and insertion into quoted strings. The selected
line remains the maintainer's responsibility; no code executes to locate it.

The compiler reads tracked worktree files, including staged new files, with a
configurable aggregate `--max-bytes` budget. Stage newly created inputs before
running it. It rejects missing consumers, duplicate IDs, unsafe paths, unsupported
marked files, removed declarations and unused consumer links. Review its changes
and stage them explicitly. It never stages, commits, publishes or contacts a service.

The same check runs in pre-commit and CI. When a definition or document moves,
update the source comment's consumer path if needed, run the compiler and review
whether the surrounding explanation also needs revision. Missing definitions
require an explicit editorial decision; the tool never guesses a replacement.
