# Vendor contract attribution

These generated snapshots retain selected responses, examples and referenced
components from vendor-owned OpenAPI descriptions. Source URLs, immutable revisions
and SHA-256 digests are recorded in [manifest.json](manifest.json).

- `github.json`: GitHub, Inc., MIT. The original notice is retained in
  [LICENSE.github](LICENSE.github).
- `gitlab.json`: GitLab Inc., documentation licensed under
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  The original repository licensing notice is retained in [LICENSE.gitlab](LICENSE.gitlab).
  The extracted GitLab snapshot remains under CC BY-SA 4.0.

Modifications: extraction of selected success-response definitions and their local
reference closure, JSON serialization and regrouping under named test operations.
Example email addresses are replaced with reserved synthetic addresses. Schema
constraints and other example values are preserved. Scenario overrides
live in the tests, not these snapshots. Regeneration and verification are described
in [the contract-testing guide](../../../../docs/provider-contracts.md).
