# Disposable ARM64 test environment; not part of the TV package.
FROM node:22-bookworm-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS protocol
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    build-essential python3 libjson-c5 libssl3 libicu72 util-linux mount \
    && rm -rf /var/lib/apt/lists/*
COPY --from=protocol /usr/local/bin/node /usr/local/bin/node
