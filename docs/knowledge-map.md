# Working emphasis and skill connections

The connection map answers: **Which areas of work are in focus, and how do they
connect?** It is a bounded view of recorded applications. The complete hierarchy,
relationship export, lessons, and historical observations remain available;
peripheral fading never means a concept was deleted or forgotten.

## Evidence and selection

Each effective task/context observation contributes once to the owning disciplines
of its explicitly named concepts and its application context. Naming both a skill
and its parent in one observation does not count twice. The latest revision of a
task/context replaces its earlier contribution to current emphasis.

Uses receive the recency weight `2 ** (-age_days / 30)`. The reference time is the
latest recorded application, not the rendering clock. A use recorded thirty days
before that reference contributes half as much as a use at the reference. All
reported outcomes count as activity; only explicitly verified reuse is colored
green in the links. Activity is not a proficiency or success score.

The map shows at most twelve disciplines, ranked by summed weighted uses, then
most recent use, then stable concept ID. The strongest emphasis is centered;
lower weights produce smaller bubbles with preferred positions farther outward.
An empty application history uses a deterministic neutral layout with an explicit
no-evidence note. No historical activity is inferred from lesson counts.

## Geometry and relationships

The bubble layout uses a fixed unit circle. A deterministic polar search places
bubbles inside it with a positive gap between every pair. If one scale cannot fit,
a bounded sequence of uniform reductions retries packing. This avoids overlaps
without random animation or an unbounded optimization loop. The Python layout
function accepts a display limit from one to twelve; the standard renderer uses
twelve to preserve more peripheral context.

Bubble opacity uses a weighted two-dimensional Gaussian over the displayed
centers. Its covariance matrix is eigendecomposed, so the ellipse may rotate
around the plot's z-axis. The opacity fall-off is spread across twice the 1.75
Mahalanobis standard-deviation distance, so peripheral bubbles remain more
visible while the configured 35% floor is retained farther out; central bubbles
remain fully opaque.
The same fitted distribution appears as a smooth, low-contrast gray field behind
the entire plot. It is a visual guide to the current discipline emphasis, not
another data series. Bubble fills remain tied to the same Gaussian distance and
fade over twice the 1.75 standard-deviation distance. A large plus marks the
weighted mean, in muted gray with a white outline. Covariance ellipses at
0.5, 1, 1.5, and 2 Mahalanobis standard deviations sit above the gradient and
below the bubbles. Half-step contours are dashed; integer contours are solid.
These are distance contours, not one-dimensional confidence percentages.
Short exterior spokes indicate both directions of the major and minor axes.
Each lies on an axis through the fitted mean and starts beyond the
2.7-standard-deviation threshold. A ray-circle intersection moves a spoke
farther out only where needed to clear an actual bubble, with a small gap.
The threshold uses `mean +/- 2.7 * sqrt(principal_variance) * principal_direction`,
so directions follow the same covariance as the ellipses. The viewport fits the
bubbles and short spokes without reserving margins for axis or distance labels.
The mean cross and its white outline rotate with the same principal directions.
There are no axis labels, center-crossing lines, long leaders, or endpoint diamonds.
The viewport expands for the annotations without changing the distribution,
bubble selection, or opacity. A single-center fit omits directional guides
because its covariance comes only from numerical regularization.
Skill labels are centered beside their vertices without background
boxes. The renderer measures full names, wraps at word boundaries, and packs text
inside its parent circle, reserving the mean marker and each discipline title.
Discipline titles share a fixed 11-point size; every skill uses 7.2 points on the
source canvas. Bubble radius and label count do not change either size. The
shared canvas provides room for dense groups; the renderer tries wide rows and
compact columns without shrinking individual labels. Inputs that cannot fit
fail explicitly instead of dropping names or changing the hierarchy typography.
Embedding the complete figure in a document scales both levels uniformly.
Relationship lines leave gaps around text, and discipline titles occupy the
highest drawing layer. Text stays fully opaque. White or dark lettering is chosen
by luminance contrast against the actual bubble fill composited over the Gaussian
field, so faded peripheral bubbles remain readable without text backplates.
Bubble selection, positions, and the existing opacity curve are unchanged. Full link kinds and weights are retained from the complete
graph: dashed links are curated relations, solid links represent containment or
observed reuse, and green identifies reuse reported as verified. Links to
offscreen disciplines remain in the complete graph export. The map reports how
many disciplines are visible.

## Resume projection

Standalone figures keep their title and question subtitle. Awareness publication
sets the renderers' `projection=True` option, which hides explicitly marked outer
headings before SVG and PNG generation and crops unused canvas. It does not erase
pixels, infer title locations, or remove axis titles, legends, or evidence notes.
The receiver owns section headings and figure identifiers. The same behavior
applies to every awareness figure family, including decisions, tools, problems,
and project checkpoints.

## Validation

Tests cover empty and large collections, deterministic layouts, viewport bounds,
nonoverlap, recency decay, once-per-ancestor counting, revision handling, and an
unchanged complete graph. Projection tests render every supported figure family,
check that outer headings are absent while data labels remain, verify repeated
PNG bytes, and exercise the privacy scan against visible labels.

## Public README example

The [README preview](../README.md#see-how-your-skills-connect) uses invented
engineering disciplines and task observations from
[`knowledge-preview.py`](../scripts/documentation/knowledge-preview.py).
It reads no collection, repository history or credentials. Fixed dates make the
working-emphasis calculation reproducible; the example is not evidence of actual
project activity or measured productivity.

From the source checkout's locked development environment:

```bash
python scripts/documentation/knowledge-preview.py --output .cache/readme-preview
cp .cache/readme-preview/knowledge-map.svg docs/assets/knowledge-map-example.svg
```

The script uses the same renderer as real collection figures and produces SVG/PNG
previews for inspection. Review the labels and layout before replacing the README
asset. The separately linked project-comparison example has its own
[source and regeneration contract](view-freshness.md).
