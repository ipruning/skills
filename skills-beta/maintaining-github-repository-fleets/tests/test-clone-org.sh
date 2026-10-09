#!/usr/bin/env bash
# 用本地 file:// 仓库和假的 gh 验证 clone-org.sh 的克隆、更新、跳过和防误写。

set -euo pipefail

skill_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$skill_root/scripts/clone-org.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com

make_remote() {
    git init -q -b "$2" "$tmp/src/$1"
    echo v1 >"$tmp/src/$1/f.txt"
    mkdir -p "$tmp/src/$1/.github"
    echo hidden >"$tmp/src/$1/.github/ci.yml"
    git -C "$tmp/src/$1" add -A
    git -C "$tmp/src/$1" commit -qm init
}
make_remote alpha main
make_remote beta trunk

# 假的 gh：repo list 把固定 JSON 交给 --jq 表达式处理。
mkdir -p "$tmp/bin"
cat >"$tmp/bin/gh" <<GH
#!/usr/bin/env bash
[[ \$1 == repo && \$2 == list ]] || exit 1
while ((\$#)); do [[ \$1 == --jq ]] && expr="\$2"; shift; done
jq -r "\$expr" "$tmp/repos.json"
GH
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH"

cat >"$tmp/repos.json" <<JSON
[
  {"name": "alpha", "url": "file://$tmp/src/alpha", "isEmpty": false, "defaultBranchRef": {"name": "main"}},
  {"name": "beta", "url": "file://$tmp/src/beta", "isEmpty": false, "defaultBranchRef": {"name": "trunk"}},
  {"name": "empty", "url": "file://$tmp/src/empty", "isEmpty": true, "defaultBranchRef": null}
]
JSON

mirror="$tmp/mirror"
out="$(bash "$script" acme "$mirror")"
grep -q '^cloned alpha ' <<<"$out"
grep -q '^cloned beta ' <<<"$out"
[[ ! -e $mirror/empty ]]
[[ $(<"$mirror/beta/f.txt") == v1 ]]
[[ $(git -C "$mirror/alpha" rev-list --count HEAD) == 1 ]]

# 远端前进、镜像里有本地改动和多余目录：更新到远端最新，报告 stale。
echo v2 >"$tmp/src/beta/f.txt"
git -C "$tmp/src/beta" commit -qam v2
echo junk >"$mirror/alpha/f.txt"
mkdir "$mirror/renamed-away"
out="$(bash "$script" acme "$mirror")"
grep -q '^updated beta ' <<<"$out"
grep -q '^stale renamed-away$' <<<"$out"
[[ $(<"$mirror/beta/f.txt") == v2 ]]
[[ $(<"$mirror/alpha/f.txt") == v1 ]]

# 失败的仓库让退出码非零。
rm -rf "$tmp/src/alpha" "$mirror/alpha"
if bash "$script" acme "$mirror" >"$tmp/fail.log"; then
    echo "expected failure when a repo cannot be cloned" >&2
    exit 1
fi
grep -q '^FAILED alpha:' "$tmp/fail.log"

# 不往没有标记的非空目录或别的 owner 的镜像里写。
mkdir -p "$tmp/dev/project"
if bash "$script" acme "$tmp/dev" 2>/dev/null; then exit 1; fi
if bash "$script" other "$mirror" 2>/dev/null; then exit 1; fi

echo "clone-org tests passed"
