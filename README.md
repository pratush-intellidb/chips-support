# IntelliDB PostgreSQL HA Setup on RHEL 9

Menu-driven Python 3 tool for PostgreSQL 17 High Availability on RHEL 9 using **Patroni**, **etcd**, **HAProxy**, **firewalld**, **SELinux**, and **systemd**. Supports standard PostgreSQL 17 (port 5432) and **IntelliDB Enterprise** (port 5555, user `intellidb`, database `intellidb`).

**Version:** 1.0.0

---

## Quick configuration steps

| Step | Action |
|------|--------|
| 1 | Copy project (including `rpms/`) to each of 3 RHEL 9 nodes. |
| 2 | `cp config.example.yaml config.yaml` — set `etcd_ips`, `current_node`, `current_node_ip` **per node**; set passwords or leave empty to be prompted. |
| 3 | `sudo python3 pg_ha_setup.py` (or `sudo python3 pg_ha_setup.py --config config.yaml`). |
| 4 | Menu: **1** Validate → **2** Open firewall ports → **3** Install packages. |
| 5 | Menu: **4** Configure etcd → **5** Install PostgreSQL 17 (skip if IntelliDB only) → **7** Configure Patroni (choose **y** for IntelliDB mode if using port 5555) → **8** HAProxy → **9** SELinux → **10** Initialize cluster. |
| 6 | Repeat steps 2–5 on the other two nodes (same `config.yaml`, different `current_node` / `current_node_ip`). |
| 7 | Connect apps to HAProxy: `<haproxy_ip>:5000` (or your `haproxy_port`). |

**IntelliDB Enterprise (already installed on 3 nodes, port 5555):** Set in `config.yaml`: `use_intellidb: true`, and optionally `intellidb_port: 5555`, `intellidb_user: intellidb`, `intellidb_password: "IDBE@2025"`, `intellidb_data_dir`, `intellidb_bin_dir`. At step 5, choose **7** and answer **y** when asked for IntelliDB mode. Stop existing IntelliDB on each node before initializing Patroni.

---

## Ready to run (offline)

- Ensure **`rpms/`** is populated (RPMs + etcd tarball + patroni-wheels). Use Docker to build it once (see **Downloading RPMs** below).
- On each server: run `sudo python3 pg_ha_setup.py` from the project directory. Menu **3** installs from `./rpms/` (no internet).

---

## Table of Contents

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
