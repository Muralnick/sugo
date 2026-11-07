# ADR-061: Start workers so a user install can find Sugo

**Status:** Accepted (maintainer decision, 2026-11-07)
**Date:** 2026-11-07
**Deciders:** project author
**Amends:** ADR-043 and ADR-054 (how the PDF and Office workers are started)
**Adds dependencies:** none

## Context

ADR-043 and ADR-054 start each worker as `python -I -m <module>`. Python's isolated mode `-I` is the sum of three switches: `-E` ignores `PYTHON*` environment variables, `-P` does not put the current folder on the import path, and `-s` leaves out the user's own site-packages.

On 2026-11-07 the maintainer installed Sugo with `pip install --user`, which puts it in the user's site-packages (`%APPDATA%\Python\Python3XX\site-packages` on Windows). pip does the same on its own on Windows when the user has no admin rights ("Defaulting to user installation"). The main process ran, but every worker failed: with `-s` the worker could not import Sugo, so every PDF ended with `PDF_EXTRACTION_FAILED` and every Office file with `OFFICE_EXTRACTION_FAILED`. Version 0.1.1 has the same fault.

## Decision

Workers start with `-E -P`, plus `-s` unless this copy of Sugo is itself installed in the user's site-packages (and Python has the user site enabled). `sugo.extractors.worker.module_command` decides this from the location of Sugo's own files.

- For every other install (a virtual environment, `uv tool`, `pipx`, a system install), the flags are `-E -P -s`, which is exactly `-I`: nothing changes.
- For a user install, only `-s` is dropped. The environment and the current folder still cannot change the worker's code. The user's site-packages is a folder only that user can write, and the main process already runs Sugo and its dependencies from it, so the worker trusts nothing the main process does not already trust.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Pass Sugo's folder to the worker on `PYTHONPATH` | `-E` would ignore it; dropping `-E` would let any `PYTHON*` variable change the worker |
| Always drop `-s` | Loosens isolation for every install, not only the one that needs it |
| Tell users not to use `--user` | pip chooses it on its own without admin rights; users would see every PDF fail |

## Consequences

- PDF and Office conversion work for `pip install --user` installs.
- A test plants a fake `sugo` in the current folder and on `PYTHONPATH` and checks that the worker imports the real one, with and without a user install.
- Residual: with a user install, other packages in the user's site-packages can be imported by the worker, as they already can by the main process.
