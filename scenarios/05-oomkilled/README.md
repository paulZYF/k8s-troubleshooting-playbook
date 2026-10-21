# 05. OOMKilled: memory limit too low

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 21s; healthy 21s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-05
kubectl -n pb-05 apply -f scenarios/05-oomkilled/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The pod restarts every few seconds; the restart count keeps going up.


```console
$ kubectl -n pb-05 get pods
NAME                             READY   STATUS    RESTARTS      AGE
report-worker-6f898dc646-xhntf   1/1     Running   2 (16s ago)   21s
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-05 describe pod -l app=report-worker | sed -n '/Containers:/,/Conditions:/p' | grep -E 'State|Reason|Exit Code|Restart Count|Limits|memory'
    State:          Running
    Last State:     Terminated
      Reason:       OOMKilled
      Exit Code:    137
    Restart Count:  2
    Limits:
      memory:  64Mi
      memory:     64Mi

$ kubectl -n pb-05 logs deploy/report-worker --previous
loading report data
stress: info: [1] dispatching hogs: 0 cpu, 0 io, 1 vm, 0 hdd

$ kubectl -n pb-05 get events --sort-by=.lastTimestamp -o custom-columns=REASON:.reason,MESSAGE:.message | tail -5
ScalingReplicaSet   Scaled up replica set report-worker-6f898dc646 from 0 to 1
BackOff             Back-off restarting failed container worker in pod report-worker-6f898dc646-xhntf_pb-05(936684e4-de27-4e8d-b3b6-6191feccaa56)
Pulled              Container image "polinux/stress:1.0.4" already present on machine
Created             Created container: worker
Started             Started container worker
```

## Root cause
The worker needs about 150 MiB but the container limit is 64 MiB. When the process goes over the limit, the kernel OOM killer kills it with SIGKILL (`Exit Code: 137` = 128 + 9). Usually the reason is `OOMKilled`; when the container dies very quickly, some containerd versions report `Reason: Error` instead, so treat exit code 137 together with a low memory limit as an OOM kill. The app log has no error because the process is killed from outside.

## Fix
Raise the memory limit above the real peak (here 256 MiB) and set the request near normal usage (192 MiB) so the scheduler reserves enough memory on the node.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -18,4 +18,4 @@
           command: ["sh", "-c", "echo 'loading report data'; sleep 2; exec stress --vm 1 --vm-bytes 150M --vm-hang 0 --vm-keep"]
           resources:
-            requests: {cpu: 10m, memory: 64Mi}
-            limits: {memory: 64Mi}
+            requests: {cpu: 10m, memory: 192Mi}
+            limits: {memory: 256Mi}
```

After the fix:

```console
$ kubectl -n pb-05 get pods
NAME                             READY   STATUS    RESTARTS   AGE
report-worker-6b9597956f-6fxww   1/1     Running   0          21s

$ kubectl -n pb-05 top pod 2>/dev/null || echo "(metrics-server not installed; see Grafana 'Workload health' for memory usage)"
(metrics-server not installed; see Grafana 'Workload health' for memory usage)
```

## Prevention
- Measure the peak (`container_memory_working_set_bytes`) before setting limits.
- For JVM / Node.js, size the heap to the container limit.
- Alert `PodOOMKilled` (fires on the first OOM kill), then `PodCrashLooping` if it keeps going.

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`PodOOMKilled`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodOOMKilled.md), [`PodCrashLooping`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/PodCrashLooping.md)

## Time to fix in the demo
21 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
