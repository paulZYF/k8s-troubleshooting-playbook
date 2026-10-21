# 06. Readiness probe fails: pod is Running but gets no traffic

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 13s; healthy 2s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-06
kubectl -n pb-06 apply -f scenarios/06-readiness-probe-fails/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
Pods are Running with 0 restarts, but READY is 0/1 and the Service sends no traffic to them.


```console
$ kubectl -n pb-06 get pods
NAME                          READY   STATUS    RESTARTS   AGE
storefront-6db9b66896-24d88   0/1     Running   0          13s
storefront-6db9b66896-bb5gw   0/1     Running   0          13s

$ kubectl -n pb-06 get endpointslices -l kubernetes.io/service-name=storefront -o custom-columns='NAME:.metadata.name,ADDRESSES:.endpoints[*].addresses[0],READY:.endpoints[*].conditions.ready'
NAME               ADDRESSES                   READY
storefront-6ksnv   10.244.0.119,10.244.0.120   false,false
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-06 describe pod -l app=storefront | grep -E 'Readiness|Unhealthy' | sort -u | cut -c1-160
    Readiness:    http-get http://:http/healthz delay=0s timeout=1s period=5s successThreshold=1 failureThreshold=2

$ kubectl -n pb-06 logs deploy/storefront --tail=3
10.244.0.1 - - [21/Oct/2026:02:53:52 +0000] "GET /healthz HTTP/1.1" 404 153 "-" "kube-probe/1.34" "-"
2026/10/21 02:53:57 [error] 37#37: *4 open() "/usr/share/nginx/html/healthz" failed (2: No such file or directory), client: 10.244.0.1, server: localhost, request: "GET /healthz HTTP/1.1", host: "10.244.0.119:80"
10.244.0.1 - - [21/Oct/2026:02:53:57 +0000] "GET /healthz HTTP/1.1" 404 153 "-" "kube-probe/1.34" "-"
Found 2 pods, using pod/storefront-6db9b66896-24d88

$ kubectl -n pb-06 run probe-test --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -qO- -T 3 http://storefront/ >/dev/null && echo OK || echo "request failed: no ready endpoints"' 2>&1 | grep -v 'pod .* deleted'
All commands and output from this session will be recorded in container logs, including credentials and sensitive information passed through the command prompt.
If you don't see a command prompt, try pressing enter.
wget: can't connect to remote host (10.96.220.149): Connection refused
request failed: no ready endpoints
```

## Root cause
The readiness probe calls `/healthz`, which nginx does not serve (404). A failing readiness probe does not restart the pod; it only removes it from the Service endpoints. So the pod looks healthy in `get pods` (Running, 0 restarts) but receives no traffic.

## Fix
Point the probe at a path the app really serves (`/` here, or add a real health endpoint).

```diff
--- broken.yaml
+++ fixed.yaml
@@ -17,5 +17,5 @@
           ports: [{name: http, containerPort: 80}]
           readinessProbe:
-            httpGet: {path: /healthz, port: http}   # nginx has no /healthz -> 404
+            httpGet: {path: /, port: http}   # a path the app really serves
             periodSeconds: 5
             failureThreshold: 2
```

After the fix:

```console
$ kubectl -n pb-06 get pods
NAME                          READY   STATUS        RESTARTS   AGE
storefront-66549fd686-d6vk7   1/1     Running       0          1s
storefront-66549fd686-kmntr   1/1     Running       0          2s
storefront-6db9b66896-24d88   0/1     Terminating   0          19s

$ kubectl -n pb-06 get endpointslices -l kubernetes.io/service-name=storefront -o custom-columns='NAME:.metadata.name,ADDRESSES:.endpoints[*].addresses[0],READY:.endpoints[*].conditions.ready'
NAME               ADDRESSES                                READY
storefront-6ksnv   10.244.0.119,10.244.0.122,10.244.0.123   false,true,true

$ kubectl -n pb-06 run probe-test --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -qO- -T 3 http://storefront/ | grep -o "<title>.*</title>"' 2>&1 | grep -v 'pod .* deleted'
<title>Welcome to nginx!</title>
```

## Prevention
- Test the probe path with `kubectl exec ... wget/curl` before shipping.
- Readiness = "can serve traffic now", liveness = "is stuck, restart me"; don't share one strict endpoint.
- Alert `DeploymentReplicasMismatch` (available < desired for 15m).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`DeploymentReplicasMismatch`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/DeploymentReplicasMismatch.md)

## Time to fix in the demo
2 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
