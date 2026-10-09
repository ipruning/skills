#!/usr/bin/env bash
# 把一个 GitHub 用户或组织的全部仓库浅克隆到一个镜像目录，已有的拉到默认分支最新。

set -euo pipefail

usage() {
    cat <<'EOF'
用法：bash clone-org.sh <owner> <root> [--user <login>] [--jobs <n>] [--include-archived]

把 <owner> 下所有非空仓库的默认分支浅克隆（--depth 1）到 <root>/<repo>，
已存在的目录 fetch 后 reset --hard 到远端默认分支最新提交。

<root> 是只读扫描用的缓存，不是开发目录：脚本会丢弃里面的本地改动。
首次运行要求 <root> 不存在或为空，并写入 <root>/.fleet-mirror 记录 owner；
之后只接受同一 owner 的标记目录。

  --user <login>      用这个已登录的 gh 账号取 token（只经环境变量传给 git）
  --jobs <n>          并行数，默认 8
  --include-archived  也克隆已归档仓库（默认跳过）

输出每仓一行：cloned / updated / FAILED，以及 <root> 里已不在列表中的 stale 目录
（改名、删除、归档或变空的仓库，脚本不删）。有失败时退出码为 1。
EOF
}

owner="" root="" user="" jobs=8 archived_flag="--no-archived"
while (($#)); do
    case "$1" in
        -h | --help) usage; exit 0 ;;
        --user) user="${2:?--user 需要参数}"; shift 2 ;;
        --jobs) jobs="${2:?--jobs 需要参数}"; shift 2 ;;
        --include-archived) archived_flag=""; shift ;;
        -*) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
        *)
            if [[ -z $owner ]]; then owner="$1"
            elif [[ -z $root ]]; then root="$1"
            else echo "多余参数：$1" >&2; exit 2
            fi
            shift ;;
    esac
done
[[ -n $owner && -n $root ]] || { usage >&2; exit 2; }

marker="$root/.fleet-mirror"
if [[ -f $marker ]]; then
    [[ $(<"$marker") == "$owner" ]] || {
        echo "$root 是 $(<"$marker") 的镜像，不是 $owner 的" >&2
        exit 2
    }
elif [[ -d $root && -n $(ls -A "$root") ]]; then
    echo "$root 非空且没有 .fleet-mirror 标记，拒绝写入（它可能是开发目录）" >&2
    exit 2
else
    mkdir -p "$root"
    printf '%s\n' "$owner" >"$marker"
fi

if [[ -n $user ]]; then
    GH_TOKEN="$(gh auth token --user "$user")"
    export GH_TOKEN
fi
export GIT_TERMINAL_PROMPT=0

list="$(mktemp)"
log="$(mktemp)"
trap 'rm -f "$list" "$log"' EXIT

# shellcheck disable=SC2086 # archived_flag 为空时不传
gh repo list "$owner" --limit 10000 $archived_flag \
    --json name,url,isEmpty,defaultBranchRef \
    --jq '.[] | select(.isEmpty | not) | [.name, .url, .defaultBranchRef.name] | @tsv' >"$list"

sync_one() {
    local name="$1" url="$2" branch="$3" dir="$ROOT/$1"
    local -a git=(git -c credential.helper= -c 'credential.helper=!gh auth git-credential')
    local err
    if [[ -d $dir/.git ]]; then
        if err="$("${git[@]}" -C "$dir" remote set-url origin "$url" 2>&1 &&
            "${git[@]}" -C "$dir" fetch --quiet --depth 1 origin "$branch" 2>&1 &&
            git -C "$dir" reset --quiet --hard FETCH_HEAD 2>&1 &&
            git -C "$dir" clean -qfdx 2>&1)"; then
            echo "updated $name $(git -C "$dir" rev-parse --short HEAD)"
        else
            echo "FAILED $name: ${err//$'\n'/ }"
        fi
    else
        rm -rf "$dir"
        if err="$("${git[@]}" clone --quiet --depth 1 --branch "$branch" "$url" "$dir" 2>&1)"; then
            echo "cloned $name $(git -C "$dir" rev-parse --short HEAD)"
        else
            echo "FAILED $name: ${err//$'\n'/ }"
        fi
    fi
}
export -f sync_one
export ROOT="$root"

[[ -s $list ]] && tr '\t' '\n' <"$list" | xargs -n 3 -P "$jobs" bash -c 'sync_one "$@"' _ | tee "$log"

for dir in "$root"/*/; do
    [[ -d $dir ]] || continue
    name="$(basename "$dir")"
    cut -f1 "$list" | grep -qxF "$name" || echo "stale $name"
done

failed="$(grep -c '^FAILED ' "$log" || true)"
echo "repos: $(wc -l <"$list" | tr -d ' '), failed: $failed"
[[ $failed == 0 ]]
