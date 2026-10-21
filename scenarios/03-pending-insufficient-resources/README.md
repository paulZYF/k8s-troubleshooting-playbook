# 03. Pending: not enough CPU / memory on any node

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 0s; healthy 2s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-03
kubectl -n pb-03 apply -f scenarios/03-pending-insufficient-resources/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod stays Pending forever. Nothing is wrong with the image or the app.


```console
$ kubectl -n pb-03 get pods
NAME                         READY   STATUS    RESTARTS   AGE
analytics-867d4cbc45-jnz4v   0/1     Pending   0          0s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-03 describe pod -l app=analytics | sed -n '/Events:/,$p'
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  0s    default-scheduler  0/1 nodes are available: 1 Insufficient cpu, 1 Insufficient memory. no new claims to deallocate, preemption: 0/1 nodes are available: 1 Preemption is not helpful for scheduling.

$ kubectl get nodes -o custom-columns=NODE:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory
NODE                     CPU   MEMORY
playbook-control-plane   8     16386504Ki

$ kubectl describe nodes | sed -n '/Allocated resources:/,/Events:/p'
Allocated resources:
  (Total limits may be over 100 percent, i.e., overcommitted.)
  Resource           Requests     Limits
  --------           --------     ------
  cpu                1080m (13%)  100m (1%)
  memory             428Mi (2%)   550Mi (3%)
  ephemeral-storage  0 (0%)       0 (0%)
  hugepages-1Gi      0 (0%)       0 (0%)
  hugepages-2Mi      0 (0%)       0 (0%)
Events:
```

## Root cause
The pod requests 64 CPUs and 256 GiB memory. The scheduler only places a pod on a node whose *allocatable minus already-requested* resources fit the request, so no node qualifies. Requests, not real usage, decide scheduling.

## Fix
Size requests from real usage (`kubectl top pod`, or the Grafana memory panel) plus headroom. If the workload really needs it, add a node pool that is big enough.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -17,5 +17,5 @@
           command: ["sh", "-c", "while true; do sleep 3600; done"]
           resources:
-            # copied from a big production node pool; no node in this cluster has this much
-            requests: {cpu: "64", memory: 256Gi}
-            limits: {memory: 256Gi}
+            # sized from real usage (kubectl top pod) plus headroom
+            requests: {cpu: 50m, memory: 32Mi}
+            limits: {memory: 64Mi}
```

After the fix:

```console
$ kubectl -n pb-03 get pods
NAME                         READY   STATUS    RESTARTS   AGE
analytics-774f56c4d7-7q6d5   1/1     Running   0          2s
```

## Prevention
- Set requests from measured usage; review them like code.
- Use a LimitRange / ResourceQuota per namespace to block absurd values.
- Alert `PodNotReady` (pod Pending > 15m).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodNotReady`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodNotReady.md)

## Time to fix in the demo
2 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
