FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder

# UV_COMPILE_BYTECODE speeds up container cold starts by shifting compilation to build time.
# UV_LINK_MODE=copy avoids cross-device link warnings when using Docker cache mounts.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed

# Isolates the Python installation to cache it independently of project dependencies.
RUN uv python install 3.14

WORKDIR /app

# Maximizes Docker layer caching if your source code changes but dependencies don't.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM docker.io/library/debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /python /python
COPY --from=builder /app /app

# Ensures the virtual environment's executables take precedence.
ENV PATH="/app/.venv/bin:$PATH"

# Replace 'your_app_module' with the actual package or script name.
CMD ["valerie-bot"]