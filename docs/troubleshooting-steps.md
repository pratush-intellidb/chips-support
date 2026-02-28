### When something fails, what should you do?

Think in layers: **config → packages → services → cluster tools**. Here’s a practical checklist you can follow every time.

---

### 1. Basic sanity checks (on each node)

- **Confirm you’re using the right script + config**
  - **Script path**: make sure you are running the updated `pg_ha_setup.py` you edited (not some older copy under `/srv/...`).
  - **Config**: confirm `--config config.yaml` is passed and:
    - `etcd_nodes` / `etcd_ips` lists match reality and have the same length.
    - `current_node` is one of `etcd_nodes`.
    - `current_node_ip` is this host’s IP.
- **Run menu 1: Validate System Requirements**
  - If any check shows `FAIL` (root, RHEL 9, firewalld, port conflicts, etc.), fix that first.
  - Typical fixes:
    - Start firewalld: `systemctl start firewalld && systemctl enable firewalld`
    - Stop conflicting services on ports 5432/5555/8008/2379/2380/5000.

---

### 2. etcd‑related problems

If `Configure etcd` finishes but `systemctl status etcd` shows FAILED:

1. **Check the env file**:

   ```bash
   sudo cat /etc/etcd/etcd.conf
   ```

   Confirm:

   - `ETCD_NAME` matches `current_node`.
   - All `ETCD_*_URLS` use **this node’s real IP** (e.g. `172.16.15.37`).
   - `ETCD_INITIAL_CLUSTER` lists all 3 nodes with correct IPs.

2. **Read the detailed logs** (avoid truncated `>` lines):

   ```bash
   journalctl -u etcd -n 50
   ```

   Look for:
   - `unrecognized environment variable` → wrong `ETCD_*` name or typo.
   - `failed to verify ...` or `advertise client URLs ...` → usually IP/DNS mismatch.

3. **Common fixes**:
   - IP mismatch: correct `current_node_ip` and `etcd_ips` in `config.yaml`, rerun menu 4.
   - Old data: if you’re rebuilding from scratch, you may need to **wipe etcd data** (carefully!) on all nodes:
     ```bash
     systemctl stop etcd
     rm -rf /var/lib/etcd/*
     # then rerun Configure etcd, then start etcd
     ```

4. **Patroni fails with `ValueError: Invalid IPv6 URL` or `curl .../v2/machines` returns 404**:
   - **Invalid IPv6 URL** is caused by IPv4 in brackets (e.g. `http://[172.16.15.36]:2379`). Python treats bracketed hosts as IPv6; IPv4 in brackets is invalid.
   - etcd **3.6+** removed the v2 API; Patroni’s `etcd` DCS driver requires it.
   - **Fix for Invalid IPv6 URL:** Remove brackets around IPv4 in etcd.conf and patroni.yml (e.g. `[172.16.15.36]` -> `172.16.15.36`):
     ```bash
     sudo sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/etcd/etcd.conf
     sudo sed -i 's/\[\([0-9][0-9.]*\)\]/\1/g' /etc/patroni/patroni.yml
     sudo systemctl restart etcd
     sudo systemctl restart patroni
     ```
     Or run `fix-node1.sh`, `fix-node2.sh`, `fix-node3.sh` on the respective nodes.
   - **Fix for 404:** Install etcd **3.5.x** on all nodes:
     ```bash
     sudo bash scripts/fix-etcd-v2-for-patroni.sh
     ```
     Or pass a local tarball: `sudo bash scripts/fix-etcd-v2-for-patroni.sh ./rpms/etcd-v3.5.15-linux-amd64.tar.gz`
   - Then restart Patroni on each node: `systemctl restart patroni`.

---

### 3. HAProxy issues

If menu 8 prints “Configure HAProxy failed: …” or the service is down:

1. **Check config file**:

   ```bash
   sudo cat /etc/haproxy/haproxy.cfg
   ```

   Verify:

   - `frontend pg_frontend` has the expected `bind <haproxy_bind>:<haproxy_port>`.
   - `backend pg_write` lists all 3 servers with correct IPs and DB port.

2. **Validate manually**:

   ```bash
   sudo haproxy -c -f /etc/haproxy/haproxy.cfg
   ```

   - If this fails, fix what it complains about (syntax, unknown options, wrong paths).

3. **Service status**:

   ```bash
   systemctl status haproxy -l
   journalctl -u haproxy -n 50
   ```

   - Fix any obvious errors (missing cert files if you enable TLS, port in use, etc.).
   - After fixing, rerun menu 8 or reload: `systemctl reload haproxy`.

---

### 4. Patroni / PostgreSQL issues

If cluster doesn’t come up or `Check Cluster Health` fails:

1. **Check Patroni config**:

   ```bash
   sudo cat /etc/patroni/patroni.yml
   ```

   Confirm:

   - `etcd.hosts` lists correct etcd IPs/ports.
   - `listen` / `connect_address` use the node’s correct IP and DB port.
   - `data_dir`, `bin_dir` point to real paths.

2. **Check Patroni service**:

   ```bash
   systemctl status patroni -l
   journalctl -u patroni -n 50
   ```

   Look for:

   - Connection errors to etcd → fix etcd first.
   - Permission/SELinux issues on data dirs → go back to menu 9 (SELinux) and run it, then check AVCs:
     ```bash
     ausearch -m avc -ts recent
     ```

3. **Check cluster view**:

   ```bash
   patronictl -c /etc/patroni/patroni.yml list
   ```

   - If this fails, note the error (e.g. etcd not reachable, no leader, auth error).

4. **`patroni: error: unrecognized arguments: -c`** (systemd):

   The **patroni** daemon takes the config file as a **positional** argument, not `-c`. The `-c` flag is only for **patronictl**.

   - Wrong: `ExecStart=/usr/local/bin/patroni -c /etc/patroni/patroni.yml`
   - Correct: `ExecStart=/usr/local/bin/patroni /etc/patroni/patroni.yml`

   Edit the unit and reload:

   ```bash
   sudo sed -i 's|patroni -c /etc/patroni/patroni.yml|patroni /etc/patroni/patroni.yml|' /etc/systemd/system/patroni.service
   sudo systemctl daemon-reload
   sudo systemctl restart patroni
   ```

---

### 5. firewalld / SELinux problems

- **Ports blocked**:
  - On each node, run menu 2 and check “Verify ports are open”.
  - Or from CLI:
    ```bash
    firewall-cmd --zone=public --list-ports
    ```
  - Add missing ones: `firewall-cmd --permanent --add-port=5432/tcp` (or 5555, 2379, 2380, 5000, 8008), then `firewall-cmd --reload`.

- **SELinux denials**:
  - Even after menu 9, if services still fail mysteriously, run:
    ```bash
    ausearch -m avc -ts recent
    ```
  - Any denials will point to wrong labels/paths → usually fixed by:
    ```bash
    restorecon -Rv <path>
    ```

---

### 6. Network / connectivity checks

If nodes don’t see each other:

- Use the built‑in connectivity check (menu 2 → option 7).
- Or manually:
  ```bash
  # from each node, test etcd/Patroni/db on the others
  nc -zv <other_node_ip> 2379
  nc -zv <other_node_ip> 2380
  nc -zv <other_node_ip> 8008
  nc -zv <other_node_ip> 5432   # or 5555
  ```

Fix firewall, routing, or IP mistakes accordingly.

---

### 7. When you’re stuck

For any failing menu option:

1. Note **which option** you ran (e.g. “4 Configure etcd on node2”).
2. Collect:
   - The **exact menu output** (with the friendly error message).
   - The related `systemctl status ...` and `journalctl -u ... -n 50`.
3. Share those logs; they usually point directly to whether it’s:
   - A **bad path / port** in config.
   - A **network/firewall** issue.
   - An **OS package / service** issue (missing binary, permissions, SELinux).

I can then map that output back to exactly which part of the setup to change (and whether it’s a script config vs OS‑level fix).