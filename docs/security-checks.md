# Security checks

The main CI workflow runs **Trivy security scan** alongside tests and PII scanning
on pull requests, main pushes, and version tags. Release publication and private
collection decryption depend on it. The repository settings require that check;
GitHub must apply those settings for branch protection to enforce it remotely.

Trivy scans filesystem dependencies and secret patterns. All reported findings,
invalid reports, and scanner errors fail the job. Repository-provided ignore files,
scanner configuration, and custom secret rules are disabled. The checkout is
read-only, and the scan does not receive collection or publication secrets.

Only vulnerability databases are cached, under an exact six-hour window key with
no stale fallback. Raw reports and scanner diagnostics can contain secrets; they
stay in a private memory directory with swap disabled and are deleted on exit.
The job prints a sanitized summary. Its seven-day artifact retains only allowlisted
finding metadata, never matched values, source snippets, or arbitrary scanner
metadata. It is a complete list of retained findings, not the original raw report.

A separate job in the same pipeline uses default-branch code to post a concise PR
summary and artifact link. It alone receives comment-write permission. Fork and
Dependabot PRs use the check summary and report artifact because their tokens lack
comment-write permission; there is no privileged `pull_request_target` fallback.

Trivy complements the deterministic PII scanner. Neither is encryption, neither
recognizes every secret or contextual identifier, and this filesystem scan does
not assess a running service, host, or built container. Keep reporting private if
a finding may disclose sensitive paths or package names.

## Pinned tools

The [workflow](../.github/workflows/ci.yml) is the authoritative source for
Trivy's image version, OCI digest, cache key, and action commit pins. Update the
related image and cache settings together after reviewing the
[upstream release notes](https://github.com/aquasecurity/trivy/releases).
The report sanitizer is adapted from Resumeme; its attribution is kept beside
[the script](../scripts/ci/checks/trivy-report.py).
