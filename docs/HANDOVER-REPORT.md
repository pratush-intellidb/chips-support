# IntelliDB PostgreSQL HA Setup – Handover Report

**Date:** February 28, 2026  
**Environment:** RHEL 9, IntelliDB PostgreSQL 17.5 HA (Patroni, etcd, HAProxy)  
**Nodes:** 3 VMs (node1, node2, node3)

---

## 1. Environment Overview

| Node   | Hostname              | IP            | Role                          |
|--------|------------------------|---------------|-------------------------------|
| node1  | DCSDCD34VMWHCIP        | 172.16.15.36  | HAProxy, etcd, Patroni        |
| node2  | DCSDCD35VMWHCIP (assumed) | 172.16.15.37 | etcd, Patroni                 |
| node3  | DCSDCD36VMWHCIP        | 172.16.15.38  | etcd, Patroni                 |

**Package manager:** `yum` (dnf not available at customer site)  
**Project path:** `/srv/chips-support-main` or `chips-support-main` (as deployed)

---

## 2. Work Completed to Date

### 2.1 etcd

| Action | Status | Details |
|--------|--------|---------|
| Downgrade to etcd 3.5.x | Done | Patroni requires v2 API; etcd 3.6+ removed it |
| `ETCD_ENABLE_V2=true` | Done | Added to `/etc/etcd/etcd.conf` (no quotes) |
| `ETCD_ADVERTISE_CLIENT_URLS` | Done | etcd 3.5+ requires this; `ETCD_INITIAL_ADVERTISE_CLIENT_URLS` is unrecognized |
| Remove brackets around IPv4 in URLs | Done | Fix for Patroni "Invalid IPv6 URL" error |

**etcd config location:** `/etc/etcd/etcd.conf`  
**Data dir:** `/var/lib/etcd`

### 2.2 Patroni

| Action | Status | Details |
|--------|--------|---------|
| ExecStart fix | Done | Must be `ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml` |
| User/Group | Done | Set to `intellidb` for IntelliDB Enterprise |
| Config ownership | Done | `chown intellidb:intellidb /etc/patroni/patroni.yml` |
| PATH for patronictl | Done | `export PATH="/usr/local/bin:$PATH"` |

**Patroni config:** `/etc/patroni/patroni.yml`  
**Patroni unit:** `/etc/systemd/system/patroni.service`

### 2.3 HAProxy (node1 only)

| Action | Status | Details |
|--------|--------|---------|
| Chroot removed | Done | Using `stats socket /tmp/haproxy/admin.sock` |
| SELinux | Done | `setenforce 0` (permissive) for socket access |
| Socket dir | Done | `mkdir -p /var/lib/haproxy/run/haproxy` |

**HAProxy config:** `/etc/haproxy/haproxy.cfg`

### 2.4 Scripts Created/Updated

| Script | Purpose |
|--------|---------|
| `fix-node1.sh` | Fix node1: etcd v2, ETCD_ADVERTISE_CLIENT_URLS, Patroni unit, HAProxy, start Patroni |
| `fix-node2.sh` | Fix node2: etcd v2, ETCD_ADVERTISE_CLIENT_URLS, Patroni unit, start Patroni |
| `fix-node3.sh` | Fix node3: etcd v2, ETCD_ADVERTISE_CLIENT_URLS, Patroni unit, start Patroni |
| `ha-cluster-fix-and-validate.sh` | All-in-one: validate etcd, Patroni, HAProxy; fix configs; verify cluster |
| `fix-etcd-v2-for-patroni.sh` | Install etcd 3.5.x from tarball |
| `reset-etcd-data-for-3_5.sh` | Wipe etcd data after 3.6→3.5 downgrade |

---

## 3. Current Status (as of last session)

### Node1 (DCSDCD34VMWHCIP – 172.16.15.36)

| Component | Status | Notes |
|-----------|--------|-------|
| etcd | Running | Active for ~18+ min at last check |
| Patroni | Failing | `activating (auto-restart)`, exit code 2 |
| HAProxy | Running | Logs: "backend pg_write has no server available!" |
| patronictl | Failing | `ValueError: Invalid IPv6 URL` |

**Root cause (Patroni):** Patroni fails when parsing etcd URLs that have IPv4 in brackets (e.g. `http://[172.16.15.36]:2379`). Python treats bracketed hosts as IPv6; IPv4 in brackets is invalid.

### Node2 (172.16.15.37)

| Component | Status | Notes |
|-----------|--------|-------|
| etcd | Unknown | Not explicitly reported in last logs |
| Patroni | Unknown | Earlier: "Patroni failed to start" |
| HAProxy | N/A | HAProxy only on node1 |

### Node3 (DCSDCD36VMWHCIP – 172.16.15.38)

| Component | Status | Notes |
|-----------|--------|-------|
| etcd | Was failing | Fixed with `ETCD_ADVERTISE_CLIENT_URLS`; fix-node3.sh run |
| Patroni | Unknown | "Patroni may not be active" per fix-node3.sh |
| patronictl | Failing | "patronictl failed - cluster may still be forming" |

---

## 4. Outstanding Issues

### 4.1 Patroni "Invalid IPv6 URL" (node1, possibly all nodes)

**Fix to apply on each node:**

```bash
# Remove brackets around IPv4 in etcd and Patroni configs
sudo sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/etcd/etcd.conf
sudo sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/patroni/patroni.yml
sudo systemctl restart etcd
sudo systemctl restart patroni
```

Or run the per-node fix scripts (after syncing latest from repo):

```bash
# Fix line endings if copied from Windows
sed -i 's/\r$//' scripts/fix-node1.sh scripts/fix-node2.sh scripts/fix-node3.sh

# On each node
sudo bash scripts/fix-node1.sh   # node1
sudo bash scripts/fix-node2.sh   # node2
sudo bash scripts/fix-node3.sh   # node3
```

### 4.2 HAProxy "backend pg_write has no server available!"

This is expected until Patroni is healthy on all 3 nodes. HAProxy routes to Patroni-managed PostgreSQL; with no healthy cluster, there are no backends.

**Resolution:** Fix Patroni first (see 4.1). Once `patronictl list` shows 1 Leader + 2 Replicas, HAProxy should detect backends.

### 4.3 etcd on node3

If etcd still fails on node3 after `ETCD_ADVERTISE_CLIENT_URLS` fix:

```bash
# Add if missing
echo 'ETCD_ADVERTISE_CLIENT_URLS="http://172.16.15.38:2379"' | sudo tee -a /etc/etcd/etcd.conf
sudo systemctl restart etcd
```

If data corruption (e.g. after 3.6→3.5 downgrade):

```bash
sudo systemctl stop etcd
sudo rm -rf /var/lib/etcd/*
sudo systemctl start etcd
```

---

## 5. Recommended Next Steps

1. **Apply Invalid IPv6 URL fix on all 3 nodes** (section 4.1).
2. **Verify etcd on all nodes:**
   ```bash
   systemctl status etcd
   curl -s http://<node_ip>:2379/health
   curl -s http://<node_ip>:2379/v2/keys/
   ```
3. **Start Patroni on all nodes** (order: node1 → node2 → node3).
4. **Verify cluster:**
   ```bash
   export PATH="/usr/local/bin:$PATH"
   patronictl -c /etc/patroni/patroni.yml list
   ```
   Expect: 1 Leader, 2 Replicas.
5. **Check HAProxy** – "backend pg_write has no server available!" should clear once cluster is healthy.
6. **Optional:** Re-run `ha-cluster-fix-and-validate.sh` on each node with config or manual args.

---

## 6. Key Paths and Commands

| Item | Path/Command |
|------|--------------|
| etcd config | `/etc/etcd/etcd.conf` |
| Patroni config | `/etc/patroni/patroni.yml` |
| Patroni unit | `/etc/systemd/system/patroni.service` |
| HAProxy config | `/etc/haproxy/haproxy.cfg` |
| etcd logs | `journalctl -u etcd -n 50` |
| Patroni logs | `journalctl -xeu patroni -n 50` |
| Cluster status | `patronictl -c /etc/patroni/patroni.yml list` |

---

## 7. Documentation References

| Document | Purpose |
|----------|---------|
| `docs/troubleshooting-steps.md` | Step-by-step troubleshooting |
| `docs/next-steps.md` | Post-setup fixes after ha-cluster-fix-and-validate.sh |
| `docs/validation-steps.md` | Validation checklist |
| `scripts/README.md` | Fix scripts usage |
| `README.md` | Main setup guide |

---

## 8. Contact / Handover Notes

- Project uses `yum` (not `dnf`) for package installs.
- IntelliDB Enterprise: port 5555, user `intellidb`, database `intellidb`.
- HAProxy listens on port 5000 (configurable via `haproxy_port` in config).
- For offline install, use `rpms/` and `scripts/download-rpms-in-docker.sh` to populate.

---

*Report generated from session logs. Verify current state on each VM before proceeding.*
