#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo bash remove-runners.sh --token-file FILE [options]
       sudo bash remove-runners.sh --resume-after-unregister [options]

Remove GitHub.com organization-level runners only after GitHub reports them idle.

Required:
  -o, --org ORG          GitHub organization
  -p, --prefix PREFIX    Exact runner name prefix
  -n, --count N          Numbered instances to remove, 1-50
      --drained          Confirm every target runner is idle and no job can be assigned

Token input:
      --token-file FILE  Read the remove token from FILE

Optional:
      --start N          First numbered instance; defaults to 1
      --resume-after-unregister
                         Finish local cleanup only after independently confirming
                         the selected remote runner is already unregistered
  -u, --user USER        Linux service user; defaults to actions
  -y, --yes              Skip the interactive confirmation
  -h, --help             Show this help
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

SCRIPTS_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
IDENTITY_READER="$SCRIPTS_DIR/read-runner-identity.py"
[[ -f "$IDENTITY_READER" && -r "$IDENTITY_READER" ]] \
    || die "missing runner identity helper; copy the entire scripts directory: $IDENTITY_READER"

ORG=''
PREFIX=''
COUNT=''
START=1
RUNNER_USER='actions'
TOKEN=''
TOKEN_FILE=''
DRAINED=0
ASSUME_YES=0
RESUME_AFTER_UNREGISTER=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--org) require_value "$1" "${2-}"; ORG=$2; shift 2 ;;
        -p|--prefix) require_value "$1" "${2-}"; PREFIX=$2; shift 2 ;;
        -n|--count) require_value "$1" "${2-}"; COUNT=$2; shift 2 ;;
        --start) require_value "$1" "${2-}"; START=$2; shift 2 ;;
        -u|--user) require_value "$1" "${2-}"; RUNNER_USER=$2; shift 2 ;;
        --token-file) require_value "$1" "${2-}"; TOKEN_FILE=$2; shift 2 ;;
        --drained) DRAINED=1; shift ;;
        --resume-after-unregister) RESUME_AFTER_UNREGISTER=1; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; [[ $# -eq 0 ]] || { printf 'ERROR: positional arguments are not supported\n' >&2; exit 2; } ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || die 'run as root'
for dependency in \
    awk chmod chown cut env find getent grep install mktemp mv pgrep ps python3 rm \
    readlink runuser sed seq sort stat systemctl tr xargs; do
    command -v "$dependency" >/dev/null 2>&1 || die "missing dependency: $dependency"
done

[[ -n "$ORG" ]] || die 'missing required option: --org'
[[ -n "$PREFIX" ]] || die 'missing required option: --prefix'
[[ -n "$COUNT" ]] || die 'missing required option: --count'
[[ "$ORG" =~ ^[A-Za-z0-9._-]+$ ]] || die 'organization contains unsupported characters'
[[ "$PREFIX" =~ ^[A-Za-z0-9._-]+$ ]] || die 'prefix contains unsupported characters'
[[ "$COUNT" =~ ^[0-9]+$ && "$COUNT" -ge 1 && "$COUNT" -le 50 ]] \
    || die "runner count must be an integer from 1 to 50: $COUNT"
[[ "$START" =~ ^[0-9]+$ && "$START" -ge 1 && "$START" -le 50 ]] \
    || die "start must be an integer from 1 to 50: $START"
END=$((START + COUNT - 1))
[[ $END -le 50 ]] || die "selected instance range exceeds 50: $START..$END"
[[ $DRAINED -eq 1 ]] || die 'refusing removal without --drained'

if [[ $RESUME_AFTER_UNREGISTER -eq 1 ]]; then
    [[ -z "$TOKEN_FILE" ]] \
        || die 'resume-after-unregister performs local cleanup only; do not provide a token'
elif [[ -n "$TOKEN_FILE" ]]; then
    [[ -r "$TOKEN_FILE" ]] || die "cannot read token file: $TOKEN_FILE"
    IFS= read -r TOKEN <"$TOKEN_FILE" || [[ -n "$TOKEN" ]]
fi
if [[ $RESUME_AFTER_UNREGISTER -eq 0 ]]; then
    [[ -n "$TOKEN" ]] || die 'use --token-file'
fi

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
DEFAULT_RUNNER_RUNTIME_PATH="$BASE/.local/bin:$BASE/.local/share/mise/shims:$BASE/bin:$CLEAN_COMMAND_PATH"
[[ ! -d /snap/bin ]] || DEFAULT_RUNNER_RUNTIME_PATH="$DEFAULT_RUNNER_RUNTIME_PATH:/snap/bin"
ORG_URL="https://github.com/$ORG"
STATE_DIR=/var/lib/github-actions-runner-removal

runner_dirs=()
runner_units=()
runner_numbers=()
runner_unit_present=()
runner_was_active=()
runner_state_files=()
runner_marker_backups=()
runner_runtime_paths=()
shared_dropins=()
for runner_number in $(seq "$START" "$END"); do
    runner_dir="$BASE/actions-runner-$runner_number"
    runner_name="$PREFIX-$runner_number"
    runner_runtime_path=$DEFAULT_RUNNER_RUNTIME_PATH
    if [[ -f "$runner_dir/.path" ]]; then
        mapfile -t runner_path_lines <"$runner_dir/.path"
        [[ ${#runner_path_lines[@]} -eq 1 && -n ${runner_path_lines[0]} ]] \
            || die "runner .path must contain exactly one non-empty line: $runner_dir/.path"
        runner_runtime_path=${runner_path_lines[0]}
        validate_plain_value runner-path "$runner_runtime_path"
    fi
    state_file="$STATE_DIR/${ORG}--${PREFIX}--${runner_number}.identity"
    marker_backup="${state_file}.service-marker"
    identity_from_state=0
    [[ -d "$runner_dir" ]] || die "target directory is missing: $runner_dir"
    if [[ $RESUME_AFTER_UNREGISTER -eq 1 ]]; then
        if [[ -f "$runner_dir/.runner" ]]; then
            mapfile -t identity < <(python3 "$IDENTITY_READER" "$runner_dir/.runner")
            [[ ${identity[0]-} == "$runner_name" && ${identity[1]-} == "$ORG_URL" ]] \
                || die "stale local runner identity does not match $ORG_URL / $runner_name: $runner_dir"
            warn "resume is accepting a stale local .runner only because remote absence was independently confirmed: $runner_dir"
        else
            [[ -f "$state_file" ]] \
                || die "resume without .runner requires the root-owned identity recorded before unregister: $state_file"
            [[ $(stat -c '%u:%g:%a' "$state_file") == 0:0:600 ]] \
                || die "removal identity has unsafe ownership or mode: $state_file"
            mapfile -t saved_identity <"$state_file"
            [[ ${saved_identity[0]-} == "$ORG_URL" \
                && ${saved_identity[1]-} == "$runner_name" \
                && ${saved_identity[2]-} == "$runner_dir" ]] \
                || die "recorded removal identity does not match requested organization/name/path: $state_file"
            identity_from_state=1
        fi
    else
        [[ -f "$runner_dir/.runner" ]] \
            || die "target has no registered runner identity: $runner_dir"
        mapfile -t identity < <(python3 "$IDENTITY_READER" "$runner_dir/.runner")
        [[ ${identity[0]-} == "$runner_name" && ${identity[1]-} == "$ORG_URL" ]] \
            || die "runner identity does not match $ORG_URL / $runner_name: $runner_dir"
    fi

    unit_name=''
    unit_present=0
    was_active=0
    marker_source=''
    if [[ -f "$runner_dir/.service" ]]; then
        marker_source="$runner_dir/.service"
    elif [[ -f "$marker_backup" ]]; then
        [[ $(stat -c '%u:%g:%a' "$marker_backup") == 0:0:600 ]] \
            || die "service-marker backup has unsafe ownership or mode: $marker_backup"
        [[ -f "$state_file" && $(stat -c '%u:%g:%a' "$state_file") == 0:0:600 ]] \
            || die "service-marker backup has no safe removal identity: $state_file"
        mapfile -t marker_identity <"$state_file"
        [[ ${marker_identity[0]-} == "$ORG_URL" \
            && ${marker_identity[1]-} == "$runner_name" \
            && ${marker_identity[2]-} == "$runner_dir" ]] \
            || die "service-marker backup identity does not match requested runner: $state_file"
        marker_source=$marker_backup
        warn "continuing an interrupted removal with the root-owned service-marker backup: $marker_backup"
    fi
    if [[ -n "$marker_source" ]]; then
        unit_name=$(<"$marker_source")
        [[ "$unit_name" =~ ^actions\.runner\.[A-Za-z0-9_.@-]+\.service$ ]] \
            || die "invalid service name in $runner_dir/.service"
        fragment_path=$(systemctl show "$unit_name" -p FragmentPath --value)
        expected_fragment="/etc/systemd/system/$unit_name"
        if [[ -z "$fragment_path" && -f "$expected_fragment" ]]; then
            systemctl daemon-reload || die "failed to load existing unit fragment for validation: $expected_fragment"
            fragment_path=$(systemctl show "$unit_name" -p FragmentPath --value)
        fi
        if [[ -n "$fragment_path" ]]; then
            [[ "$fragment_path" == "$expected_fragment" ]] \
                || die "unexpected unit fragment path: $unit_name -> $fragment_path"
            [[ $(systemctl show "$unit_name" -p User --value) == "$RUNNER_USER" ]] \
                || die "service user mismatch: $unit_name"
            systemctl show "$unit_name" -p ExecStart --value | grep -Fq -- "$runner_dir/runsvc.sh" \
                || die "service ExecStart does not match runner directory: $unit_name"
            unit_present=1
            [[ $(systemctl show "$unit_name" -p ActiveState --value) == active ]] && was_active=1
            dropin_paths=$(systemctl show "$unit_name" -p DropInPaths --value)
            read -r -a unit_dropins <<<"$dropin_paths"
            for dropin_path in "${unit_dropins[@]}"; do
                case "$dropin_path" in
                    "/etc/systemd/system/$unit_name.d/"*) ;;
                    *) shared_dropins+=("$dropin_path") ;;
                esac
            done
        else
            warn "service identity exists but unit fragment is absent; treating it as an incomplete local install: $unit_name"
        fi
        unit_stem=${unit_name%.service}
        remaining_stem=$unit_stem
        while [[ "$remaining_stem" == *-* ]]; do
            remaining_stem=${remaining_stem%-*}
            shared_dir="/etc/systemd/system/${remaining_stem}-.service.d"
            [[ -d "$shared_dir" ]] && shared_dropins+=("$shared_dir")
        done
        [[ -d /etc/systemd/system/service.d ]] && shared_dropins+=(/etc/systemd/system/service.d)
    fi
    if [[ $identity_from_state -eq 1 && -n ${saved_identity[3]-} \
        && ${saved_identity[3]} != "$unit_name" ]]; then
        die "recorded removal unit does not match local .service: $state_file"
    fi

    runner_dirs+=("$runner_dir")
    runner_units+=("$unit_name")
    runner_numbers+=("$runner_number")
    runner_unit_present+=("$unit_present")
    runner_was_active+=("$was_active")
    runner_state_files+=("$state_file")
    runner_marker_backups+=("$marker_backup")
    runner_runtime_paths+=("$runner_runtime_path")
done

for unit_name in $(systemctl list-units --type=service --all 'actions.runner*' --plain --no-legend | awk '{print $1}'); do
    [[ $(systemctl show "$unit_name" -p User --value) == "$RUNNER_USER" ]] || continue
    [[ $(systemctl show "$unit_name" -p ActiveState --value) == active ]] || continue
    is_target=0
    for target_unit in "${runner_units[@]}"; do
        if [[ "$unit_name" == "$target_unit" ]]; then
            is_target=1
            break
        fi
    done
    [[ $is_target -eq 1 ]] || die "active same-user runner is outside removal target; stop it first: $unit_name"
done

printf 'The following drained runners will be unregistered and deleted:\n'
for index in "${!runner_dirs[@]}"; do
    printf '  %s  %s\n' "${runner_units[$index]:-(no service installed)}" "${runner_dirs[$index]}"
done
if [[ $ASSUME_YES -ne 1 ]]; then
    read -r -p 'Proceed? [y/N] ' confirmation
    [[ ${confirmation,,} == y || ${confirmation,,} == yes ]] || exit 0
fi
if [[ $RESUME_AFTER_UNREGISTER -eq 0 ]]; then
    install -d -o root -g root -m 0700 "$STATE_DIR" \
        || die "failed to create root-owned removal state directory: $STATE_DIR"
fi

stopped_units=()
for index in "${!runner_units[@]}"; do
    unit_name=${runner_units[$index]}
    [[ ${runner_unit_present[$index]} -eq 1 ]] || continue
    if ! systemctl stop "$unit_name"; then
        if [[ $RESUME_AFTER_UNREGISTER -eq 0 ]]; then
            warn "failed to stop $unit_name; restarting services already stopped"
            for stopped_unit in "${stopped_units[@]}"; do systemctl start "$stopped_unit" || true; done
        else
            warn "failed to stop $unit_name; leaving previously stopped unregistered services stopped"
        fi
        exit 1
    fi
    [[ ${runner_was_active[$index]} -eq 1 ]] && stopped_units+=("$unit_name")
done
if [[ $RESUME_AFTER_UNREGISTER -eq 0 ]] \
    && pgrep -u "$RUNNER_USER" >/dev/null 2>&1; then
    warn "processes for User=$RUNNER_USER remain after stopping target units"
    ps -o pid,ppid,stat,etime,comm -u "$RUNNER_USER" >&2
    for stopped_unit in "${stopped_units[@]}"; do systemctl start "$stopped_unit" || true; done
    die 'refusing to expose the remove token while same-user processes remain'
fi
if [[ $RESUME_AFTER_UNREGISTER -eq 1 ]]; then
    residual_target_pids=()
    for unit_name in "${runner_units[@]}"; do
        [[ -n "$unit_name" ]] || continue
        control_group=$(systemctl show "$unit_name" -p ControlGroup --value 2>/dev/null || true)
        [[ -n "$control_group" ]] || continue
        cgroup_roots=()
        [[ ! -d "/sys/fs/cgroup${control_group}" ]] \
            || cgroup_roots+=("/sys/fs/cgroup${control_group}")
        for controller_root in /sys/fs/cgroup/*; do
            [[ -d "$controller_root$control_group" ]] \
                && cgroup_roots+=("$controller_root$control_group")
        done
        for cgroup_root in "${cgroup_roots[@]}"; do
            while IFS= read -r -d '' process_file; do
                while IFS= read -r residual_pid; do
                    [[ -n "$residual_pid" ]] && residual_target_pids+=("$residual_pid")
                done <"$process_file"
            done < <(find "$cgroup_root" -type f \
                \( -name cgroup.procs -o -name tasks \) -print0)
        done
    done
    while IFS= read -r residual_pid; do
        [[ -n "$residual_pid" ]] || continue
        process_exe=$(readlink -f "/proc/$residual_pid/exe" 2>/dev/null || true)
        process_cwd=$(readlink -f "/proc/$residual_pid/cwd" 2>/dev/null || true)
        process_args=$(tr '\0' ' ' <"/proc/$residual_pid/cmdline" 2>/dev/null || true)
        for runner_dir in "${runner_dirs[@]}"; do
            if [[ "$process_exe" == "$runner_dir/"* \
                || "$process_cwd" == "$runner_dir" \
                || "$process_cwd" == "$runner_dir/"* \
                || "$process_args" == *"$runner_dir/"* ]]; then
                residual_target_pids+=("$residual_pid")
                break
            fi
        done
    done < <(pgrep -u "$RUNNER_USER" || true)
    if (( ${#residual_target_pids[@]} > 0 )); then
        warn 'target runner processes remain after stopping target units'
        printf '%s\n' "${residual_target_pids[@]}" | sort -un | xargs -r ps -o pid,ppid,stat,etime,comm -p >&2
        die 'refusing local cleanup while target runner processes remain'
    fi
fi

removed=0
restart_registered_units_from() {
    local first_index=$1
    local restore_unit
    local restore_index
    [[ $RESUME_AFTER_UNREGISTER -eq 0 ]] || return 0
    for restore_index in $(seq "$first_index" $((${#runner_units[@]} - 1))); do
        restore_unit=${runner_units[$restore_index]}
        if [[ ${runner_was_active[$restore_index]} -eq 1 \
            && -n "$restore_unit" && -f "${runner_dirs[$restore_index]}/.runner" \
            && -n $(systemctl show "$restore_unit" -p FragmentPath --value 2>/dev/null) ]]; then
            systemctl start "$restore_unit" || warn "failed to restart $restore_unit"
        fi
    done
}

for index in "${!runner_dirs[@]}"; do
    runner_dir=${runner_dirs[$index]}
    unit_name=${runner_units[$index]}
    runner_number=${runner_numbers[$index]}
    state_file=${runner_state_files[$index]}
    marker_backup=${runner_marker_backups[$index]}
    info "removing $unit_name"

    if [[ $RESUME_AFTER_UNREGISTER -eq 0 ]]; then
        state_tmp=$(mktemp "$STATE_DIR/.identity.XXXXXX") || {
            restart_registered_units_from "$index"
            die 'failed to create removal identity'
        }
        if ! printf '%s\n%s\n%s\n%s\n' \
            "$ORG_URL" "$PREFIX-$runner_number" "$runner_dir" "$unit_name" >"$state_tmp" \
          || ! chmod 0600 "$state_tmp" \
          || ! chown root:root "$state_tmp" \
          || ! mv -f -- "$state_tmp" "$state_file"; then
            rm -f -- "$state_tmp"
            restart_registered_units_from "$index"
            die "failed to persist removal identity before unregister: $state_file"
        fi
        # config.sh remove refuses while the runner's .service marker exists.
        # Keep the stopped systemd unit as rollback, but move the marker into
        # root-only recovery state before invoking runner-user-owned config.sh.
        if [[ -n "$unit_name" && -f "$runner_dir/.service" ]]; then
            if ! install -o root -g root -m 0600 "$runner_dir/.service" "$marker_backup" \
              || ! rm -f -- "$runner_dir/.service"; then
                rm -f -- "$marker_backup"
                restart_registered_units_from "$index"
                die "failed to stage service marker for unregister: $runner_dir/.service"
            fi
        fi
        if ! (cd "$runner_dir" && "$ENV_BIN" -i PATH="$CLEAN_COMMAND_PATH" \
            "$RUNUSER_BIN" -u "$RUNNER_USER" -- "$ENV_BIN" -i \
            HOME="$BASE" USER="$RUNNER_USER" LOGNAME="$RUNNER_USER" \
            SHELL="$RUNNER_SHELL" PATH="${runner_runtime_paths[$index]}" \
            "$runner_dir/config.sh" remove --token "$TOKEN"); then
            if [[ -f "$marker_backup" ]]; then
                if ! install -o "$RUNNER_USER" -g "$RUNNER_PRIMARY_GID" -m 0644 \
                    "$marker_backup" "$runner_dir/.service"; then
                    warn "CRITICAL: GitHub unregister failed and service marker could not be restored: $runner_dir/.service"
                    exit 1
                fi
                rm -f -- "$marker_backup" || warn "stale marker backup remains: $marker_backup"
            fi
            warn "GitHub unregister failed for ${unit_name:-$runner_dir}; preserving local state and restarting still-registered services"
            restart_registered_units_from "$index"
            exit 1
        fi
    fi

    if [[ ${runner_unit_present[$index]} -eq 1 ]]; then
        if ! systemctl disable "$unit_name" \
            || ! rm -f -- "/etc/systemd/system/$unit_name" \
            || ! rm -rf -- "/etc/systemd/system/$unit_name.d" \
            || ! systemctl daemon-reload; then
            warn "remote runner is unregistered but local unit cleanup failed; directory preserved: $unit_name"
            warn "after confirming the remote runner is absent, rerun with --start $runner_number --count 1 --resume-after-unregister --drained"
            restart_registered_units_from "$((index + 1))"
            exit 1
        fi
        systemctl reset-failed "$unit_name" 2>/dev/null || true
        if systemctl show "$unit_name" -p FragmentPath --value 2>/dev/null | grep -q .; then
            warn "remote runner is unregistered but unit fragment still exists; directory preserved: $unit_name"
            warn "after confirming the remote runner is absent, rerun with --start $runner_number --count 1 --resume-after-unregister --drained"
            restart_registered_units_from "$((index + 1))"
            exit 1
        fi
    fi

    if [[ ${runner_unit_present[$index]} -eq 0 && -n "$unit_name" ]]; then
        if ! rm -f -- "/etc/systemd/system/$unit_name" \
          || ! rm -rf -- "/etc/systemd/system/$unit_name.d" \
          || ! systemctl daemon-reload; then
            warn "remote runner is unregistered but residual local unit cleanup failed: $unit_name"
            warn "after confirming the remote runner is absent, rerun with --start $runner_number --count 1 --resume-after-unregister --drained"
            restart_registered_units_from "$((index + 1))"
            exit 1
        fi
    fi

    if ! rm -rf -- "$runner_dir"; then
        warn "remote runner and unit are removed but directory cleanup failed: $runner_dir"
        warn "after confirming the remote runner is absent, rerun with --start $runner_number --count 1 --resume-after-unregister --drained"
        restart_registered_units_from "$((index + 1))"
        exit 1
    fi
    if ! rm -f -- "$state_file" "$marker_backup"; then
        warn "runner is removed but stale removal state remains: $state_file / $marker_backup"
        exit 1
    fi
    removed=$((removed + 1))
done

printf 'Removal complete: removed=%d failed=0\n' "$removed"
if (( ${#shared_dropins[@]} > 0 )); then
    printf 'Retained inherited drop-ins collected from actual units; review before deleting any shared file:\n'
    printf '%s\n' "${shared_dropins[@]}" | sort -u | sed 's/^/  /'
fi
