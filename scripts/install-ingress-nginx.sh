#!/usr/bin/env bash
# Install ingress-nginx if it is not there yet. Idempotent.
# Uses the "baremetal" manifest (NodePort Service, no hostPorts), so it works on kind, k3s and
# kubeadm clusters, and on hosts where the CNI portmap plugin cannot set up hostPorts.
# Scenario 08 talks to the controller through its ClusterIP Service from inside the cluster.
set -euo pipefail
VERSION="${INGRESS_NGINX_VERSION:-controller-v1.13.3}"
if ! kubectl -n ingress-nginx get deploy ingress-nginx-controller >/dev/null 2>&1; then
  kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/${VERSION}/deploy/static/provider/baremetal/deploy.yaml" >/dev/null
fi
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=480s
# the admission webhook must answer before Ingress objects can be created
kubectl -n ingress-nginx wait --for=condition=complete job/ingress-nginx-admission-patch --timeout=120s >/dev/null 2>&1 || true
