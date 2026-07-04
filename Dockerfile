# render-engine-pg-cms container image.
#
# Version resolution: the project version is dynamic via setuptools-scm, which
# reads it from git. git is installed below so a plain `docker build .` from a
# checkout Just Works. For builds without git history (source tarballs, some
# CI), pass --build-arg VERSION=X.Y.Z to override.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# git lets setuptools-scm derive the version from the checkout at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Optional version override; empty => setuptools-scm reads it from git.
ARG VERSION=""

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN if [ -n "$VERSION" ]; then export SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION"; fi \
    && uv sync --frozen --no-dev

EXPOSE 8000

# --no-sync: the environment is already built into the image above. Without it,
# `uv run` re-syncs on every start — re-deriving the setuptools-scm version from
# the (now dirty) copied checkout and yielding a bogus .devN version at runtime.
CMD ["uv", "run", "--no-sync", "uvicorn", "render_engine_pg_cms.main:app", "--host", "0.0.0.0", "--port", "8000"]
