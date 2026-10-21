# 01. CrashLoopBackOff: app exits because a required env var is missing

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 28s; healthy 2s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-01
kubectl -n pb-01 apply -f scenarios/01-crashloop-missing-env/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod restarts again and again and shows CrashLoopBackOff. The Deployment never becomes available.


```console
$ kubectl -n pb-01 get pods
NAME                          READY   STATUS             RESTARTS      AGE
orders-api-7dd4d8964b-rxft8   0/1     CrashLoopBackOff   2 (12s ago)   27s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-01 logs deploy/orders-api --previous
FATAL: required env var DATABASE_URL is not set

$ kubectl -n pb-01 describe pod -l app=orders-api | sed -n '/Containers:/,/Conditions:/p' | grep -E 'State|Reason|Exit Code|Restart Count|Last State'
    State:          Waiting
      Reason:       CrashLoopBackOff
    Last State:     Terminated
      Reason:       Error
      Exit Code:    1
    Restart Count:  2

$ kubectl -n pb-01 get events --field-selector reason=BackOff -o custom-columns=REASON:.reason,OBJECT:.involvedObject.name,MESSAGE:.message
REASON    OBJECT                        MESSAGE
BackOff   orders-api-7dd4d8964b-rxft8   Back-off restarting failed container app in pod orders-api-7dd4d8964b-rxft8_pb-01(f5f21685-4cab-4b84-bb3c-83c208708ccd)
```

## Root cause
The container exits with code 1 at start because `DATABASE_URL` is not set. Kubernetes restarts it, each time with a longer back-off delay, which is what CrashLoopBackOff means. The pod events alone do not tell you why; the logs of the *previous* container do.

## Fix
Store the value in a Secret and inject it with `env.valueFrom.secretKeyRef`. Apply the fixed manifest; the Deployment rolls out a new pod that starts normally.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -1,2 +1,10 @@
+apiVersion: v1
+kind: Secret
+metadata:
+  name: orders-db
+type: Opaque
+stringData:
+  url: postgres://orders@orders-db:5432/orders
+---
 apiVersion: apps/v1
 kind: Deployment
@@ -24,4 +32,8 @@
               fi
               echo "connecting to $DATABASE_URL"; while true; do sleep 3600; done
+          env:
+            - name: DATABASE_URL
+              valueFrom:
+                secretKeyRef: {name: orders-db, key: url}
           resources:
             requests: {cpu: 10m, memory: 16Mi}
```

After the fix:

```console
$ kubectl -n pb-01 get pods
NAME                          READY   STATUS        RESTARTS   AGE
orders-api-6c9cc7b7b4-9rrjz   1/1     Running       0          2s
orders-api-7dd4d8964b-rxft8   0/1     Terminating   2          29s

$ kubectl -n pb-01 logs deploy/orders-api
connecting to postgres://orders@orders-db:5432/orders
Found 2 pods, using pod/orders-api-6c9cc7b7b4-9rrjz
```

## Prevention
- Validate required config at start and print a clear error (this app does), so `logs --previous` is useful.
- Keep env vars in the manifest / Helm values next to the code, review them in the PR.
- Alert `PodCrashLooping` (warning, 5m).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodCrashLooping`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodCrashLooping.md)

## Time to fix in the demo
2 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
