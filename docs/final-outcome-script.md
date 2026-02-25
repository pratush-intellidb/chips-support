### High level

If you run `pg_ha_setup.py` successfully (with the recommended menu steps on all 3 nodes), you end up with a **3‑node PostgreSQL + Patroni + etcd + HAProxy HA cluster**, ready for apps to connect to via HAProxy.

Here’s what gets configured, component by component.

---

### 1. Packages and services

On each node it will:

- Install **PostgreSQL 17** (or use **IntelliDB** if `use_intellidb: true`).
- Install **etcd**, **Patroni**, **HAProxy**, **firewalld**, and required Python libs.
- Enable systemd services where appropriate:
  - `etcd`
  - `patroni`
  - `haproxy`

---

### 2. etcd (DCS)

On each node it will:

- Create `/etc/etcd/etcd.conf` with variables derived from your `config.yaml`:
  - `ETCD_NAME` (node name)
  - `ETCD_DATA_DIR`
  - `ETCD_LISTEN_CLIENT_URLS`, `ETCD_LISTEN_PEER_URLS`
  - `ETCD_INITIAL_ADVERTISE_CLIENT_URLS`, `ETCD_INITIAL_ADVERTISE_PEER_URLS`
  - `ETCD_ADVERTISE_CLIENT_URLS`
  - `ETCD_INITIAL_CLUSTER` (all 3 nodes’ names + IPs)
  - `ETCD_INITIAL_CLUSTER_STATE="new"` (for fresh cluster)
- Create or override `etcd.service` so it uses that env file.
- Run `systemctl daemon-reload`, `enable etcd`, `start etcd`.

Result: **3‑node etcd cluster** used by Patroni as the distributed configuration store.

---

### 3. PostgreSQL data directory

On each node it will:

- Install `postgresql17-server` and `postgresql17-contrib` (unless using IntelliDB mode where DB already exists).
- Ensure the data directory exists and is owned by `postgres`:
  - Standard: `/var/lib/pgsql/17/data`
  - IntelliDB: whatever `intellidb_data_dir` you configured.
- It **does not** directly initialize/postgresql‑17‑setup; Patroni bootstraps the cluster.

Result: **Data directories ready for Patroni** to initialize and manage.

---

### 4. Patroni

On each node it will:

- Build and write `/etc/patroni/patroni.yml` with:
  - `scope` = your `cluster_name`.
  - `name` = that node’s `current_node`.
  - `restapi.listen/connect_address` = `<current_node_ip>:8008`.
  - `etcd.hosts` = all your `etcd_ips:2379`.
  - Bootstrap DCS settings (TTL, failover limits, etc.).
  - `pg_hba` rules (with a warning that `0.0.0.0/0` is permissive).
  - Users:
    - `replicator` user with replication privileges and the password you provided.
    - Superuser (`postgres` or `intellidb`) with your configured password.
  - PostgreSQL section:
    - `listen` / `connect_address` = `<current_node_ip>:port` (5432 or 5555 for IntelliDB).
    - `data_dir`, `bin_dir` based on standard vs IntelliDB mode.
    - Basic parameters (max_connections, wal settings, etc.) suitable for HA.

- You then use **Initialize Cluster** to start Patroni and bootstrap the first primary.

Result: **Patroni‑managed PostgreSQL instances** on all 3 nodes, using etcd as DCS.

---

### 5. HAProxy

On each node it will:

- Generate `/etc/haproxy/haproxy.cfg` with:
  - A `pg_frontend` listening on `haproxy_bind:haproxy_port` (default `0.0.0.0:5000`).
  - A `pg_write` backend with `server` lines for each node (`etcd_nodes` + `etcd_ips`) on the DB port (5432 or 5555).
  - TCP mode, basic health checks using Patroni’s REST API (via `httpchk` on port 8008).

- Validate the config with `haproxy -c -f /etc/haproxy/haproxy.cfg`.
- Reload the HAProxy service.

Result: **A load‑balancing / failover entry point** so applications connect to **`<haproxy_ip>:haproxy_port`**, not directly to PostgreSQL.

---

### 6. Firewall and SELinux

On each node it can:

- **firewalld**:
  - Open required ports permanently (if you choose that menu option):
    - DB port (5432 or 5555), 8008, 2379, 2380, HAProxy port, and optional read‑replica port.
  - Reload firewalld to apply rules.

- **SELinux**:
  - Run `restorecon -Rv` on:
    - PostgreSQL data dir
    - `/var/lib/etcd`
    - `/etc/patroni`
    - `/var/log/patroni`
  - Print hints to inspect AVCs if things still fail.

Result: **Ports opened and SELinux labels corrected** for the key components.

---

### 7. Health checks, failover, backup

It also provides utilities:

- **Check Cluster Health**:
  - Runs `patronictl -c /etc/patroni/patroni.yml list` and shows the cluster state.

- **Simulate Failover**:
  - Calls `patronictl failover <cluster_name> --force` after a confirmation prompt.

- **Backup Using pg_basebackup**:
  - Prepares a `pg_basebackup` command as `postgres` user, to take a base backup into `/var/lib/pgsql/backups/basebackup_<timestamp>`.

Result: You can **verify status**, simulate failover, and take **logical base backups** through the menu.

---

### Final state

After successful runs on all 3 nodes, your environment is:

- A **3‑node PostgreSQL/IntelliDB HA cluster** managed by Patroni.
- **etcd** as the DCS backing Patroni.
- **HAProxy** in front, listening on a known port (default 5000) for app connections.
- **firewalld** updated to allow the needed ports.
- **SELinux** contexts fixed for key directories.
- Configuration stored in:
  - `/etc/etcd/etcd.conf`
  - `/etc/patroni/patroni.yml`
  - `/etc/haproxy/haproxy.cfg`

**Client entrypoint and HAProxy node choice:**

- In a 3‑node deployment with no separate HAProxy VM, choose **one node** (for example `node1`) to run menu option **8 – Configure HAProxy**.  
- On the other two nodes, you can **skip option 8**, so applications always connect to that single HAProxy endpoint.  
- Applications should connect to **`<HAProxy node IP>:<haproxy_port>`** (for example `172.16.15.36:5000`), not directly to `:5432`/`:5555` on the database nodes.