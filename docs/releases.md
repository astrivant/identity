# Releases

CI uses the `vMAJOR.MINOR.PATCH` tag for package metadata before building.
Independent tests, source checks, PII scanning, and orchestration must pass
before publication. The release job downloads that run's verified wheel and
source distribution; it never uses a cached distribution or rebuilds it.

Select this repository for the organization `PYPI_API_TOKEN` Actions secret.
CI exposes it only as `POETRY_PYPI_TOKEN_PYPI` in the publishing step. Configure
the `pypi` environment for the intended tag deployment policy.

With authenticated `gh`, OpenSSL, and Cosign 3.x, run the setup helper:

```bash
bash scripts/release/setup-signing.sh --repo OWNER/REPO
```

It creates local protected key backups and sets `COSIGN_PRIVATE_KEY` and
`COSIGN_PASSWORD` in the explicitly selected repository. Reuse `--key-dir PATH`
after a partial upload; do not regenerate a new identity just to retry.

Cosign 3.1.3 signs each final distribution and the SHA256SUMS manifest.
The release attaches distributions, signature bundles, public key, SHA-256
public-key fingerprint, signed manifest, and SOURCE.json provenance.
The GitHub release remains a draft until PyPI publication succeeds. Already
published GitHub releases are immutable; publish a new version for new bytes.

Compare the fingerprint through a trusted channel before verification. A hash
verifies bytes; a trusted public key establishes the signing identity. The
release notes contain the exact consumer verification commands.
