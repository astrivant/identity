# Security policy

Report vulnerabilities through [private vulnerability reporting](https://github.com/astrivant/identity/security/advisories/new).
Do not paste personal records, credentials, or private matches into public issues.
The current release line receives security fixes; update before reporting a defect.

## Publication boundary

This project contains code, schemas, and synthetic fixtures. Keep actual lessons,
decisions, prompts, tool-use records, model configuration, and generated personal
graphs in a separately controlled collection. Application users own access and
retention decisions for that collection. Sapience does not upload records to a
model or telemetry service.

`sapience privacy scan` scans tracked and nonignored untracked UTF-8 sources.
`--staged` inspects the complete Git index, so unstaged clean files cannot hide
staged sensitive content. `.git` history and ignored files are outside its scope.
The CI job scans every checked-out source file and must pass before merge/release;
pre-commit exports the same gate as `sapience-pii`. Hooks can be bypassed locally,
so repository branch protection must require **PII scan**.

## What the scanner detects

- Email-like strings, except reserved example.com/org/net, .test, and .invalid domains.
- Personal Unix/macOS/Windows home paths; generic runner/container homes are permitted.
- Common North American phone and US government-ID shapes.
- LinkedIn member profile URLs and PEM/OpenSSH private-key headers.
- Additional case-insensitive literals from `--terms-file` or `SAPIENCE_PII_TERMS_FILE`.

Keep the terms file outside public source control. Logs contain only relative
file location, line number, and detector ID. A sensitive filename becomes a
digest label. Matched values and snippets are never printed. Files larger than
5 MiB, non-UTF-8/binary files, and unreadable files block the scan; symlink targets
are inspected without following them outside the checkout.

This is a deterministic guard for defined patterns, not an identity classifier.
It cannot recognize all people's names, postal addresses, international phones,
encoded data, photographs, contextual identification, or secrets of every form.
Do not describe a passing scan as proof that a dataset is anonymized. Review
publication contents and use a dedicated secret scanner for broader credentials.
If data reaches Git history or release artifacts, removing the current text is
insufficient: revoke credentials, restrict/delete affected outputs, and assess
history rewriting and registry removal as separate recovery actions.

## Storage and network behavior

JSONL records and Life snapshots contain full supplied text and evidence.
Snapshots intentionally preserve prior records for replay; deleting current
entries does not remove their historical copies. SQLite indexes and plots can
contain the same data. Keep all of these private when they describe people.
Local atomic writes use owner-only files; directory, backup, and Git access
controls remain the operator's responsibility. Neither journals nor databases
are encrypted by this library.

PostgreSQL is explicit, uses parameterized SQL, and defaults to certificate and hostname verification; explicit URL sslmode overrides are respected.
Use distinct namespaces for logical collections; namespaces do not replace
database authorization or separate roles. Backups and replicas retain data.
Runtime database URLs belong in environment variables or Kubernetes Secrets,
never chart values. Connection errors redact endpoints and credentials.

Registry checks send candidate names to PyPI over HTTPS. The local six-hour
cache retains only name, status, check time, and cooldown, not author metadata.
Avoid confidential names; the cache is disposable. It does not reserve names.

CI runs on synthetic fixtures. PyPI and signing credentials are supplied only
to tag publication jobs. Signing happens after artifact bytes are final; use
the published fingerprint through an independently trusted channel.
