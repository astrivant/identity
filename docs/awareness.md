# Professional representation

Publish selected evidence figures to an existing resumeme repository, then request
an authenticated rebuild through GitHub's repository dispatch API. Source journals
remain in the collection. Figures and labels become destination-repository data.

## Purpose and interpretation

Professional representation makes your documented work and approach to problems
visible to colleagues. A resume appendix can show the skills and tools you apply,
relationships among concepts, and how documented practice changes across projects.
The same figures support personal reflection while you work with an agent.

Choose figures that answer a useful question for their audience. Usage and toolbox
plots show recorded applications; hierarchy and graph plots show curated structure;
checkpoint comparisons show changes between recorded project boundaries. Decisions
and concise rationales provide evidence for problem-solving approaches. Counts do
not measure proficiency, and missing observations are not evidence of missing ability.
This visual signature is separate from the resume's cryptographic release signature.

The collection remains useful without any figure export. All figures are disabled
by default, and enabling one never requires publishing the underlying journals.

## Package and command

The Python implementation lives in `witful.representation`: it renders selected
figures and publishes them to a professional profile or resume. Internal imports
use this package instead of `witful.awareness`. The existing `witful awareness`
command, configuration paths and Resumeme delivery protocol retain their names
so existing collections and receivers continue to work.

## Setup

Install the GitHub CLI and authenticate with `gh auth login --hostname github.com`.
A fine-grained token or GitHub App token supplied as `GH_TOKEN` needs Contents:
write on the destination repository. Cross-repository GITHUB_TOKEN access is not
automatic. This adapter supports GitHub.com only.

Configure the resume receiver on its default `main` branch first, following
[resumeme's awareness guide](https://github.com/astrivant/resumeme/blob/main/docs/awareness.md).
Its `automation.awareness.enabled` switch and allowed actor list must authorize
this sender. Its `document.appendices.awareness` settings independently select
figures for the PDF. All switches default to disabled.

Create `knowledge/awareness.json` in the existing collection:

```json
{
  "repository": "your-account/your-resume",
  "figures": ["knowledge-usage", "toolbox-use"]
}
```

```bash
witful awareness --repo ./collection build
witful awareness --repo ./collection push
```

`build` writes `.witful/awareness.json` for local review or offline transfer.
`push` regenerates from current validated sources, writes the local bundle, then
publishes it. `--config` and `--output` are collection-relative paths unless
absolute. `witful awareness schema` prints attrs-derived config and bundle schemas.
An empty selection publishes nothing and exits with an actionable error.

Supported figures are `knowledge-usage`, `knowledge-map`, `knowledge-hierarchy`,
`toolbox-use`, `problem-repertoire`, `checkpoint-transitions`, and
`checkpoint-comparisons`, plus `decision-influences` in the `life` group.
`knowledge-map` is titled "How my skills connect"; `decision-influences` is titled
"What informs my decisions" and counts direct skill and lesson references in
current accepted decisions. Revisions replace earlier counts; retired decisions
contribute none. These captions also appear in the resume appendix. Include all figures enabled in the receiver, including
employer-specific variants. Recorded counts are evidence of usage, not mastery.

## Contract and recovery

The canonical JSON bundle contains version 1 and ordered figures with `id`,
`group`, `title`, `sha256`, and base64 `png`. Only selected PNGs are included;
intermediate graph exports and journals are never transported. Limits are 2 MiB
per image and 8 MiB per bundle. Selected SVG labels are checked for known PII
patterns before export; review labels as this cannot prove anonymization.

The destination's reserved `witful-awareness` branch contains `awareness.json`.
A GitHub Contents API update compares the expected previous blob SHA, so competing
writes fail rather than overwriting each other silently. Identical data reuses its
commit. The dispatch event type is `witful-awareness`; client payload fields are
`version: 1`, the full data `commit`, and the bundle's `sha256`. No arbitrary URL
or executable path is supplied. The receiver reads only this file using trusted
main-branch code and separately verifies the authenticated sender.

Successful CLI output means GitHub accepted the dispatch, not that CI completed.
Follow the printed Actions URL. If the response is uncertain or a request failed,
retry the same push. A committed identical bundle is reused; another dispatch can
start another build. Invalid credentials or receiver settings need correction.
The resume workflow excludes transport-branch pushes to avoid a duplicate pipeline.
Existing main-branch advancement checks decide which finished PDF may publish.

The receiver commits accepted figures beside the rebuilt PDF, preserving future
builds without live access to the collection. Figure-only rebuilds reuse the saved
LinkedIn profile. Tags retain resumeme's ordinary fresh capture and signed release
flow. Hiding a figure never deletes earlier public copies or history. Read
[SECURITY.md](../SECURITY.md) before sharing personal collection projections.

## Presentation

Exported figures omit outer plot titles and question subtitles during generation.
Axis labels, legends, and evidence notes remain; standalone collection figures keep
their headings. Regenerate an older bundle to apply this behavior. The receiver
provides its own section headings and figure identifiers. See the
[working-emphasis map contract](knowledge-map.md) for bounded bubble selection,
recency weighting, deterministic placement, and retained historical evidence.
