# 08. Ingress returns 502: Service targetPort does not match the container port

> Verified on a kind cluster (Kubernetes v1.34.0) on 2026-10-20: **reproduced and fixed**. Failure visible after 7s; healthy 7s after applying the fix. All output below is real, captured by `scripts/run_scenario.py`.

## Try it
```bash
kubectl create namespace pb-08
kubectl -n pb-08 apply -f scenarios/08-ingress-502-wrong-port/broken.yaml
# ...diagnose it yourself, then compare with the write-up below
```

Files: `broken.yaml`, `fixed.yaml`

## Symptom
The Ingress answers, but every request gets 502 Bad Gateway.


```console
$ kubectl -n pb-08 get pods,svc,ingress
NAME                        READY   STATUS    RESTARTS   AGE
pod/shop-67c6c7f44d-cq5h8   1/1     Running   0          7s

NAME           TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
service/shop   ClusterIP   10.96.104.164   <none>        80/TCP    7s

NAME                             CLASS   HOSTS               ADDRESS   PORTS   AGE
ingress.networking.k8s.io/shop   nginx   shop.example.test             80      7s

$ kubectl -n pb-08 run client --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -S -O /dev/null -T 5 --header "Host: shop.example.test" http://ingress-nginx-controller.ingress-nginx.svc/ 2>&1 | grep HTTP/' 2>&1 | grep -v 'pod .* deleted'
  HTTP/1.1 502 Bad Gateway
wget: server returned error: HTTP/1.1 502 Bad Gateway
```

## Diagnosis
Commands in the order I run them, with the real output:

```console
$ kubectl -n ingress-nginx logs deploy/ingress-nginx-controller --tail=50 | grep -E 'connect\(\) failed|upstream' | tail -2
2026/10/21 02:54:20 [error] 839#839: *9302 connect() failed (111: Connection refused) while connecting to upstream, client: 10.244.0.132, server: shop.example.test, request: "GET / HTTP/1.1", upstream: "http://10.244.0.129:8080/", host: "shop.example.test"
2026/10/21 02:54:20 [error] 839#839: *9302 connect() failed (111: Connection refused) while connecting to upstream, client: 10.244.0.132, server: shop.example.test, request: "GET / HTTP/1.1", upstream: "http://10.244.0.129:8080/", host: "shop.example.test"

$ kubectl -n pb-08 get svc shop -o jsonpath='port={.spec.ports[0].port} targetPort={.spec.ports[0].targetPort}{"\n"}'
port=80 targetPort=8080

$ kubectl -n pb-08 get endpointslices -l kubernetes.io/service-name=shop -o custom-columns=NAME:.metadata.name,PORTS:.ports[*].port,ADDRESSES:.endpoints[*].addresses[0]
NAME         PORTS   ADDRESSES
shop-xb6lw   8080    10.244.0.129

$ kubectl -n pb-08 get pod -l app=shop -o jsonpath='containerPort={.items[0].spec.containers[0].ports[0].containerPort}{"\n"}'
containerPort=80
```

## Root cause
Ingress → Service → Pod each have their own port. The Ingress points to Service port 80, which is correct, but the Service forwards to `targetPort: 8080` while nginx listens on 80. The controller connects to podIP:8080, gets "connection refused", and returns 502. (A 404 from the controller usually means the host/path does not match any Ingress rule, or `ingressClassName` is missing.)

## Fix
Set `targetPort` to the port the container really listens on (or to a named port like `http`).

```diff
--- broken.yaml
+++ fixed.yaml
@@ -28,5 +28,5 @@
   ports:
     - port: 80
-      targetPort: 8080   # the container listens on 80, not 8080
+      targetPort: 80
 ---
 apiVersion: networking.k8s.io/v1
```

After the fix:

```console
$ kubectl -n pb-08 run client --rm -i --restart=Never --image=busybox:1.36 -- sh -c 'wget -S -O /dev/null -T 5 --header "Host: shop.example.test" http://ingress-nginx-controller.ingress-nginx.svc/ 2>&1 | grep HTTP/' 2>&1 | grep -v 'pod .* deleted'
  HTTP/1.1 200 OK
```

## Prevention
- Use named ports (`containerPort` with `name: http`, `targetPort: http`) so the numbers live in one place.
- Read the ingress controller log: `connect() failed (111: Connection refused)` = wrong port or app down.
- Alert on ingress 5xx rate (`AppHighErrorRate` pattern on `nginx_ingress_controller_requests`).

Alert rules that catch it (from [k8s-monitoring-stack](https://github.com/paulZYF/k8s-monitoring-stack)): [`AppHighErrorRate`](https://github.com/paulZYF/k8s-monitoring-stack/blob/main/runbook/AppHighErrorRate.md)

## Time to fix in the demo
7 seconds from applying the fix to healthy (measured by the runner; diagnosis time not included).
