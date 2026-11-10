# Sugo's MCP server in a container (ADR-065).
#
#   docker build -t sugo .
#   docker run -i --rm -v ~/Documents:/data:ro sugo
#
# The agent can read only the folder mounted at /data. Base images are pinned
# by digest; every Python package comes from uv.lock with its hash.

# --- build stage ----------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS build

COPY --from=uv /uv /usr/local/bin/uv

# Use the base image's Python, never a downloaded one; copy files into the
# environment instead of linking to uv's cache, which is not kept.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/sugo

WORKDIR /src

# Dependencies first, so a source change does not download them again.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-editable --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# --- final stage ----------------------------------------------------------------
FROM python:3.12.15-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

LABEL org.opencontainers.image.title="Sugo" \
      org.opencontainers.image.description="Local, offline conversion of PDFs, Office files and screenshots into compact Markdown, as an MCP server." \
      org.opencontainers.image.source="https://github.com/Muralnick/sugo" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# An unprivileged user with a home for Sugo's page cache; /data is where the
# user mounts the folder the agent may read.
RUN groupadd --gid 10001 sugo \
    && useradd --uid 10001 --gid sugo --create-home --shell /usr/sbin/nologin sugo \
    && mkdir /data

COPY --from=build /opt/sugo /opt/sugo

ENV PATH=/opt/sugo/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER sugo
WORKDIR /home/sugo

ENTRYPOINT ["sugo", "mcp"]
CMD ["--root", "/data"]
