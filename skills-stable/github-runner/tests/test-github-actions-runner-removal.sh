#!/usr/bin/env bash

set -euo pipefail

skill_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly skill_root
readonly setup_script="$skill_root/scripts/setup-runners.sh"
readonly remove_script="$skill_root/scripts/remove-runners.sh"
readonly identity_reader="$skill_root/scripts/read-runner-identity.py"
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

expected_identity=$'ci-01\nhttps://github.com/example-org'
[[ $(python3 "$identity_reader" "$plain_file") == "$expected_identity" ]]
[[ $(python3 "$identity_reader" "$bom_file") == "$expected_identity" ]]
if python3 "$identity_reader" "$malformed_file" >"$tmp_dir/malformed.log" 2>&1; then
    echo "ERROR malformed runner JSON passed identity parsing" >&2
    exit 1
fi

# Removed public aliases must fail during parsing, before platform checks or writes.
for runner_script in "$setup_script" "$remove_script"; do
    for removed_option in --token -t; do
        status=0
        bash "$runner_script" "$removed_option" fixture >"$tmp_dir/option.log" 2>&1 || status=$?
        [[ $status -eq 2 ]]
        [[ $(<"$tmp_dir/option.log") == *"unknown option: $removed_option"* ]]
    done
    bash "$runner_script" --help >"$tmp_dir/help.log"
    [[ $(<"$tmp_dir/help.log") == *--token-file* ]]
done
status=0
bash "$setup_script" --label fixture >"$tmp_dir/option.log" 2>&1 || status=$?
[[ $status -eq 2 ]]
[[ $(<"$tmp_dir/option.log") == *"unknown option: --label"* ]]
[[ $(bash "$remove_script" --help) == *--resume-after-unregister* ]]
# A shell-only upload fails before registration or host operations.
mkdir "$tmp_dir/incomplete-scripts"
for runner_script in "$setup_script" "$remove_script"; do
    cp "$runner_script" "$tmp_dir/incomplete-scripts/"
    status=0
    bash "$tmp_dir/incomplete-scripts/${runner_script##*/}" --help >"$tmp_dir/package.log" 2>&1 || status=$?
    [[ $status -eq 1 ]]
    [[ $(<"$tmp_dir/package.log") == *"copy the entire scripts directory"* ]]
done
cp "$identity_reader" "$tmp_dir/incomplete-scripts/"
for runner_script in "$setup_script" "$remove_script"; do
    bash "$tmp_dir/incomplete-scripts/${runner_script##*/}" --help >/dev/null
done
# The supported spellings still parse without reaching host or network operations.
bash "$setup_script" --labels fixture --help >/dev/null
bash "$setup_script" -l fixture --help >/dev/null
bash "$setup_script" --token-file "$plain_file" --help >/dev/null
bash "$remove_script" --resume-after-unregister --help >/dev/null

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
