FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS sdk

# The npm release is a CLI shim. Build the Node API from the reviewed immutable source and its own lock.
ADD --checksum=sha256:f988c6ffd176bad830471d384b9a4b1d54f0c329e353228e276c722a2df2921d https://codeload.github.com/colbymchenry/codegraph/legacy.tar.gz/4727a068e484dd99c1ea58a8abda1a394213040b /tmp/source.tar.gz
WORKDIR /opt/codegraph
RUN tar -xzf /tmp/source.tar.gz --strip-components=1 \
    && npm ci --ignore-scripts --no-audit --no-fund \
    && npm exec -- tsc \
    && mkdir -p dist/db dist/extraction/wasm \
    && cp src/db/schema.sql dist/db/ \
    && cp src/extraction/wasm/*.wasm dist/extraction/wasm/ \
    && npm prune --omit=dev --ignore-scripts --no-audit --no-fund

FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/codegraph
COPY --from=sdk /opt/codegraph/dist ./dist
COPY --from=sdk /opt/codegraph/node_modules ./node_modules
COPY --from=sdk /opt/codegraph/package.json /opt/codegraph/LICENSE ./
COPY worker.mjs ./worker.mjs
ENV DO_NOT_TRACK=1 CODEGRAPH_TELEMETRY=0 HOME=/work TMPDIR=/work \
    CODEGRAPH_PARSE_POOL_SIZE=1 CODEGRAPH_RESOLVER_POOL_SIZE=1
USER node
WORKDIR /work
ENTRYPOINT ["/usr/bin/tini", "-g", "--"]
CMD ["/usr/bin/timeout", "--signal=TERM", "--kill-after=5", "60", "node", "/opt/codegraph/worker.mjs"]
