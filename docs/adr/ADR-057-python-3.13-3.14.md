# ADR-057: Support Python 3.12 to 3.14

**Status:** Proposed
**Date:** 2026-11-06
**Deciders:** project author
**Amends:** ADR-033 (release pipeline: package metadata)
**Adds dependencies:** none

## Context

`sugo-cli` 0.1.0 declares `requires-python = ">=3.12,<3.13"`. A user whose default Python is 3.13 or newer, which is the common case on a fresh machine, gets `pip` errors such as "Ignored the following versions that require a different python version" and "No matching distribution found", and may conclude the package is broken. `uv tool install` is not affected because it downloads Python 3.12 itself.

The upper bound was a precaution from the first release, not a known incompatibility: nothing in the repository documents a reason for it.

## Decision

1. Declare `requires-python = ">=3.12,<3.15"` and add the 3.13 and 3.14 classifiers. The upper bound stays, so a future Python is opted into deliberately rather than by accident.
2. Keep Python 3.12 as the **reference version**: `.python-version`, the `checks` job (lint, types, import boundaries, tests), the `windows` job, the reproducible-build check and the release pipeline stay on 3.12. The required status check `checks` keeps its name.
3. Add a CI job, `python-versions`, that runs the full test suite on 3.13 and 3.14, on Linux and on Windows. A version is supported only while this job passes.
4. Regenerate `uv.lock` for the wider range. The change must only **add** wheels for the new Python tags and environment markers; it must not change any pinned version (so the 14-day rule and the existing hashes are untouched).
5. Type checking stays at `python_version = "3.12"`, the lowest supported version.

The distribution is a pure-Python wheel (`py3-none-any`), so one wheel serves every supported version and the release build does not change.

## Consequences

- `pip install sugo-cli` works on Python 3.12, 3.13 and 3.14.
- CI gains four jobs per pull request (roughly the cost of the existing `windows` job each). CI downloads the extra Pythons with uv's managed Python installer.
- Runtime differences between Python versions (for example in the OCR or PDF stack) are caught by the test suite only where tests exist. Benchmarks are still measured on 3.12.
- If a dependency stops supporting a version, the bound is lowered in a new ADR rather than silently.

## Alternatives considered

- **Keep `<3.13` and document it.** Honest, but turns away most users with a recent Python.
- **Remove the upper bound.** Simplest, but promises support for versions nobody has tested.
