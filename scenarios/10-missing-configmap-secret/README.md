# 10. Missing ConfigMap / Secret: pod stuck in CreateContainerConfigError

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 3s; healthy 16s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-10
kubectl -n pb-10 apply -f scenarios/10-missing-configmap-secret/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod never starts; STATUS shows CreateContainerConfigError. There are no logs.


```console
$ kubectl -n pb-10 get pods
NAME                       READY   STATUS                       RESTARTS   AGE
notifier-788cb84dd-hczjc   0/1     CreateContainerConfigError   0          3s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-10 logs deploy/notifier
Error from server (BadRequest): container "app" in pod "notifier-788cb84dd-hczjc" is waiting to start: CreateContainerConfigError

$ kubectl -n pb-10 describe pod -l app=notifier | sed -n '/Events:/,$p' | grep -E 'Warning|Failed' | head -3
  Warning  Failed     2s (x2 over 2s)  kubelet            spec.containers{app}: Error: configmap "notifier-config" not found

$ kubectl -n pb-10 get configmap,secret
NAME                         DATA   AGE
configmap/kube-root-ca.crt   1      3s
```

## Root cause
The container reads `MODE` from ConfigMap `notifier-config` and `SMTP_PASSWORD` from Secret `notifier-smtp`. Neither exists, so the kubelet cannot build the container config and never starts it. The event names only the first missing object; fix it and the next one appears.

## Fix
Create the ConfigMap and the Secret (the fixed manifest includes them; in real life the Secret comes from your secret manager, not from git). The kubelet retries and the pod starts by itself.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -1,2 +1,17 @@
+apiVersion: v1
+kind: ConfigMap
+metadata:
+  name: notifier-config
+data:
+  mode: digest
+---
+apiVersion: v1
+kind: Secret
+metadata:
+  name: notifier-smtp
+type: Opaque
+stringData:
+  password: demo-only-not-a-real-password
+---
 apiVersion: apps/v1
 kind: Deployment
@@ -19,8 +34,8 @@
             - name: MODE
               valueFrom:
-                configMapKeyRef: {name: notifier-config, key: mode}   # ConfigMap was never created
+                configMapKeyRef: {name: notifier-config, key: mode}
             - name: SMTP_PASSWORD
               valueFrom:
-                secretKeyRef: {name: notifier-smtp, key: password}     # Secret was never created
+                secretKeyRef: {name: notifier-smtp, key: password}
           resources:
             requests: {cpu: 10m, memory: 16Mi}
```

After the fix:

```console
$ kubectl -n pb-10 get pods
NAME                       READY   STATUS    RESTARTS   AGE
notifier-788cb84dd-hczjc   1/1     Running   0          20s

$ kubectl -n pb-10 logs deploy/notifier
mode=digest
```

## Prevention
- Deploy config objects in the same Helm release / kustomization as the app.
- Use `optional: true` only for truly optional keys.
- Alert `PodNotReady` / `DeploymentReplicasMismatch`.

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`DeploymentReplicasMismatch`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/DeploymentReplicasMismatch.md)

## Time to fix in the demo
16 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
