#!/usr/bin/env bash

set -euo pipefail

skill_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly skill_root
readonly setup_script="$skill_root/scripts/setup-runners.sh"
readonly remove_script="$skill_root/scripts/remove-runners.sh"
readonly deploy_doc="$skill_root/references/deploy-and-remove.md"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

plain_file="$tmp_dir/plain.runner"
bom_file="$tmp_dir/bom.runner"
malformed_file="$tmp_dir/malformed.runner"

printf '%s\n' \
    '{"agentName":"ci-01","gitHubUrl":"https://github.com/example-org"}' \
    >"$plain_file"
printf '\357\273\277%s\n' \
    '{"agentName":"ci-01","gitHubUrl":"https://github.com/example-org"}' \
    >"$bom_file"
printf '%s\n' '{"agentName":' >"$malformed_file"

read_identity() {
    local runner_file=$1
    python3 - "$runner_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as file:
    data = json.load(file)
print(data.get("agentName", ""))
print(data.get("gitHubUrl", ""))
PY
}

expected_identity=$'ci-01\nhttps://github.com/example-org'
[[ $(read_identity "$plain_file") == "$expected_identity" ]]
[[ $(read_identity "$bom_file") == "$expected_identity" ]]
if read_identity "$malformed_file" >"$tmp_dir/malformed.log" 2>&1; then
    echo "ERROR malformed runner JSON passed identity parsing" >&2
    exit 1
fi

for runner_script in "$setup_script" "$remove_script"; do
    grep -F 'with open(sys.argv[1], encoding="utf-8-sig") as file:' \
        "$runner_script" >/dev/null
done

# Portable equivalent of a noexec mount: direct execution is unavailable,
# while an explicit trusted interpreter can read a root-only helper.
helper="$tmp_dir/root-helper.sh"
printf '%s\n' '#!/usr/bin/env bash' 'printf "helper-ok\\n"' >"$helper"
chmod 0600 "$helper"
if "$helper" >"$tmp_dir/direct.log" 2>&1; then
    echo "ERROR non-executable helper unexpectedly ran directly" >&2
    exit 1
fi
[[ $(/bin/bash "$helper") == helper-ok ]]
grep -F '/bin/bash /run/<HELPER>' "$deploy_doc" >/dev/null

echo "GitHub Actions runner removal fixtures passed."
