# Runtime image for the API.
#
# Built for **linux/arm64**, because Oracle's Always Free tier is Ampere ARM.
# Every dependency here ships aarch64 wheels, so nothing compiles from source —
# but if you swap in a package that does, an ARM build is where you will find
# out.
#
# Multi-stage: the build stage carries uv and the lockfile, the final stage
# carries only the virtualenv and the application. That keeps the shipped image
# free of build tooling, which is both smaller and a smaller attack surface.

# --- build -------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies are installed before the application is copied, so a code change
# does not invalidate the dependency layer.
# README.md is copied because pyproject declares `readme = "README.md"`, and
# hatchling refuses to build the project without it. CI caught this on the
# first ARM build; it is invisible until the project itself is installed.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# `--no-dev` also drops the `kb` extra (beautifulsoup4, lxml, pyyaml). Those are
# scraper-only: the knowledge base is pre-built and committed, so the running
# service never parses HTML.
COPY backend ./backend
COPY knowledge-base/knowledge_base.xml ./knowledge-base/knowledge_base.xml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# --- runtime -----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Runs as a non-root user. Nothing here needs privilege, and a container escape
# from an unprivileged process is a much smaller problem.
RUN groupadd --system --gid 1001 burj \
    && useradd --system --uid 1001 --gid burj --create-home burj

WORKDIR /app

COPY --from=builder --chown=burj:burj /app/.venv /app/.venv
COPY --from=builder --chown=burj:burj /app/backend /app/backend
COPY --from=builder --chown=burj:burj /app/knowledge-base /app/knowledge-base

# Put the virtualenv first on PATH so `uvicorn` resolves without `uv run`,
# which would add a resolver step to every container start.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER burj
EXPOSE 8000

# Readiness, not liveness: /ready inspects the knowledge base, so a container
# that booted with an unusable corpus is reported unhealthy rather than sitting
# there answering every question with the fallback.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=4).status==200 else 1)"

# `create_app` as a factory — there is deliberately no module-level `app`, so
# importing the module never runs settings validation.
CMD ["uvicorn", "app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
