# Build and run on the same supported Python minor as the source checks.
FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/witful
ENV PATH="/opt/witful/bin:$PATH" \
    TMPDIR=/run/witful \
    MPLCONFIGDIR=/run/witful/matplotlib \
    XDG_CACHE_HOME=/run/witful/cache

LABEL org.opencontainers.image.title="Witful" \
    org.opencontainers.image.description="Policy and learning tools for intelligent agents" \
    org.opencontainers.image.source="https://github.com/astrivant/identity" \
    org.opencontainers.image.licenses="BUSL-1.1"

# Git/SSH support collection operations; Tini owns PID 1 and forwards process-group signals.
ARG GIT_VERSION=1:2.47.3-0+deb13u1
ARG OPENSSH_CLIENT_VERSION=1:10.0p1-7+deb13u4
ARG TINI_VERSION=0.19.0-3+b8
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        git="${GIT_VERSION}" \
        openssh-client="${OPENSSH_CLIENT_VERSION}" \
        tini="${TINI_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

# Both runnable targets share a stable unprivileged identity and private working storage.
RUN groupadd --gid 10001 witful \
    && useradd --uid 10001 --gid witful --create-home --shell /usr/sbin/nologin witful \
    && install -d -o witful -g witful -m 0700 /run/witful
STOPSIGNAL SIGTERM

FROM base AS tooling
ARG POETRY_VERSION=2.5.1
ENV POETRY_NO_INTERACTION=1 POETRY_CACHE_DIR=/var/cache/pypoetry
WORKDIR /build

# Isolate build tools from the application environment copied into production.
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/poetry \
    && /opt/poetry/bin/python -m pip install "poetry==${POETRY_VERSION}" \
    && python -m venv /opt/witful
COPY pyproject.toml poetry.lock ./

FROM tooling AS dependencies
# Source edits do not invalidate dependency installation; downloads live only in the build cache.
RUN --mount=type=cache,target=/var/cache/pypoetry \
    /opt/poetry/bin/poetry install --only main --extras "postgres native" --no-root

FROM dependencies AS wheel
COPY LICENSE ./
COPY docs/WITFUL.md ./docs/WITFUL.md
COPY pkg ./pkg
RUN /opt/poetry/bin/poetry build --format wheel \
    && python -m pip install --no-deps --no-index dist/*.whl \
    && python -m pip check

FROM dependencies AS development
RUN --mount=type=cache,target=/var/cache/pypoetry \
    /opt/poetry/bin/poetry install --extras "postgres native" --no-root
COPY --chown=10001:10001 LICENSE ./
COPY --chown=10001:10001 docs/WITFUL.md ./docs/WITFUL.md
COPY --chown=10001:10001 pkg ./pkg

# Editable installation lets a mounted source tree drive the CLI without rebuilding its wheel.
# Discard root-owned temporary installation caches before handing the image to its runtime user.
RUN /opt/poetry/bin/poetry install --only-root \
    && python -m pip check \
    && rm -rf /run/witful/* \
    && chown -R witful:witful /build /opt/witful
ENV PATH="/opt/witful/bin:/opt/poetry/bin:$PATH" \
    POETRY_CACHE_DIR=/run/witful/poetry
ARG VCS_REF
LABEL org.opencontainers.image.revision="${VCS_REF}"
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "witful"]
CMD ["--help"]

FROM base AS production
COPY --from=wheel /opt/witful /opt/witful
ARG VCS_REF
LABEL org.opencontainers.image.revision="${VCS_REF}"
USER 10001:10001
WORKDIR /home/witful
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "witful"]
CMD ["--help"]
