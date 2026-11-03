# Host-only native regression fixtures; separate from the pinned TV toolchain.
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    gcc libc6-dev libjson-c5 openssl procps util-linux && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /src
