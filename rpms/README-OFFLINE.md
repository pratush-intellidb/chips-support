# IntelliDB PostgreSQL HA – Offline RPMs and Binaries

This folder was populated by the Docker-based download. Use it on **RHEL 9 / Rocky Linux 9** servers without internet.

## Contents

### RPMs (install with dnf)

- **postgresql17-server**, **postgresql17-contrib** – PostgreSQL 17
- **haproxy** – load balancer
- **firewalld** – firewall (if not already installed)
- **python3-psycopg2**, **python3-pyyaml** – Python deps

Install from this directory:

```bash
sudo dnf install -y ./*.rpm
```

(Do not run this from a directory that also contains the etcd tarball or patroni-wheels.)

### etcd (not in EPEL for EL9)

- **etcd-v3.6.8-linux-amd64.tar.gz** – official etcd binary release

Install:

```bash
cd /path/to/rpms
tar xzf etcd-v3.6.8-linux-amd64.tar.gz
sudo cp etcd-v3.6.8-linux-amd64/etcd etcd-v3.6.8-linux-amd64/etcdctl /usr/local/bin/
sudo chmod 755 /usr/local/bin/etcd /usr/local/bin/etcdctl
```

Or use the systemd unit from the IntelliDB setup (option 4); ensure `etcd` and `etcdctl` are on `PATH` (e.g. `/usr/local/bin`).

### Patroni (not in EPEL for EL9)

- **patroni-wheels/** – Patroni and Python dependencies as wheels

Install (offline):

```bash
pip3 install --no-index --find-links=/path/to/rpms/patroni-wheels patroni
```

Or from the project root:

```bash
pip3 install --no-index --find-links=./rpms/patroni-wheels patroni
```

Then run the IntelliDB setup script (menu option 7 configures Patroni; ensure Patroni is on `PATH`).

## Order on the server

**Easiest:** Run from the project root:

```bash
sudo python3 pg_ha_setup.py
```

Then choose **3. Install Required Packages**. The script will install RPMs from `./rpms/`, then etcd from the tarball and Patroni from wheels. Continue with options 4–10.

**Manual alternative:** If you prefer not to use the menu:

1. Install RPMs: `cd rpms && sudo dnf install -y *.rpm`
2. Install etcd binaries from the tarball (see above).
3. Install Patroni from wheels (see above).
4. Run `sudo python3 pg_ha_setup.py` and use options 4–10 (skip option 3).
