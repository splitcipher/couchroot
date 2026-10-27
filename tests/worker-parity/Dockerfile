# Disposable ARM64 test environment; not part of the TV package.
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS protocol
FROM debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    build-essential python3 libjson-c5 libssl3 libicu72 util-linux mount \
    && rm -rf /var/lib/apt/lists/*
COPY --from=protocol /usr/local/bin/node /usr/local/bin/node
