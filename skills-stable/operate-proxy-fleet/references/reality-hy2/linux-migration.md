# 从 Clash／Mihomo 迁到 sing-box

Linux 主机原来跑 Clash、Mihomo 或用户级代理配置，迁到 sing-box TUN 后不能两套同时开着。新 TUN 先按 [linux-client.md](linux-client.md) 跑通并验收，再清旧的。

## 盘点

```bash
systemctl list-unit-files --no-pager | grep -Ei 'clash|mihomo' || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'clash|mihomo' || true
systemctl --user list-unit-files --no-pager | grep -Ei 'clash|mihomo' || true
systemctl --user list-units --type=service --all --no-pager | grep -Ei 'clash|mihomo' || true
ps -eo pid,ppid,user,comm,args | grep -Ei 'clash|mihomo' | grep -v grep || true
ss -lntup | grep -E ':(7890|7891|7892|7893|9090|9097|2080)\b' || true
```

「隔离」指把文件 `mv` 进下面建的 `proxy-cleanup` 目录（root 的文件进 `/root/proxy-cleanup`，用户的进 `~/.local/share/proxy-cleanup`），并记下原路径，需要时能原样挪回。每条路径都要追到旧进程或旧 unit 上，才能隔离它。不要以为 `/opt/clash`、`~/.config/sing-box` 或某个 systemd 路径一定属于这次迁移。动之前记下来源、属主、谁在用、备份路径和恢复命令。

## 停掉旧服务

盘点之后，只停用并 mask 确认过的旧服务。mask 会建一个 `/etc/systemd/system/<unit> -> /dev/null` 的符号链接，之后别挪它，挪了 mask 就失效：

```bash
sudo systemctl disable --now mihomo.service 2>/dev/null || true
sudo systemctl mask mihomo.service 2>/dev/null || true
sudo install -d -m 700 /root/proxy-cleanup
systemctl is-enabled mihomo.service
systemctl is-active mihomo.service || true
```

`/usr/lib/systemd/system` 下的 unit 用 `dpkg-query -S`、`pacman -Qo` 或主机的包管理器查归属；要卸包得用户点名。包里自带的 unit 文件永远不隔离。`/opt/clash` 这类应用自带的 daemon 目录，确认属主和使用方后才隔离，然后 `systemctl daemon-reload`，再查一次 mask。

## 清 shell hook 和旧的用户配置

```bash
rg -n -i 'clash|mihomo|watch_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy' \
  ~/.bashrc ~/.bash_profile ~/.profile ~/.zshrc ~/.zprofile ~/.zshenv /etc/profile /etc/bash.bashrc /etc/zsh/zshrc 2>/dev/null || true
mkdir -p ~/.local/share/proxy-cleanup
```

先列出候选文件，逐个对照这次的范围；归属不明或超出范围的才问用户。正在用的 sing-box 客户端配置保留。root 拥有的旧文件，有现成的非交互提权路径就用，没有就把确切的隔离命令交给用户执行。

## 清完复查

再盘点一次，确认过的旧组件必须全部不在：

```bash
set -o pipefail

systemctl list-unit-files --no-pager \
  | awk 'tolower($1) ~ /(clash|mihomo)/ && $2 ~ /^enabled/ { print > "/dev/stderr"; bad = 1 } END { exit bad }' \
  || { echo "enabled system proxy unit or unreadable system unit inventory" >&2; exit 1; }

systemctl --user list-unit-files --no-pager \
  | awk 'tolower($1) ~ /(clash|mihomo)/ && $2 ~ /^enabled/ { print > "/dev/stderr"; bad = 1 } END { exit bad }' \
  || { echo "enabled user proxy unit or unreadable user unit inventory" >&2; exit 1; }

if ! system_running="$(systemctl list-units --type=service --state=running --no-pager)"; then
  echo "cannot read running system units" >&2
  exit 1
fi
if grep -Ei 'clash|mihomo' <<<"$system_running"; then exit 1; fi

if ! user_running="$(systemctl --user list-units --type=service --state=running --no-pager)"; then
  echo "cannot read running user units" >&2
  exit 1
fi
if grep -Ei 'clash|mihomo' <<<"$user_running"; then exit 1; fi

process_matches="$(pgrep -a -f 'clash|mihomo' 2>&1)"
pgrep_code=$?
case "$pgrep_code" in
  0) printf '%s\n' "$process_matches" >&2; exit 1 ;;
  1) ;;
  *) printf '%s\n' "$process_matches" >&2; exit 1 ;;
esac

if ! socket_inventory="$(ss -lntup)"; then
  echo "cannot read listener inventory" >&2
  exit 1
fi
if grep -E ':(7890|7891|7892|7893|9090|9097)\b' <<<"$socket_inventory"; then exit 1; fi

shell_files=(
  ~/.bashrc ~/.bash_profile ~/.profile ~/.zshrc ~/.zprofile ~/.zshenv
  /etc/profile /etc/bash.bashrc /etc/zsh/zshrc
)
existing_shell_files=()
for file_path in "${shell_files[@]}"; do
  if [[ -f "$file_path" ]]; then existing_shell_files+=("$file_path"); fi
done
if ((${#existing_shell_files[@]})); then
  shell_matches="$(grep -Eni 'watch_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy' \
    "${existing_shell_files[@]}" 2>&1)"
  grep_code=$?
  case "$grep_code" in
    0) printf '%s\n' "$shell_matches" >&2; exit 1 ;;
    1) ;;
    *) printf '%s\n' "$shell_matches" >&2; exit 1 ;;
  esac
fi
```

`systemctl --user` 的检查要用受影响的登录用户身份跑，不要从 root shell 跑。连不上那个用户的 user manager 时，用户级清理就算没验证，持久清理这一关没过。

盘点阶段记下的每条归属路径都要复查。文件名里恰好带 `clash` 或 `mihomo` 的无关文件不是清理对象。故意 mask 的 unit 在用户点名卸包之前可以留着；它要满足：已 mask 或已禁用、不在运行、不占进程和端口、起不来。
