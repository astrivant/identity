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
Muted principal-axis guides mark both ends of the major and minor axes at
2.7 standard deviations from the fitted mean. Their endpoints use
`mean +/- 2.7 * sqrt(principal_variance) * principal_direction`, so they rotate
with the same covariance as the ellipses. Diamond tips mark those exact distances;
dotted leaders extend to exterior labels when needed to keep lettering clear of
the bubbles. The viewport expands to include them without changing the fitted
distribution, bubble selection, or opacity. A single-center fit omits directional
guides because its covariance comes only from numerical regularization.
Skill labels are centered beside their vertices without background
boxes. The renderer measures full names, wraps at word boundaries, and packs text
inside its parent circle, reserving the mean marker and each discipline title.
It tries wide rows and compact columns before reducing type; an input that cannot
fit the bounded minimum font size fails explicitly instead of dropping labels.
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
