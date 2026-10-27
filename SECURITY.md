# Security policy

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository. Please do not open public issues for security problems.

Sugo is maintained by a single person. Realistic targets: acknowledgement within 7 days, an assessment within 14 days. Critical issues get an emergency release.

## Supported versions

Only the latest minor release receives security fixes.

## Scope

Sugo processes untrusted files by design. Reports about parser crashes, sandbox escapes, archive handling, path traversal, prompt-injection filtering, MCP access control, local web UI exposure, model loading and supply-chain issues are all in scope. See `docs/THREAT_MODEL.md` for the threat model and declared residual risks.

## Process

Confirmed vulnerabilities are published as GitHub Security Advisories, with a CVE when appropriate. Every fixed vulnerability adds a regression case to the security test corpus.
