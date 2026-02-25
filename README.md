# IntelliDB PostgreSQL HA Setup on RHEL 9

Menu-driven Python 3 tool for PostgreSQL 17 High Availability on RHEL 9 using **Patroni**, **etcd**, **HAProxy**, **firewalld**, **SELinux**, and **systemd**. Supports standard PostgreSQL 17 (port 5432) and **IntelliDB Enterprise** (port 5555, user `intellidb`, database `intellidb`).

**Version:** 1.0.0

---

## Quick setup notes

### Before you start

- **3 nodes** on RHEL 9 (or Rocky/AlmaLinux 9), with root/sudo.
- Project directory on each node (include **`rpms/`** if offline).
- Same **`config.yaml`** on all nodes; only **`current_node`** and **`current_node_ip`** differ per node.

### Standard PostgreSQL 17 (port 5432)

| Step | What to do |
|------|------------|
| 1 | On **each node**: copy project to server (e.g. `/opt/intellidb-ha/`). Include `rpms/` if offline. |
| 2 | `cp config.example.yaml config.yaml`. Edit **per node**: `current_node` (e.g. node1), `current_node_ip` (e.g. 192.168.1.11). Set `etcd_ips` for all 3 nodes once. Passwords: set or leave `""` to be prompted. |
| 3 | Run `sudo python3 pg_ha_setup.py --config config.yaml` (or without `--config` to use defaults). |
| 4 | **1** Validate → **2** Open firewall ports → **3** Install packages. |
| 5 | **4** Configure etcd → **5** Install PostgreSQL 17 → **7** Configure Patroni (answer **n** for IntelliDB) → **8** HAProxy → **9** SELinux → **10** Initialize cluster. |
| 6 | Repeat steps 2–5 on the other two nodes (change `current_node` / `current_node_ip` only). |
| 7 | Connect applications to **`<haproxy_ip>:5000`** (or your `haproxy_port`). |

**HAProxy node (3‑node setup, no extra VM):**  
- Run menu option **8 – Configure HAProxy** on **exactly one node** (for example `node1`).  
- On the other two nodes, you can **skip option 8**, so applications only connect to that node’s `haproxy_bind:haproxy_port` (for example `172.16.15.36:5000`).

### IntelliDB Enterprise (port 5555)

- In **`config.yaml`**: set **`use_intellidb: true`**. Defaults: port **5555**, user **intellidb**, database **intellidb**, password **IDBE@2025**, data dir **/var/lib/intellidb/data**, bin dir **/usr/pgsql-17/bin** (override in YAML if your install differs).
- **Stop** existing IntelliDB on each node before running the HA setup: `systemctl stop intellidb`.
- Follow the same steps as above, but at step 5: skip **5** (Install PostgreSQL 17); at **7** (Patroni) answer **y** for IntelliDB mode.
- After HA is up, applications connect to HAProxy (e.g. `<haproxy_ip>:5000`); HAProxy routes to IntelliDB on port 5555 on the leader.

### Offline (no internet on servers)

- Build **`rpms/`** once using Docker (see **Downloading RPMs**). Copy the full project (including `rpms/`) to each node.
- Menu **3** installs from `./rpms/` (RPMs + etcd tarball + Patroni wheels). No internet needed on the servers.

---

## Table of Contents

- [Quick setup notes](#quick-setup-notes)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Network Ports](#network-ports)
- [Configuration](#configuration)
- [IntelliDB Enterprise](#intellidb-enterprise)
- [Downloading RPMs (Docker)](#downloading-rpms-docker)
- [Command-Line Options](#command-line-options)
- [Menu Reference](#menu-reference)
- [Logging and Troubleshooting](#logging-and-troubleshooting)
- [Security](#security)
- [Support](#support)

---

## Requirements

- **OS:** RHEL 9 or compatible (Rocky Linux 9, AlmaLinux 9, CentOS Stream 9)
- **Root** (sudo) for install and config
- **Python:** 3.6+ (stdlib; PyYAML optional for `--config`)
- **Network:** 3 nodes reachable on 2379, 2380 (etcd)
- **Offline:** Use pre-built `rpms/`; script does not download from the internet

---

## Quick Start

```bash
sudo python3 pg_ha_setup.py
# Or with config file:
sudo python3 pg_ha_setup.py --config config.yaml
```

Recommended menu order: **1** → **2** → **3** → **4** → **7** → **8** → **9** → **10**.

---

## Network Ports

| Port | Service | Purpose |
|------|---------|---------|
| 5432 | PostgreSQL | Client connections (standard) |
| 5555 | IntelliDB | Client connections (IntelliDB Enterprise) |
| 8008 | Patroni REST | Health checks, leader detection |
| 2379 | etcd client | DCS communication |
| 2380 | etcd peer | etcd replication |
| 5000 | HAProxy | Frontend (configurable) |
| 7000 | Read replica | Optional |

Use menu **2** to view details and open firewall ports.

---

## Configuration

```bash
cp config.example.yaml config.yaml
# Edit: etcd_ips, current_node, current_node_ip; passwords (or leave "" to be prompted)
sudo python3 pg_ha_setup.py --config config.yaml
```

- **Per node:** Set `current_node` and `current_node_ip` for that host (e.g. node1/node2/node3).
- **Passwords:** Empty `""` = prompt at runtime (masked).
- Do not commit `config.yaml` with real passwords.

---

## IntelliDB Enterprise

For existing **IntelliDB Enterprise** (PostgreSQL 17 on port **5555**, user **intellidb**, database **intellidb**, password **IDBE@2025**):

- **Default paths** (per IntelliDB Enterprise reference): **Data directory** `/var/lib/intellidb/data`, **bin directory** `/usr/pgsql-17/bin`. Override in `config.yaml` if your install differs.
- In `config.yaml`: set `use_intellidb: true`. Optionally override `intellidb_port`, `intellidb_user`, `intellidb_password`, `intellidb_data_dir`, `intellidb_bin_dir`.
- When running menu **7** (Configure Patroni), answer **y** to “Use IntelliDB Enterprise mode” (or rely on YAML).
- Patroni and HAProxy will use port 5555 and the IntelliDB superuser. Stop any existing IntelliDB service on each node before initializing the cluster.

---

## Downloading RPMs (Docker)

etcd and Patroni are not in EPEL for EL9. Build `rpms/` once with Docker:

**PowerShell (Windows):**
```powershell
docker pull rockylinux:9
docker run --rm -v "${PWD}:/mnt/host" rockylinux:9 bash /mnt/host/scripts/download-rpms-in-docker.sh
```

**Bash (Linux/macOS):**
```bash
docker pull rockylinux:9
docker run --rm -v "$(pwd):/mnt/host" rockylinux:9 bash /mnt/host/scripts/download-rpms-in-docker.sh
```

This fills `rpms/` with RPMs, etcd tarball, and Patroni wheels. Copy the project to servers and run the setup (see **Quick configuration steps**).

Manual steps: **`rpms/README-OFFLINE.md`**.

---

## Command-Line Options

| Option | Description |
|--------|-------------|
| `--config`, `-c` | YAML config file path |
| `--dry-run` | Simulate; no changes |
| `--non-interactive` | With `--config`: validation and port menu only |
| `--version`, `-v` | Print version and exit |

---

## Menu Reference

| # | Option |
|---|--------|
| 1 | Validate System Requirements |
| 2 | Show Required Ports & Open Firewall Ports |
| 3 | Install Required Packages |
| 4 | Configure etcd Cluster |
| 5 | Install PostgreSQL 17 |
| 6 | Configure PostgreSQL Replication |
| 7 | Install & Configure Patroni (IntelliDB mode prompt) |
| 8 | Configure HAProxy |
| 9 | Configure SELinux Policies |
| 10 | Initialize Cluster |
| 11 | Check Cluster Health |
| 12 | Simulate Failover |
| 13 | Backup Using pg_basebackup |
| 14 | Full Automated Setup |
| 15 | Uninstall HA Stack |
| 16 | Security Hardening (Info) |
| 17 | Enable TLS (Self-Signed Certs) |
| 18 | Exit |

---

## Logging and Troubleshooting

- **Log file:** `/var/log/pg_ha_setup.log`
- **HAProxy:** Config validated before reload; errors printed if invalid.
- **SELinux:** `restorecon` skipped with warning if missing; AVC: `ausearch -m avc -ts recent`
- **Offline:** Use `rpms/`; menu **3** installs from there. See `rpms/README-OFFLINE.md`.

---

## Security

- Restrict **pg_hba.conf** by CIDR (avoid 0.0.0.0/0).
- Bind services to **private IPs**.
- Use **TLS** in production (menu **17** for self-signed).
- Consider **etcd** peer/client TLS.
- **Patroni** config file is chmod 0600 (contains passwords).

---

## Support

Provide: menu **1** output, `/var/log/pg_ha_setup.log` excerpts, and `cat /etc/os-release`. Contact your vendor or internal support process.
