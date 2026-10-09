#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo bash setup-runners.sh --token-file FILE [options]

Deploy GitHub.com organization-level self-hosted runners on a Linux systemd host.

Required:
  -o, --org ORG                 GitHub organization
  -n, --count N                 Number of runners, 1-50
      --drained                 Confirm same-user runners are drained and stopped

Token input (choose one):
      --token-file FILE         Read the registration token from FILE
  -t, --token TOKEN             Compatibility only; exposes TOKEN in process argv
                                prefer --token-file

Optional:
  -l, --label LABEL             One custom label; compatibility alias for --labels
      --labels LABELS           Comma-separated custom labels; defaults to hostname
  -g, --group GROUP             Runner group; defaults to Default
  -p, --prefix PREFIX           Runner name prefix; defaults to the sole label;
                                required when --labels contains several labels
  -u, --user USER               Linux service user; defaults to actions
      --runner-version VERSION  Pin actions/runner version and disable self-update;
                                default is latest with normal runner updates
      --runner-path PATH        PATH captured for runner services and jobs;
                                defaults to user-local, mise and system paths
      --accept-inherited-dropins
                                Confirm every inherited systemd drop-in was reviewed
  -y, --yes                     Skip the interactive confirmation
  -h, --help                    Show this help
EOF
}

info() { printf '>>> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_value() {
    local option_name=$1
    local option_value=${2-}
    [[ -n "$option_value" ]] || {
        printf 'ERROR: %s requires a value\n' "$option_name" >&2
        exit 2
    }
}

validate_plain_value() {
    local value_name=$1
    local value=$2
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != *$'\t'* ]] \
        || die "$value_name must not contain control characters"
}

read_runner_identity() {
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

ORG=''
COUNT=''
LABELS=''
RUNNER_GROUP='Default'
PREFIX=''
RUNNER_USER='actions'
RUNNER_VERSION=''
RUNNER_RUNTIME_PATH=''
PIN_RUNNER_VERSION=0
TOKEN=${GITHUB_RUNNER_TOKEN-}
TOKEN_FILE=''
ASSUME_YES=0
DRAINED=0
ACCEPT_INHERITED_DROPINS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--org) require_value "$1" "${2-}"; ORG=$2; shift 2 ;;
        -n|--count) require_value "$1" "${2-}"; COUNT=$2; shift 2 ;;
        -l|--label|--labels) require_value "$1" "${2-}"; LABELS=$2; shift 2 ;;
        -g|--group) require_value "$1" "${2-}"; RUNNER_GROUP=$2; shift 2 ;;
        -p|--prefix) require_value "$1" "${2-}"; PREFIX=$2; shift 2 ;;
        -u|--user) require_value "$1" "${2-}"; RUNNER_USER=$2; shift 2 ;;
        --runner-version) require_value "$1" "${2-}"; RUNNER_VERSION=${2#v}; PIN_RUNNER_VERSION=1; shift 2 ;;
        --runner-path) require_value "$1" "${2-}"; RUNNER_RUNTIME_PATH=$2; shift 2 ;;
        --token-file) require_value "$1" "${2-}"; TOKEN_FILE=$2; shift 2 ;;
        -t|--token)
            require_value "$1" "${2-}"
            TOKEN=$2
            warn '--token exposes the token in process argv; prefer --token-file'
            shift 2
            ;;
        --drained) DRAINED=1; shift ;;
        --accept-inherited-dropins) ACCEPT_INHERITED_DROPINS=1; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; [[ $# -eq 0 ]] || { printf 'ERROR: positional arguments are not supported\n' >&2; exit 2; } ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || die 'run as root'
[[ -d /run/systemd/system ]] || die 'systemd system manager is not running'

for dependency in \
    awk chmod chown curl cut env getent grep hostname install mktemp mv pgrep ps \
    python3 rm runuser sed seq sha256sum sort systemctl tar tr uname; do
    command -v "$dependency" >/dev/null 2>&1 || die "missing dependency: $dependency"
done
[[ $(uname -s) == Linux ]] || die 'this script supports Linux only'
CURL_RETRY_ARGS=(--retry 3)
if curl --retry-all-errors --version >/dev/null 2>&1; then
    CURL_RETRY_ARGS+=(--retry-all-errors)
fi

[[ -n "$ORG" ]] || die 'missing required option: --org'
[[ -n "$COUNT" ]] || die 'missing required option: --count'
[[ "$COUNT" =~ ^[0-9]+$ && "$COUNT" -ge 1 && "$COUNT" -le 50 ]] \
    || die "runner count must be an integer from 1 to 50: $COUNT"
[[ "$ORG" =~ ^[A-Za-z0-9._-]+$ ]] || die 'organization contains unsupported characters'
[[ "$RUNNER_USER" =~ ^[A-Za-z_][A-Za-z0-9_-]*[$]?$ ]] || die 'invalid Linux user name'
[[ $DRAINED -eq 1 ]] || die 'refusing deployment without --drained'

if [[ -n "$TOKEN_FILE" ]]; then
    [[ -z "$TOKEN" ]] || die 'use only one token source'
    [[ -r "$TOKEN_FILE" ]] || die "cannot read token file: $TOKEN_FILE"
    IFS= read -r TOKEN <"$TOKEN_FILE" || [[ -n "$TOKEN" ]]
fi
[[ -n "$TOKEN" ]] || die 'use --token-file'

validate_plain_value organization "$ORG"
validate_plain_value labels "$LABELS"
validate_plain_value group "$RUNNER_GROUP"
validate_plain_value prefix "$PREFIX"

passwd_row=$(getent passwd -- "$RUNNER_USER") || die "Linux user does not exist: $RUNNER_USER"
BASE=$(printf '%s\n' "$passwd_row" | cut -d: -f6)
RUNNER_PRIMARY_GID=$(printf '%s\n' "$passwd_row" | cut -d: -f4)
RUNNER_SHELL=$(printf '%s\n' "$passwd_row" | cut -d: -f7)
[[ "$BASE" == /* && -d "$BASE" ]] || die "invalid home directory for $RUNNER_USER: $BASE"
[[ "$RUNNER_PRIMARY_GID" =~ ^[0-9]+$ ]] || die "invalid primary GID for $RUNNER_USER"
[[ "$RUNNER_SHELL" == /* && -x "$RUNNER_SHELL" ]] || die "invalid login shell for $RUNNER_USER: $RUNNER_SHELL"
ENV_BIN=$(command -v env)
RUNUSER_BIN=$(command -v runuser)
CLEAN_COMMAND_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ -z "$RUNNER_RUNTIME_PATH" ]]; then
    RUNNER_RUNTIME_PATH="$BASE/.local/bin:$BASE/.local/share/mise/shims:$BASE/bin:$CLEAN_COMMAND_PATH"
    [[ ! -d /snap/bin ]] || RUNNER_RUNTIME_PATH="$RUNNER_RUNTIME_PATH:/snap/bin"
fi
validate_plain_value runner-path "$RUNNER_RUNTIME_PATH"

hostname_short=$(hostname -s | tr '[:upper:]' '[:lower:]')
if [[ -z "$LABELS" ]]; then
    LABELS=$hostname_short
fi
if [[ -z "$PREFIX" ]]; then
    [[ "$LABELS" != *,* ]] \
        || die 'multi-label deployment requires an explicit --prefix'
    PREFIX=$LABELS
fi
[[ "$PREFIX" =~ ^[A-Za-z0-9._-]+$ ]] || die 'prefix must contain only letters, digits, dot, underscore, or dash'
validate_plain_value labels "$LABELS"
[[ "$LABELS" != ,* && "$LABELS" != *, && "$LABELS" != *,,* ]] \
    || die 'labels must be a comma-separated list with no empty item'

active_same_user=()
while IFS= read -r unit_name; do
    [[ -n "$unit_name" ]] || continue
    unit_user=$(systemctl show "$unit_name" -p User --value)
    unit_state=$(systemctl show "$unit_name" -p ActiveState --value)
    if [[ "$unit_user" == "$RUNNER_USER" && "$unit_state" == active ]]; then
        active_same_user+=("$unit_name")
    fi
done < <(systemctl list-units --type=service --all 'actions.runner*' --plain --no-legend | awk '{print $1}')
if (( ${#active_same_user[@]} > 0 )); then
    printf 'ERROR: active runner services for User=%s must be stopped before setup:\n' "$RUNNER_USER" >&2
    printf '  %s\n' "${active_same_user[@]}" >&2
    exit 1
fi
if pgrep -u "$RUNNER_USER" >/dev/null 2>&1; then
    printf 'ERROR: processes for User=%s remain after drain; stop them before setup:\n' "$RUNNER_USER" >&2
    ps -o pid,ppid,stat,etime,comm -u "$RUNNER_USER" >&2
    exit 1
fi

case $(uname -m) in
    x86_64|amd64) RUNNER_ARCH=x64 ;;
    aarch64|arm64) RUNNER_ARCH=arm64 ;;
    armv7l|armv6l) RUNNER_ARCH=arm ;;
    *) die "unsupported architecture: $(uname -m)" ;;
esac

release_json=$(mktemp)
download_tmp=''
cleanup() {
    rm -f -- "$release_json"
    [[ -z "$download_tmp" ]] || rm -f -- "$download_tmp"
}
trap cleanup EXIT

if [[ -n "$RUNNER_VERSION" ]]; then
    release_api="https://api.github.com/repos/actions/runner/releases/tags/v${RUNNER_VERSION}"
else
    release_api='https://api.github.com/repos/actions/runner/releases/latest'
fi
info "reading release metadata from $release_api"
curl -fsSL "${CURL_RETRY_ARGS[@]}" "$release_api" -o "$release_json" \
    || die 'failed to read GitHub runner release metadata'

if [[ -z "$RUNNER_VERSION" ]]; then
    RUNNER_VERSION=$(python3 - "$release_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as file:
    tag = json.load(file)["tag_name"]
    print(tag[1:] if tag.startswith("v") else tag)
PY
    )
fi

PACKAGE="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
mapfile -t asset_metadata < <(python3 - "$release_json" "$PACKAGE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as file:
    release = json.load(file)
for asset in release.get("assets", []):
    if asset.get("name") == sys.argv[2]:
        print(asset.get("browser_download_url", ""))
        print(asset.get("digest", ""))
        break
PY
)
[[ ${#asset_metadata[@]} -eq 2 && -n ${asset_metadata[0]} ]] \
    || die "release does not contain $PACKAGE"
ASSET_URL=${asset_metadata[0]}
ASSET_DIGEST=${asset_metadata[1]}
[[ "$ASSET_DIGEST" == sha256:* ]] || die "release asset has no SHA-256 digest: $PACKAGE"
ASSET_SHA256=${ASSET_DIGEST#sha256:}

CACHE_DIR=/var/cache/github-actions-runner
install -d -o root -g root -m 0755 "$CACHE_DIR"
PACKAGE_PATH="$CACHE_DIR/$PACKAGE"

verify_package() {
    local package_path=$1
    printf '%s  %s\n' "$ASSET_SHA256" "$package_path" | sha256sum -c - >/dev/null \
        || return 1
    local archive_list
    archive_list=$(mktemp) || return 1
    if ! tar -tzf "$package_path" >"$archive_list"; then
        rm -f -- "$archive_list"
        return 1
    fi
    for required_path in config.sh svc.sh bin/Runner.Listener; do
        { grep -Fxq "$required_path" "$archive_list" || grep -Fxq "./$required_path" "$archive_list"; } || {
            rm -f -- "$archive_list"
            return 1
        }
    done
    rm -f -- "$archive_list"
}

if [[ -f "$PACKAGE_PATH" ]] && ! verify_package "$PACKAGE_PATH"; then
    warn "discarding invalid cached package: $PACKAGE_PATH"
    rm -f -- "$PACKAGE_PATH"
fi
if [[ ! -f "$PACKAGE_PATH" ]]; then
    download_tmp=$(mktemp "$CACHE_DIR/.${PACKAGE}.XXXXXX")
    curl -fL "${CURL_RETRY_ARGS[@]}" "$ASSET_URL" -o "$download_tmp"
    verify_package "$download_tmp" || die "downloaded package failed verification: $PACKAGE"
    chmod 0644 "$download_tmp"
    chown root:root "$download_tmp"
    mv -f -- "$download_tmp" "$PACKAGE_PATH"
    download_tmp=''
fi

ORG_URL="https://github.com/$ORG"
printf '%s\n' \
    "Organization: $ORG" \
    "Runner names: ${PREFIX}-{1..${COUNT}}" \
    "Labels: $LABELS" \
    "Group: $RUNNER_GROUP" \
    "Linux user: $RUNNER_USER" \
    "Runner PATH: $RUNNER_RUNTIME_PATH" \
    "Install paths: ${BASE}/actions-runner-{1..${COUNT}}" \
    "Runner version: $RUNNER_VERSION ($RUNNER_ARCH)"
if [[ $ASSUME_YES -ne 1 ]]; then
    read -r -p 'Proceed? [y/N] ' confirmation
    [[ ${confirmation,,} == y || ${confirmation,,} == yes ]] || exit 0
fi

target_units=()
inherited_dropins=()
created=0

# This script intentionally supports fresh deployment only. It has no GitHub API
# credential with which to prove a remote same-name runner is idle, so it never
# passes config.sh --replace and never treats local state as remote reconciliation.
for runner_number in $(seq 1 "$COUNT"); do
    runner_dir="$BASE/actions-runner-$runner_number"
    [[ ! -e "$runner_dir" ]] \
        || die "target path already exists; inspect or remove it before fresh deployment: $runner_dir"
done

for runner_number in $(seq 1 "$COUNT"); do
    runner_dir="$BASE/actions-runner-$runner_number"
    runner_name="$PREFIX-$runner_number"

    info "configuring $runner_name"
    install -d -o root -g root -m 0755 "$runner_dir"
    tar -xzf "$PACKAGE_PATH" -C "$runner_dir"
    chown -R "$RUNNER_USER:$RUNNER_PRIMARY_GID" "$runner_dir"

    config_args=(
        "$runner_dir/config.sh" --unattended
        --url "$ORG_URL"
        --token "$TOKEN"
        --name "$runner_name"
        --runnergroup "$RUNNER_GROUP"
        --labels "$LABELS"
        --work _work
    )
    if [[ $PIN_RUNNER_VERSION -eq 1 ]]; then
        config_args+=(--disableupdate)
    fi
    if ! (cd "$runner_dir" && "$ENV_BIN" -i PATH="$CLEAN_COMMAND_PATH" \
        "$RUNUSER_BIN" -u "$RUNNER_USER" -- "$ENV_BIN" -i \
        HOME="$BASE" USER="$RUNNER_USER" LOGNAME="$RUNNER_USER" \
        SHELL="$RUNNER_SHELL" PATH="$RUNNER_RUNTIME_PATH" "${config_args[@]}"); then
        die "runner registration failed; directory preserved because local .runner absence cannot prove the remote request did not commit. Check GitHub for $runner_name before cleanup: $runner_dir"
    fi
    mapfile -t identity < <(read_runner_identity "$runner_dir/.runner")
    [[ ${identity[0]-} == "$runner_name" && ${identity[1]-} == "$ORG_URL" ]] \
        || die "registered runner identity does not match $ORG_URL / $runner_name: $runner_dir"

    chown -R root:root "$runner_dir"
    if ! (cd "$runner_dir" && ./svc.sh install "$RUNNER_USER"); then
        chown -R "$RUNNER_USER:$RUNNER_PRIMARY_GID" "$runner_dir"
        die "service installation failed; recover this registered instance with remove-runners.sh --start $runner_number --count 1: $runner_dir"
    fi
    chown -R "$RUNNER_USER:$RUNNER_PRIMARY_GID" "$runner_dir"
    unit_name=$(<"$runner_dir/.service")
    [[ "$unit_name" =~ ^actions\.runner\.[A-Za-z0-9_.@-]+\.service$ ]] \
        || die "installed service name is invalid: $unit_name"
    fragment_path=$(systemctl show "$unit_name" -p FragmentPath --value)
    [[ "$fragment_path" == "/etc/systemd/system/$unit_name" ]] \
        || die "installed service fragment mismatch: $unit_name -> $fragment_path"
    [[ $(systemctl show "$unit_name" -p User --value) == "$RUNNER_USER" ]] \
        || die "installed service user mismatch: $unit_name"
    systemctl show "$unit_name" -p ExecStart --value | grep -Fq -- "$runner_dir/runsvc.sh" \
        || die "installed service ExecStart mismatch: $unit_name"
    systemctl is-enabled --quiet "$unit_name" \
        || die "installed service is not enabled: $unit_name"
    dropin_paths=$(systemctl show "$unit_name" -p DropInPaths --value)
    read -r -a unit_dropins <<<"$dropin_paths"
    if [[ -n "$dropin_paths" && $ACCEPT_INHERITED_DROPINS -eq 0 ]]; then
        printf 'ERROR: inherited drop-ins require explicit review before this fresh runner can start:\n' >&2
        printf '  %s\n' "${unit_dropins[@]}" >&2
        die "rerun only after removing this registered instance, then pass --accept-inherited-dropins if every path is intended"
    fi
    if [[ -n "$dropin_paths" ]]; then
        inherited_dropins+=("${unit_dropins[@]}")
    fi
    target_units+=("$unit_name")
    created=$((created + 1))
done

for unit_name in "${target_units[@]}"; do
    systemctl start "$unit_name"
    systemctl is-active --quiet "$unit_name" || die "runner service did not become active: $unit_name"
done

printf 'Local deployment complete: created=%d active=%d\n' \
    "$created" "${#target_units[@]}"
printf 'Deployment is not complete until GitHub online/name/label/group state matches these units:\n'
printf '  %s\n' "${target_units[@]}"
if (( ${#inherited_dropins[@]} > 0 )); then
    printf 'Accepted inherited drop-ins:\n'
    printf '%s\n' "${inherited_dropins[@]}" | sort -u | sed 's/^/  /'
fi
