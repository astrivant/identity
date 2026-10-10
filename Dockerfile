# Keep the interpreter identical across dependency installation and execution.
FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VIRTUAL_ENV=/opt/witful
ENV PATH="/opt/witful/bin:$PATH"
# Reap children and forward signals in both development and production targets.
ARG TINI_VERSION=0.19.0-3+b8
RUN apt-get update && apt-get install --no-install-recommends -y tini="${TINI_VERSION}" \
    && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGTERM

FROM base AS dependencies
WORKDIR /build
RUN python -m venv /opt/poetry && /opt/poetry/bin/pip install --no-cache-dir poetry==2.5.1     && python -m venv /opt/witful
COPY pyproject.toml poetry.lock ./
RUN /opt/poetry/bin/poetry install --only main --extras postgres --no-root --no-interaction
COPY README.md LICENSE ./
COPY docs/WITFUL.md ./docs/WITFUL.md
COPY pkg ./pkg
RUN /opt/poetry/bin/poetry build --format wheel     && pip install --no-deps dist/*.whl

FROM dependencies AS development
RUN /opt/poetry/bin/poetry install --extras postgres --extras sapience --no-root --no-interaction
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "witful"]
CMD ["--help"]

FROM base AS production
RUN groupadd --gid 10001 witful && useradd --uid 10001 --gid witful --create-home witful
COPY --from=dependencies /opt/witful /opt/witful
USER 10001:10001
WORKDIR /home/witful
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "witful"]
CMD ["--help"]
