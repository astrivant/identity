# Review chart palette

<!-- toc:start -->

**Table of contents**

- [Review chart palette](#review-chart-palette)

<!-- toc:end -->

[pr-palette.json](pr-palette.json) caches the reviewed Astrivant colors for PR
charts. Its source is the public company logo, recorded with a content digest
and review date so renderers can reuse the choice without fetching it again.

Muted slate and sage carry the logo's navy and green. Brick red, ochre yellow and
clay orange extend the categorical series; these accents are presentation choices,
not additional colors sampled from the logo. Dark text, slice boundaries and
explicit labels keep the plots readable without relying on color alone.

Matplotlib consumers should load `foreground`, `background` and `series` from this
file within their figure or style context. Keep generated charts with their diff
receipts on the review artifact branch, separate from these maintained style
inputs. A palette change requires a refreshed figure and receipt.
