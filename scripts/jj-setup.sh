#!/usr/bin/env bash
# Make this checkout a colocated jj + git repo and install the repo's jj config.
# Idempotent: safe to run on every session start.
# 0.47.0 crashes on every command in the cloud container (revset alias "stack limit
# reached" then a panic), so the pin stays on 0.46.0 until a newer release is checked.
set -euo pipefail

JJ_VERSION="${JJ_VERSION:-0.46.0}"
root="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v jj >/dev/null 2>&1; then
    tmp="$(mktemp -d)"
    url="https://github.com/jj-vcs/jj/releases/download/v${JJ_VERSION}/jj-v${JJ_VERSION}-x86_64-unknown-linux-musl.tar.gz"
    curl -fsSL "$url" | tar xz -C "$tmp" ./jj
    install -m 755 "$tmp/jj" /usr/local/bin/jj
    rm -rf "$tmp"
fi

cd "$root"
if [ ! -d .jj ]; then
    jj git init --colocate >/dev/null
fi
cp jj-config.toml "$(jj config path --repo)"
jj bookmark track main --remote=origin >/dev/null 2>&1 || true
jj --version
