# ADR-065: A minimal container image for the MCP server

**Status:** Accepted (maintainer decisions A, B and C, 2026-11-10)
**Date:** 2026-11-10
**Deciders:** project author
**Builds on:** ADR-033 (distribution and supply chain), ADR-049 and ADR-053 (MCP server), ADR-060 (MCP Registry package)
**Adds:** `Dockerfile`, `.dockerignore`, a CI job that builds the image and lists the MCP tools
**Adds dependencies:** none in the Python package; the image is built `FROM` two pinned images (Python, uv)

## Context

Glama (glama.ai) is a public directory of MCP servers, and the `awesome-mcp-servers` list (pull request #18625) now accepts only servers that Glama lists with a passing score. Glama's published methodology (glama.ai/mcp/methodology, read 2026-11-10) says it:

- clones the repository and builds each server from a Dockerfile, the maintainer's or one it infers itself; a server whose build fails stays hidden from search;
- runs the image in an isolated microVM and calls `tools/list`, `resources/list` and `prompts/list`;
- watches the process for credential access and network connections it did not expect, and rescans after every commit.

Sugo has no Dockerfile. Letting Glama infer one means an image nobody here has read, built from unpinned packages. ADR-033 and ARCHITECTURE §§ distribution and release already plan signed Docker images on GHCR, one per level, for amd64 and arm64; that is a larger piece of work (signing, SBOM, multi-architecture builds, publishing) and is not needed for this listing.

## Decision

A single `Dockerfile` that builds the MCP server from the checked-out source, with every Python package fixed by `uv.lock`, and that publishes nothing.

1. **Base images pinned by digest.** `python:3.12.15-slim-trixie` (Debian; 3.12.16 was under 14 days old) and the `uv` image, each as `name:tag@sha256:…`, so a rebuild cannot silently pull different bytes. The `uv` version matches CI. No `apt-get install`: the wheels Sugo needs (PyMuPDF, ONNX Runtime, OpenCV *headless*, Pillow, numpy) carry their own native libraries.
2. **Two stages.** The first stage copies the source and runs `uv sync --locked --no-dev --no-editable`: hashes come from `uv.lock`, and the build fails if the lock is out of date. Python is the base image's (`UV_PYTHON_DOWNLOADS=never`). Sugo itself is built in a second `uv sync --offline`: the build backend `uv_build` is not in `uv.lock`, but uv uses its built-in copy, and `--offline` makes the build fail rather than fetch it unpinned if that ever changes. The second stage copies only the virtual environment; `uv`, the source tree and the tests are not in the final image.
3. **Runs as an unprivileged user** (fixed UID 10001, no shell login). Docker keeps the host owner on mounted files, so the documented command adds `--user "$(id -u):$(id -g)"`: the server then reads the user's private files as the user. The page cache is `ephemeral` (ADR-045: a temporary folder deleted after each document), set in a configuration file found through `XDG_CONFIG_HOME=/etc/sugo` because the MCP server reads only the user configuration file (ADR-051); no document text stays in the container, and any UID works.
4. **One command:** `sugo mcp --root /data`. `/data` is an empty folder in the image; a user mounts the folder the agent may read there, read-only: `docker run -i --rm --network none --user "$(id -u):$(id -g)" -v ~/Documents:/data:ro sugo`. Every MCP protection (ADR-049, ADR-053) applies unchanged inside the container. Stdio transport, as in `server.json`.
5. **No network at run time is needed**: conversion never uses it (PRINCIPLES), which is what Glama's network watch will see. The documented command and the CI job both use `--network none`. The build itself downloads packages (only the pinned ones).
6. **`.dockerignore`** keeps `.git`, `.venv`, caches, the test corpus and local files out of the build context.
7. **CI job `container`** on Linux: builds the image and sends `initialize`, `tools/list`, `resources/list` and `prompts/list` over stdio (`scripts/container/mcp_probe.py`), checking that both tools answer, that the other two lists get an answer (a JSON-RPC "method not found" error, since Sugo has neither and does not declare them) and that the server exits cleanly. Not a required check at first, like `windows` was (see decision C).
8. **Not done here:** publishing images (GHCR), signing them, SBOM for the image, arm64 builds, levels other than `lite`. Those stay in ADR-033's plan for a later ADR.

### Maintainer decisions (2026-11-10)

- **A. Where the image's Sugo comes from: option 1.** (1, chosen) The checked-out source with `uv.lock`: Glama scans each commit, so the image matches what it scans, and no release coupling is needed. (2) The PyPI release `sugo-cli==X` with hashes: the same files users install, but each release would need a new hash written into the repository after publishing.
- **B. Where the Dockerfile lives: option 1.** (1, chosen) `Dockerfile` at the repository root, where Glama and other tools look first; the `docker/` folder in the ARCHITECTURE layout stays for the future per-level images. (2) `docker/Dockerfile`, as in the layout, if Glama lets the path be set.
- **C. The CI job: option 1.** (1, chosen) On every push and pull request, not required at first; required once it has run green a few times. (2) No CI job; the image is checked only by Glama.

## Alternatives considered

| Alternative | Why not |
|---|---|
| Let Glama infer a Dockerfile | Unreviewed, unpinned, may fail; the listing would be hidden |
| Install with `pip install -r requirements.txt` exported from the lock | A second copy of the lock to keep in step; `uv sync --locked` reads `uv.lock` directly |
| Alpine or distroless base | Many wheels used here are built for glibc (manylinux); Alpine would compile them from source. Distroless has no pinned Python 3.12 image we already trust |
| Full signed GHCR images now | Much more work, not needed for the listing; planned by ADR-033 |

## Consequences

- Glama can build and list Sugo, and the awesome-mcp-servers pull request can carry its badge.
- People can run the MCP server with Docker or Podman without installing Python.
- The image is about the same size as the install (~400 MB of packages plus the Python base).
- Base image digests age: Debian security fixes arrive only when the digests are updated. Until a later ADR adds automated updates, they are refreshed by hand at each release (release checklist).
- Residual: Glama's exact build form was read from its documentation and third-party notes, not yet exercised; the first build may need small changes. Glama may wrap stdio servers in its own proxy; nothing in Sugo depends on that.

## Amendment (2026-11-10): what Glama actually builds

On first use, Glama's admin page did not build the repository's `Dockerfile`. It generates its own from a build form: `debian:trixie-slim`, Node.js for its `mcp-proxy` wrapper, `uv` and a Python version installed from the internet, then `git clone` of the repository at a commit. The form is filled with Python `3.12`, the build step `uv sync --locked --no-dev --no-editable` (packages still come from `uv.lock` with hashes) plus `mkdir -p /data`, and the command `/app/.venv/bin/sugo mcp --root /data`, with no environment variables and no placeholder parameters.

So Glama's image is Glama's, built on its infrastructure with its own installers; the repository's `Dockerfile` is not what it runs. The `Dockerfile`, its rules and the `container` CI job stay: they are what people running Sugo in Docker or Podman use, and the CI probe still checks the same MCP answers Glama asks for. The repository also gets a `glama.json` naming its maintainer, which Glama's listing asks for.
