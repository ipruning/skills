# Containers

Container hosts include Docker/containerd, x-ui, nginx-proxy-manager, and apps whose public ports come from containers.

## Contents

- Inventory
- Lifecycle and leftovers
- Docker and UFW
- Forwarding
- Management ports
- Docker group risk
- Service users

## Inventory

```bash
systemctl is-active docker containerd || true
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker network ls
ip link
ss -tulpen
```

Treat a Docker permission, daemon, socket, or plugin error as unavailable evidence. Do not turn it
into an empty inventory with stderr suppression.

Map each public port to:

- host listener or docker-proxy
- container name and image
- container target port
- firewall allow path
- whether it is a service port or management/admin port

## Lifecycle And Leftovers

Running containers are only one part of host state. Read stopped and never-started containers,
builders, volumes, images, restart counts, and health before calling a container host clean:

```bash
docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}'
docker ps -aq --filter status=created
docker ps --filter health=unhealthy
docker system df
docker volume ls
docker buildx ls
docker inspect <CONTAINER> --format \
  'restart={{json .HostConfig.RestartPolicy}} cgroup={{.HostConfig.CgroupParent}} mounts={{json .Mounts}} health_status={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'
container_log=$(mktemp)
chmod 600 "$container_log"
if docker logs --since 24h <CONTAINER> >"$container_log" 2>&1; then
  stat -c 'container-log-capture mode=%a owner=%U:%G bytes=%s path=%n' "$container_log"
  printf 'lines=%s error-markers=%s secret-markers=%s\n' \
    "$(wc -l <"$container_log")" \
    "$(grep -Eic 'error|fatal|panic|exception' "$container_log" || true)" \
    "$(grep -Eic 'authorization|bearer|token|password|secret|connection[_ -]?string' "$container_log" || true)"
else
  echo "container logs unavailable; not verified" >&2
fi
```

Do not print the capture into an agent transcript. Inspect named suspect lines through a secret-aware local path, redact values before quoting, and delete the capture after the audit artifact is complete.

Classify an old container as a deployment rollback artifact or an orphan from its labels,
deployment policy, references, events, and resource activity. A running BuildKit container absent
from `docker buildx ls` is suspicious, not sufficient deletion evidence by itself. Never run broad
container, image, builder, or volume pruning while jobs or deploys are active. Remove only named,
proven leftovers and verify that active workloads and subsequent builds still work.

## Docker And UFW

Docker-published ports can bypass UFW input rules because Docker installs NAT and filter rules. A port may be reachable even if `ufw status` does not list it.

Inspect packet-filter state:

```bash
iptables -S 2>/dev/null
iptables -t nat -S 2>/dev/null
nft list ruleset 2>/dev/null
```

Do not assume UFW is the full source of truth on Docker hosts.

## Forwarding

UFW `deny routed` can block bridge forwarding. Add route rules only after a container egress or ingress test fails and firewall counters or logs point to the forward path.

Read first:

```bash
ufw status verbose 2>/dev/null || true
nft list chain inet filter forward 2>/dev/null || true
iptables -S FORWARD 2>/dev/null || true
```

Active connectivity test:

Runtime impact: starts a short-lived container when `<LOCAL_TEST_IMAGE>` already exists locally; `--pull=never` prevents network image pulls.

```bash
docker run --pull=never --rm <LOCAL_TEST_IMAGE> ping -c1 <TEST_IP>
```

UFW route rules:

Persistent impact: adds routed firewall allow rules and reloads UFW until the rules are deleted.

```bash
ufw_backup=$(mktemp /run/ufw-route-original.XXXXXX.tar)
chmod 600 "$ufw_backup" || exit 1
tar -C / -cpf "$ufw_backup" etc/ufw etc/default/ufw || exit 1
tar -tf "$ufw_backup" >/dev/null || exit 1
route_ufw_status=$(LC_ALL=C ufw status) || exit 1
case "$route_ufw_status" in
  'Status: active'*) ;;
  *) echo "UFW must already be active before adding route rules" >&2; exit 1 ;;
esac
restore_ufw_route() {
  rm -rf /etc/ufw \
    && rm -f /etc/default/ufw \
    && tar -C / -xpf "$ufw_backup" \
    && ufw --force enable
}
if ! ufw route allow in on <BRIDGE_IFACE> \
  || ! ufw route allow out on <BRIDGE_IFACE> \
  || ! ufw reload; then
  restore_ufw_route || echo "CRITICAL: UFW route change failed and rollback was incomplete" >&2
  exit 1
fi
printf 'ufw_route_backup=%s\n' "$ufw_backup"
```

Repeat only for confirmed bridge interfaces such as `docker0`, `br-*`, or named overlay interfaces.

## Management Ports

Treat these as management ports:

- x-ui dashboards
- nginx-proxy-manager admin ports
- database admin ports
- monitoring dashboards
- container registries

Expose a management port publicly only when the user confirms the public client set. Otherwise bind it to localhost, put it behind a reverse proxy with authentication, or restrict it by VPN/source range. Closing an already-exposed management port follows the Port And Rule Match rules in [firewall.md](firewall.md).

## Docker Group Risk

The `docker` group is root-equivalent: a member can mount `/` into a container and read/write the host filesystem. Use `sudo docker <COMMAND>` for admins who already have sudo/root access. Add a user to `docker` only when root-equivalent local access is intended.

Audit:

```bash
getent group docker
```

## Service Users

Create a dedicated system user when a long-running service does not need an interactive shell or a shared human account.

Persistent impact: creates `<SVC_USER>`, changes ownership and mode on the service config path, and keeps those account and file changes until removed or replaced.

```bash
getent group <SVC_USER> >/dev/null || groupadd --system <SVC_USER>
id <SVC_USER> >/dev/null 2>&1 || \
  useradd --system --gid <SVC_USER> --no-create-home --shell /usr/sbin/nologin <SVC_USER>
test "$(id -gn <SVC_USER>)" = <SVC_USER> || { echo "unexpected primary group" >&2; exit 1; }
chown <SVC_USER>:<SVC_USER> /etc/<service>/<config> || exit 1
chmod 600 /etc/<service>/<config> || exit 1
```

In systemd:

```ini
[Service]
User=<SVC_USER>
Group=<SVC_USER>
```

Persistent impact: changes the service runtime user after `systemctl daemon-reload` and service restart.

```bash
systemctl daemon-reload || exit 1
systemctl restart <service> || exit 1
systemctl is-active --quiet <service> || exit 1
main_pid=$(systemctl show <service> -p MainPID --value) || exit 1
test "$main_pid" -gt 0 || exit 1
ps -o user,pid,comm -p "$main_pid" || exit 1
```

For privileged ports, use `AmbientCapabilities=CAP_NET_BIND_SERVICE` when the service only needs low-port binding; keep root only when the service requires other root-only operations that have been identified.
