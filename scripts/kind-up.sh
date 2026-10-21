#!/usr/bin/env bash
# One-node kind test cluster for the playbook.
# kindnet enforces NetworkPolicy only if the host kernel has nfqueue support (scenario 09).
set -euo pipefail
CLUSTER="${CLUSTER:-playbook}"
if kind get clusters | grep -qx "$CLUSTER"; then echo "cluster $CLUSTER exists"; exit 0; fi
cat <<YAML | kind create cluster --name "$CLUSTER" --wait 120s --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  kubeProxyMode: nftables   # works on kernels without xt_statistic
nodes:
  - role: control-plane
YAML
echo "Pre-pulling demo images (optional, makes the scenarios faster)"
for img in busybox:1.36 nginx:1.27-alpine nginx:1.28-alpine polinux/stress:1.0.4; do
  docker pull -q "$img" >/dev/null && kind load docker-image "$img" --name "$CLUSTER" >/dev/null || true
done
