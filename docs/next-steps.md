# Next Steps After ha-cluster-fix-and-validate.sh

Follow these on **each node** in order. Your script output showed: etcd running but health check returned 000, Patroni binary not found in PATH on some nodes, Patroni failed to start on node2/node3, and patronictl not in PATH.

---

## 1. Verify etcd (all nodes)

The script checks `http://127.0.0.1:2379`. If your etcd listens only on the node IP, use that instead:

```bash
# Replace with this node's IP (e.g. 172.16.15.36 on node1)
curl -s http://172.16.15.36:2379/health; echo
curl -s http://172.16.15.36:2379/v2/keys/; echo
```

- **`/health`** returning `{"health":"true"}` means etcd is up and healthy.
- **`/v2/machines`** can return **404** in etcd 3.5 — that is normal. Patroni uses **`/v2/keys`** for the DCS; if `curl .../v2/keys/` returns JSON (not 404), the v2 API is fine for Patroni.

So: **health OK + etcd 3.5.15 = you're good.** Ignore the script's `/v2/machines` warning.

**If `/v2/keys/` returns 404:** Patroni needs the etcd v2 API. Enable it on **all three nodes**:

```bash
# On each node, add to /etc/etcd/etcd.conf:
echo 'ETCD_ENABLE_V2=true' | sudo tee -a /etc/etcd/etcd.conf
sudo systemctl restart etcd
# Then verify (use this node's IP):
curl -s http://172.16.15.36:2379/v2/keys/; echo
```

You should get JSON (e.g. `{"action":"get",...}`), not 404. Repeat on node2 and node3 with their IPs. After that, restart Patroni on node1 so it can talk to etcd.

If you want the script's health check to pass using 127.0.0.1, add `127.0.0.1:2379` to etcd's listen-client-urls in `/etc/etcd/etcd.conf` on each node, e.g.:

```text
ETCD_LISTEN_CLIENT_URLS="http://127.0.0.1:2379,http://172.16.15.36:2379"
```

Then: `systemctl restart etcd`.

---

## 2. Install Patroni where missing (node2, node3, and node1 if needed)

On **each node** where the script said "Patroni binary not found":

**Option A – From wheels (offline, same as pg_ha_setup):**

```bash
cd /srv/chips-support-main
sudo pip3 install --no-index --find-links=./rpms/patroni-wheels patroni
```

**Option B – From repo (if you have internet / repo):**

```bash
sudo dnf install -y patroni
# or if dnf not available:
sudo yum install -y patroni
```

Then confirm the binary and path:

```bash
which patroni
which patronictl
# If they are in /usr/local/bin, add to PATH for root (optional):
export PATH="/usr/local/bin:$PATH"
```

**ExecStart must use `-c`:** The correct line is `ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml` (with **`-c`** before the config path). If your unit has `patroni /etc/patroni/patroni.yml` without `-c`, Patroni will exit with status 1. Fix it:

```bash
sudo systemctl edit --full patroni.service
# Set exactly: ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml
# Set User=intellidb (for IntelliDB) or User=postgres
sudo systemctl daemon-reload
sudo systemctl start patroni
```

Or re-run the fix script (it now corrects ExecStart if `-c` is missing):  
`sudo bash scripts/ha-cluster-fix-and-validate.sh node2 172.16.15.37 "172.16.15.36,172.16.15.37,172.16.15.38"` (and similarly for node3).

---

## 3. Fix Patroni service on node2 and node3

On **node2** and **node3** the script reported "Patroni failed to start". Do:

```bash
# Check why it failed
sudo systemctl status patroni -l
sudo journalctl -xeu patroni.service -n 50
```

Common causes:

- **ExecStart missing `-c`** → Unit must be `ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml`. Without `-c`, Patroni exits with status 1. Re-run the fix script or edit the unit as in step 2.
- **Patroni not installed** → do step 2 on that node.
- **Wrong user** → for IntelliDB, `User=` and `Group=` must be `intellidb` (and the config file readable by that user).
- **etcd v2 API disabled** → if on node1 `curl .../v2/keys/` returns 404, add `ETCD_ENABLE_V2=true` to `/etc/etcd/etcd.conf` on all nodes and restart etcd (see step 1).
- **etcd unreachable** → fix etcd (step 1) and/or firewall (ports 2379, 2380).

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl start patroni
sudo systemctl status patroni
```

---

## 4. Put patronictl in PATH (all nodes)

So `patronictl` works and the script can show cluster status:

```bash
export PATH="/usr/local/bin:$PATH"
# Or create a symlink if patronictl is elsewhere:
# sudo ln -sf /path/to/patronictl /usr/local/bin/patronictl
```

To make it permanent for root:

```bash
echo 'export PATH="/usr/local/bin:$PATH"' >> /root/.bashrc
```

---

## 5. Start Patroni on all three nodes (order: node1 → node2 → node3)

Ensure etcd is running on all three, then:

**Node1:**

```bash
sudo systemctl start patroni
sudo systemctl status patroni
```

**Node2:**

```bash
sudo systemctl start patroni
sudo systemctl status patroni
```

**Node3:**

```bash
sudo systemctl start patroni
sudo systemctl status patroni
```

---

## 6. Check cluster health (any node)

```bash
export PATH="/usr/local/bin:$PATH"
patronictl -c /etc/patroni/patroni.yml list
```

You should see **1 Leader** and **2 Replicas**. Example:

```text
+ Cluster: pg-cluster -------+----+-----------+----------------+
| Member  | Host       | Role    | State   | ...            |
+---------+------------+---------+---------+----------------+
| node1   | 172.16.15.36 | Leader  | running | ...            |
| node2   | 172.16.15.37 | Replica | running | ...            |
| node3   | 172.16.15.38 | Replica | running | ...            |
+---------+------------+---------+---------+----------------+
```

---

## 7. Optional: re-run the fix script

After Patroni is installed and running on all nodes and PATH is set:

```bash
cd /srv/chips-support-main
# Node1 (HAProxy node)
sudo bash scripts/ha-cluster-fix-and-validate.sh node1 172.16.15.36 "172.16.15.36,172.16.15.37,172.16.15.38" --haproxy

# Node2
sudo bash scripts/ha-cluster-fix-and-validate.sh node2 172.16.15.37 "172.16.15.36,172.16.15.37,172.16.15.38"

# Node3
sudo bash scripts/ha-cluster-fix-and-validate.sh node3 172.16.15.38 "172.16.15.36,172.16.15.37,172.16.15.38"
```

You should then see etcd warnings gone (if you fixed listen-client-urls), "Patroni binary" OK, and "patronictl list" showing 1 Leader + 2 Replicas.

---

## Quick reference (per node)

| Step | What to do |
|------|------------|
| 1 | Verify etcd: `curl -s http://<this_node_ip>:2379/health` and `/v2/keys/` |
| 2 | Install Patroni if missing: `pip3 install --no-index --find-links=./rpms/patroni-wheels patroni` or `yum install -y patroni` |
| 3 | If Patroni won't start: `systemctl status patroni` and `journalctl -xeu patroni`; fix ExecStart/User and etcd |
| 4 | Add Patroni to PATH: `export PATH="/usr/local/bin:$PATH"` (and add to `/root/.bashrc` if you want) |
| 5 | Start Patroni: `systemctl start patroni` (node1, then node2, then node3) |
| 6 | Check cluster: `patronictl -c /etc/patroni/patroni.yml list` → 1 Leader, 2 Replicas |
