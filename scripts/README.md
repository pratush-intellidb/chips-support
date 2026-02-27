@Scripts
```
How to use it in your environment
Save this on your workstation as fix-etcd-3.5-cluster.sh, copy to /opt/chips-support/ (or similar) on each node.
On each node:

chmod +x fix-etcd-3.5-cluster.sh

# node1
sudo ./fix-etcd-3.5-cluster.sh node1 172.16.15.36 \
  "node1=http://172.16.15.36:2380,node2=http://172.16.15.37:2380,node3=http://172.16.15.38:2380" \
  /tmp/etcd-v3.5.15-linux-amd64.tar.gz

# node2
sudo ./fix-etcd-3.5-cluster.sh node2 172.16.15.37 \
  "node1=http://172.16.15.36:2380,node2=http://172.16.15.37:2380,node3=http://172.16.15.38:2380" \
  /tmp/etcd-v3.5.15-linux-amd64.tar.gz

# node3
sudo ./fix-etcd-3.5-cluster.sh node3 172.16.15.38 \
  "node1=http://172.16.15.36:2380,node2=http://172.16.15.37:2380,node3=http://172.16.15.38:2380" \
  /tmp/etcd-v3.5.15-linux-amd64.tar.gz

```
