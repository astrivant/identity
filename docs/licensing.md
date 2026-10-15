# Licensing

Identity and Witful use the [Business Source License 1.1](../LICENSE)
(`BUSL-1.1`). The licensor is Astrivant LLC. The Additional Use Grant is `None`:
the license permits non-production use, and production use requires a separate
commercial license from Astrivant LLC before conversion to the Change License.

Each specific version converts to GNU General Public License version 3.0 only
(`GPL-3.0-only`) on the fourth anniversary of its first publicly available
distribution under BSL 1.1. Publishing a later version does not restart an older
version's conversion period. BSL 1.1 is a source-available license, not an
open-source license before that conversion. Earlier distributions retain the
license under which they were made available; this change does not rewrite
published tags or their license files.

The unmodified standard terms come from the [SPDX license text](https://spdx.org/licenses/BUSL-1.1.html),
originally published by [MariaDB](https://mariadb.com/bsl11/). The project-specific
parameters appear at the top of `LICENSE`. The Python distribution metadata and
Helm registry annotation use `BUSL-1.1`; the chart carries the same project license.

## Separately licensed components

The project license excludes these components, which retain their own terms and
attribution. Installing a dependency does not relicense it.

| Components | License and maintained notice |
| --- | --- |
| README contents updater adapted from Polyad | [GPL-3.0-only text](../scripts/licenses/GPL-3.0-only.txt), [attribution](../scripts/documentation/NOTICE.md) |
| Trivy report sanitizer, coverage badge script and SVG adapted from Resumeme | [GPL-3.0-only text](../scripts/licenses/GPL-3.0-only.txt), [attribution](../scripts/ci/checks/NOTICE) |
| Signing-key setup helper adapted from Resumeme | [GPL-3.0-only text](../scripts/licenses/GPL-3.0-only.txt), [attribution](../scripts/release/NOTICE.md) |
| Markdown math/Mermaid validator, its tests and ESLint configuration | [Apache-2.0 text](../scripts/documentation/broker.LICENSE), [attribution](../scripts/documentation/NOTICE.md) |
| CI quality gate and its negative-path tests | [Apache-2.0 text](../scripts/documentation/broker.LICENSE), [attribution](../scripts/ci/NOTICE.md) |
| Provider API specifications and examples | [Upstream licenses and provenance](../scripts/ci/provider_contracts/data/NOTICE.md) |
| CloudNativePG chart dependency | [Apache-2.0 text](../helm/witful/licenses/cloudnative-pg.txt) |

Preserve these notices and license texts when redistributing the corresponding
tooling or dependencies. They are not covered by the project's production-use
restriction.
