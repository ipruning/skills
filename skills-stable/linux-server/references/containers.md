# Containers

Container hosts include Docker/containerd, x-ui, nginx-proxy-manager, and apps whose public ports come from containers.

## Contents

- Inventory
- Docker and UFW
- Forwarding
- Management ports
- Docker group risk
- Service users

## Inventory

```bash
systemctl is-active docker containerd 2>/dev/null || true
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null || true
docker network ls 2>/dev/null || true
ip link
ss -tulpen
```

Map each public port to:

- host listener or docker-proxy
- container name and image
- container target port
- firewall allow path
- whether it is a service port or management/admin port

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
ufw route allow in on <BRIDGE_IFACE>
ufw route allow out on <BRIDGE_IFACE>
ufw reload
```

Repeat only for confirmed bridge interfaces such as `docker0`, `br-*`, or named overlay interfaces.

## Management Ports

Treat these as management ports:

- x-ui dashboards
- nginx-proxy-manager admin ports
- database admin ports
- monitoring dashboards
- container registries

Expose a management port publicly only when the user confirms the public client set. Otherwise bind it to localhost, put it behind a reverse proxy with authentication, or restrict it by VPN/source range.

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
useradd --system --no-create-home --shell /usr/sbin/nologin <SVC_USER>
chown <SVC_USER>:<SVC_USER> /etc/<service>/<config>
chmod 600 /etc/<service>/<config>
```

In systemd:

```ini
[Service]
User=<SVC_USER>
Group=<SVC_USER>
```

Persistent impact: changes the service runtime user after `systemctl daemon-reload` and service restart.

```bash
systemctl daemon-reload
systemctl restart <service>
ps -o user,pid,comm -p "$(pidof <binary>)"
```

For privileged ports, use `AmbientCapabilities=CAP_NET_BIND_SERVICE` when the service only needs low-port binding; keep root only when the service requires other root-only operations that have been identified.
