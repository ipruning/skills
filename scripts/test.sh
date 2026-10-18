#!/usr/bin/env bash

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

uv run --locked pytest -q \
    tests \
    run/proxy-fleet/tests
node --test run/sub2api-admin/tests/sub2api-admin.test.js
bash run/github-runner/tests/test-github-actions-runner-removal.sh
bash ship/github-fleet/tests/test-clone-org.sh
