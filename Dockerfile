# One image, two services. The MCP server and the web app are the same
# codebase with different entry points, so they share a build and differ only
# by the `command:` in compose.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: pyproject and the lockfile change
# far less often than source, so this layer is reused across code edits.
# --no-install-project because the project itself is not copied yet.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# README.md is required by the build backend: pyproject declares
# `readme = "README.md"`, so installing the project itself needs it.
COPY README.md ./
COPY src/ ./src/
COPY db/  ./db/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.12-slim-bookworm AS runtime

# Not root. A container escape is worth much less as an unprivileged user,
# and nothing here needs to write to the filesystem.
RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src   /app/src
COPY --from=builder --chown=app:app /app/db    /app/db

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

# No CMD. Each service in compose states its own command, so an image with a
# default would just be a default someone forgets to override.
