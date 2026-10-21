# 09. DNS lookup fails inside the cluster: NetworkPolicy blocks CoreDNS

> **Not verified.** On my test machine the NetworkPolicy was not enforced: kind's default CNI (kindnet) needs the kernel's nfqueue support for NetworkPolicy, and that kernel did not have it, so DNS kept working. To reproduce it, use a cluster whose CNI enforces NetworkPolicy (for example Calico or Cilium). The manifests and the write-up below are provided, but there is no recorded output for this scenario.

## Try it
```bash
kubectl create namespace pb-09
kubectl -n pb-09 apply -f scenarios/09-dns-blocked-by-networkpolicy/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
After a security change, the app cannot resolve any name (`bad address`, `i/o timeout`), but CoreDNS itself is healthy.

## Root cause
An egress NetworkPolicy selects every pod in the namespace and only allows TCP/80 to pods in the same namespace. DNS goes to CoreDNS in `kube-system` on UDP/TCP 53, which is now denied. The same lookup from another namespace works, which proves CoreDNS is fine and the problem is local.

## Fix
Add an egress rule that allows UDP and TCP 53 to the `kube-dns` pods in `kube-system`.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -1,3 +1,3 @@
-# "Lock down egress" policy that forgot DNS.
+# Same egress lock-down, plus an explicit rule for cluster DNS.
 apiVersion: networking.k8s.io/v1
 kind: NetworkPolicy
@@ -8,9 +8,18 @@
   policyTypes: [Egress]
   egress:
-    # only allow traffic to pods in this namespace on 80 ... and nothing else
+    # allow traffic to pods in this namespace on 80
     - to:
         - podSelector: {}
       ports:
         - {protocol: TCP, port: 80}
+    # allow DNS to CoreDNS in kube-system
+    - to:
+        - namespaceSelector:
+            matchLabels: {kubernetes.io/metadata.name: kube-system}
+          podSelector:
+            matchLabels: {k8s-app: kube-dns}
+      ports:
+        - {protocol: UDP, port: 53}
+        - {protocol: TCP, port: 53}
 ---
 apiVersion: apps/v1
```

## Prevention
- Every default-deny egress policy ships with a DNS allow rule (keep it in a shared template).
- Test from inside the namespace (`kubectl exec ... nslookup`) after any NetworkPolicy change.
- Alert on CoreDNS health (`CoreDNSDown` from the default rules) and on app error rate.

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`AppHighErrorRate`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/AppHighErrorRate.md)
