# Keep the interpreter identical across dependency installation and execution.
FROM python:3.14.7-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VIRTUAL_ENV=/opt/sapience
ENV PATH="/opt/sapience/bin:$PATH"

FROM base AS dependencies
WORKDIR /build
RUN python -m venv /opt/poetry && /opt/poetry/bin/pip install --no-cache-dir poetry==2.5.1     && python -m venv /opt/sapience
COPY pyproject.toml poetry.lock ./
RUN /opt/poetry/bin/poetry install --only main --extras postgres --no-root --no-interaction
COPY README.md LICENSE ./
COPY pkg ./pkg
RUN /opt/poetry/bin/poetry build --format wheel     && pip install --no-deps dist/*.whl

FROM dependencies AS development
RUN /opt/poetry/bin/poetry install --extras postgres --no-root --no-interaction
ENTRYPOINT ["sapience"]
CMD ["--help"]

FROM base AS production
RUN groupadd --gid 10001 sapience && useradd --uid 10001 --gid sapience --create-home sapience
COPY --from=dependencies /opt/sapience /opt/sapience
USER 10001:10001
WORKDIR /home/sapience
ENTRYPOINT ["sapience"]
CMD ["--help"]
