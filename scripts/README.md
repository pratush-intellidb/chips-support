# Scripts

Support scripts for IntelliDB PostgreSQL HA (Patroni, etcd, HAProxy) on RHEL 9.

## When pg_ha_setup.py is not working (e.g. at customer site)

- **Package manager**: At sites where `dnf` is not available, `pg_ha_setup.py` automatically uses `yum` for package installs.
- **Patroni systemd unit**: Menu option **7 (Configure Patroni)** now creates `/etc/systemd/system/patroni.service` if missing, with the correct `User=` (e.g. `intellidb` for IntelliDB Enterprise).

## All-in-one fix and validate (recommended)

Run on **each node** to check etcd, fix Patroni config/unit, optionally HAProxy, and verify cluster:

```bash
# From project directory, with config.yaml (same file on all nodes; current_node/current_node_ip differ per node)
sudo bash scripts/ha-cluster-fix-and-validate.sh config.yaml
```

Or without config file (manual):

```bash
# node1 (HAProxy node)
sudo bash scripts/ha-cluster-fix-and-validate.sh node1 172.16.15.36 "172.16.15.36,172.16.15.37,172.16.15.38" --haproxy

# node2
sudo bash scripts/ha-cluster-fix-and-validate.sh node2 172.16.15.37 "172.16.15.36,172.16.15.37,172.16.15.38"

# node3
sudo bash scripts/ha-cluster-fix-and-validate.sh node3 172.16.15.38 "172.16.15.36,172.16.15.37,172.16.15.38"
```

The script:

1. Checks etcd (3.5.x, /health, /v2/machines).
2. Checks Patroni binary and config; **creates `patroni.service` with `User=intellidb`** if missing.
3. On the designated HAProxy node, checks/validates HAProxy config and restarts HAProxy.
4. Starts Patroni and runs `patronictl list` to confirm 1 Leader + 2 Replicas.

Requires `config.yaml` with `use_intellidb: true` and correct `etcd_ips` / `current_node` / `current_node_ip`, or the manual arguments above.

## Per-node fix scripts (simplest – no arguments)

Run **one script per node** on the matching host. Fixes etcd v2, Patroni ExecStart, User=intellidb, HAProxy socket dir (node1), starts services.

```bash
# Fix line endings if copied from Windows
sed -i 's/\r$//' scripts/fix-node1.sh scripts/fix-node2.sh scripts/fix-node3.sh

# On node1 (172.16.15.36) – HAProxy node
sudo bash scripts/fix-node1.sh

# On node2 (172.16.15.37)
sudo bash scripts/fix-node2.sh

# On node3 (172.16.15.38)
sudo bash scripts/fix-node3.sh
```

**Order:** Run fix-node1 first, then fix-node2, then fix-node3. Each script: enables etcd v2 (unquoted), fixes Patroni unit (-c, User=intellidb), creates HAProxy socket dir inside chroot (node1 only), starts Patroni.

## Other scripts

| Script | Purpose |
|--------|---------|
| `fix-node1.sh` | Fix node1: etcd v2, Patroni unit, HAProxy, start Patroni. |
| `fix-node2.sh` | Fix node2: etcd v2, Patroni unit, start Patroni. |
| `fix-node3.sh` | Fix node3: etcd v2, Patroni unit, start Patroni. |
| `fix-etcd-v2-for-patroni.sh` | Install etcd 3.5.x from tarball (v2 API for Patroni). Run on each node if etcd was 3.6+. |
| `reset-etcd-data-for-3_5.sh` | Wipe etcd data dir for 3.5.x after downgrade from 3.6. Run on each node. |
| `fix-patroni.sh` | Troubleshoot Patroni: binary, config, systemd unit. Suggests yum if dnf not available. |
| `fix-haproxy.sh` | Troubleshoot HAProxy: binary, config, service. Suggests yum if dnf not available. |
| `download-rpms-in-docker.sh` | Build `rpms/` (RPMs, etcd tarball, Patroni wheels) for offline install. |

## IntelliDB Enterprise 17.5 (port 5555)

- Set in `config.yaml`: `use_intellidb: true`, `intellidb_port: 5555`, `intellidb_user: intellidb`, paths and password as per your install.
- Patroni must run as the same user that runs PostgreSQL (e.g. `intellidb`). The HA fix script and pg_ha_setup option 7 create `patroni.service` with that user.
