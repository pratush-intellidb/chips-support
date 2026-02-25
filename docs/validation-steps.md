### Minimal checklist to say “setup is OK”

Run these **on each node**, then one final check from an app/client host.

---

### 1. All services are healthy

On **every node**:

```bash
systemctl status etcd -l
systemctl status patroni -l
systemctl status haproxy -l
```

You want all three to be **active (running)**. Any “failed” here = fix before proceeding.

---

### 2. Patroni sees a healthy cluster

On **any one node**:

```bash
patronictl -c /etc/patroni/patroni.yml list
```

Validate:

- You see **3 members**, all with `Cluster` = your cluster name.
- Exactly **one** is `Role` = `Leader`.
- The other two are `Replica` (or `Standby` depending on config).
- `Lag in MB` is reasonable (usually 0‑ish when idle).

If this is true, **etcd + Patroni + PostgreSQL are in sync**.

---

### 3. HAProxy is routing correctly

From an **application server** or any host that should connect via HAProxy:

```bash
psql "host=<haproxy_ip> port=<haproxy_port> dbname=postgres user=<superuser>"
```

For standard PostgreSQL:

```bash
psql "host=<haproxy_ip> port=5000 dbname=postgres user=postgres"
```

For IntelliDB:

```bash
psql "host=<haproxy_ip> port=5000 dbname=intellidb user=intellidb"
```

In `psql`:

```sql
SELECT inet_server_addr(), inet_server_port(), pg_is_in_recovery();
```

- `pg_is_in_recovery()` should be **false** (you’re on the leader via HAProxy).
- The IP/port should match the **current leader node**.

If this works, apps can safely use HAProxy.

---

### 4. Replication actually works

On the **leader** (connect directly or via HAProxy):

```sql
CREATE TABLE ha_test (id int PRIMARY KEY);
INSERT INTO ha_test VALUES (1);
```

Then, on each **replica** (connect directly to its DB port):

```sql
SELECT * FROM ha_test;
```

You should see the row `(1)`. If yes, **replication is functioning**.

---

### 5. Optional: controlled failover test

1. From any node:

   ```bash
   patronictl -c /etc/patroni/patroni.yml list
   ```

   Note which node is **Leader**.

2. Trigger a **manual failover**:

   ```bash
   patronictl -c /etc/patroni/patroni.yml failover --force
   ```

   (Follow the prompts, choose a specific target node.)

3. Run `patronictl list` again:

   - A different node should now be **Leader**.
   - Connect via HAProxy again and re‑run:

     ```sql
     SELECT inet_server_addr(), pg_is_in_recovery();
     ```

     to confirm HAProxy now sends you to the **new leader**.

If all 5 checks pass, you can confidently say **the HA setup is OK**.