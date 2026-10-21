# 07. Service has no endpoints: label selector does not match the pods

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 1s; healthy 0s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-07
kubectl -n pb-07 apply -f scenarios/07-service-no-endpoints/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
Pods are Running and Ready, but calls to the Service time out or are refused.


```console
$ kubectl -n pb-07 get pods,svc
NAME                            READY   STATUS    RESTARTS   AGE
pod/frontend-74ff77867b-lnsb4   1/1     Running   0          1s
pod/frontend-74ff77867b-m4629   1/1     Running   0          1s

NAME               TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)   AGE
service/frontend   ClusterIP   10.96.74.246   <none>        80/TCP    1s

$ kubectl -n pb-07 run client --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -qO- -T 3 http://frontend/ >/dev/null && echo OK || echo "request failed"' 2>&1 | grep -v 'pod .* deleted'
All commands and output from this session will be recorded in container logs, including credentials and sensitive information passed through the command prompt.
If you don't see a command prompt, try pressing enter.
wget: can't connect to remote host (10.96.74.246): Connection refused
request failed
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n pb-07 get endpointslices -l kubernetes.io/service-name=frontend
NAME             ADDRESSTYPE   PORTS     ENDPOINTS   AGE
frontend-wd962   IPv4          <unset>   <unset>     4s

$ kubectl -n pb-07 get svc frontend -o jsonpath='{.spec.selector}{"\n"}'
{"app":"web-frontend"}

$ kubectl -n pb-07 get pods --show-labels
NAME                        READY   STATUS    RESTARTS   AGE   LABELS
frontend-74ff77867b-lnsb4   1/1     Running   0          4s    app=frontend,pod-template-hash=74ff77867b,tier=web
frontend-74ff77867b-m4629   1/1     Running   0          4s    app=frontend,pod-template-hash=74ff77867b,tier=web
```

## Root cause
The Service selects `app=web-frontend`, but the pods are labelled `app=frontend`. A Service only sends traffic to pods whose labels match its selector, so its endpoint list is empty.

## Fix
Make the selector match the pod template labels (`app: frontend`). Endpoints appear within seconds.

```diff
--- broken.yaml
+++ fixed.yaml
@@ -25,4 +25,4 @@
   name: frontend
 spec:
-  selector: {app: web-frontend}   # typo: pods are labelled app=frontend
+  selector: {app: frontend}
   ports: [{name: http, port: 80, targetPort: http}]
```

After the fix:

```console
$ kubectl -n pb-07 get endpointslices -l kubernetes.io/service-name=frontend
NAME             ADDRESSTYPE   PORTS   ENDPOINTS                   AGE
frontend-wd962   IPv4          80      10.244.0.125,10.244.0.126   4s

$ kubectl -n pb-07 run client --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -qO- -T 3 http://frontend/ | grep -o "<title>.*</title>"' 2>&1 | grep -v 'pod .* deleted'
<title>Welcome to nginx!</title>
```

## Prevention
- Generate Service selectors and pod labels from the same Helm helper (`selectorLabels`).
- First check in any "service does not answer" case: `kubectl get endpointslices`.
- Probe the service with a blackbox exporter `probe_success` alert (app-level check).

## Time to fix in the demo
0 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
