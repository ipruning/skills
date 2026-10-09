#!/usr/bin/env bash

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uv run --locked pytest -q \
    tests \
    skills-beta/maintaining-github-repository-fleets/tests \
    skills-stable/operate-proxy-fleet/tests
node --test skills-stable/sub2api-admin/tests/sub2api-admin.test.js
bash skills-stable/github-runner/tests/test-github-actions-runner-removal.sh
