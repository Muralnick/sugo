# Sugo principles

These are the promises of the official Sugo project. No configuration, profile, recipe or extension can override them. Each principle is enforced by **invariant tests** (marked `@pytest.mark.invariant`); a change that breaks one is blocked.

Sugo is open source under AGPL-3.0-or-later: anyone can fork and change anything. Forks that break these principles must not use the name "Sugo".

| # | Principle | Meaning |
|---|---|---|
| 1 | **Local processing** | Document content never leaves the machine through Sugo. Outbound internet access goes only through a single gateway, only for sources, model downloads and pack installation, and only on explicit request. Local networking (loopback servers, inter-process channels) is limited to ports and the engine (ADR-036). |
| 2 | **No telemetry** | Never, in any form. Usage statistics stay local and visible to the user. |
| 3 | **No silent loss** | Every removal has a recorded reason and can be inspected. |
| 4 | **No invented content** | Generated text is always marked with its origin. Unreadable areas are marked, never filled. |
| 5 | **Provenance** | Every chunk is traceable to its file, container and page. |
| 6 | **Reproducibility** | Same input, configuration and models produce the same output. |
| 7 | **Security floor** | Archive limits, path sanitisation, safe model formats, no macro execution and fixed exclusions for sensitive folders. Configuration can make them stricter, never weaker than the floor. |
| 8 | **Policies win** | Keys locked by an administrator cannot be overridden by users or extensions. |
| 9 | **Most protective wins** | When profiles conflict, the safer setting prevails, and the user is told. |
| 10 | **Agents do not act on the system** | Through MCP, no installs, downloads or deletions. |
| 11 | **Logs without content** | Default logs never contain document text or file names. |
| 12 | **Stable contracts** | Output formats, error codes and exit codes follow semantic versioning. |

## Changing a principle

Requires an ADR, a public discussion on GitHub and a new major version. Principles can evolve, but never silently.
