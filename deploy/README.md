# Running ARA on Kubernetes

Local cluster (kind) + Helm chart for the FastAPI backend and Next.js frontend.

The interesting constraint here is SSE. A research run holds one HTTP connection
open for minutes, so anything that moves or restarts a pod mid-run kills a user's
report. Most of the non-obvious settings in this chart exist for that reason.

## Prerequisites

```bash
brew install kind kubectl helm        # macOS; use choco/winget/apt elsewhere
docker info                           # Docker must be running
```

## 1. Create the cluster

```bash
kind create cluster --name ara --config deploy/kind/cluster.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod --selector=app.kubernetes.io/component=controller \
  --timeout=180s
```

## 2. Build images and load them into the cluster

kind nodes can't pull from your local Docker daemon, so images are loaded in.

```bash
docker build -t ara-backend:dev ./backend
docker build -t ara-frontend:dev ./frontend      # add frontend/Dockerfile first
kind load docker-image ara-backend:dev ara-frontend:dev --name ara
```

The frontend Dockerfile needs `output: "standalone"` in `next.config.ts`:

```ts
const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() { /* unchanged */ },
};
```

## 3. Install the chart

```bash
helm install ara deploy/helm/ara \
  --set secrets.ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --set secrets.ARA_ENCRYPTION_KEY="$ARA_ENCRYPTION_KEY" \
  --set secrets.SUPABASE_URL="$SUPABASE_URL" \
  --set secrets.SUPABASE_DB_URL="$SUPABASE_DB_URL"

kubectl get pods -w
```

Open http://ara.localtest.me:8080 (localtest.me resolves to 127.0.0.1).

## 4. Watch it behave

```bash
kubectl logs -l app=ara-backend -f
kubectl describe hpa ara-backend
kubectl rollout restart deployment/ara-backend      # start a run first, watch what happens
```

## What each SSE-specific setting does

| Setting | Why |
|---|---|
| `terminationGracePeriodSeconds: 120` | A run in flight gets up to 2 minutes to finish before SIGKILL |
| `preStop: sleep 10` | Pod leaves the Service endpoints before the app starts shutting down, so no new stream lands on a dying pod |
| `proxy-buffering: off` | nginx would otherwise hold SSE events and deliver them in a batch |
| `proxy-read-timeout: 3600` | The default 60s would cut a long run |
| HPA `stabilizationWindowSeconds: 300` | Scale-down waits, instead of killing pods serving active runs |

## Experiments worth running (this is the resume material)

1. **Kill a pod mid-run.** Start a research run, then `kubectl delete pod` on the
   one serving it. Record what the client sees, then add the settings above one at
   a time and record the difference.
2. **Load test the autoscaler.** Drive concurrent runs and watch HPA add pods.
   Record time-to-scale and whether any run failed during scale events.
3. **Compare against the baseline.** Deploy with `terminationGracePeriodSeconds: 30`
   and no preStop hook, measure failed runs during a rolling restart, then turn the
   protections on and measure again. That before/after is the number worth quoting.

## Next steps once this works

- Replace the `sleep 10` preStop with a real drain endpoint that reports when the
  last active stream has closed.
- Add Prometheus and Grafana; export active-stream count and scale on that instead
  of CPU, since CPU is a poor proxy for "how many people are mid-run".
- Move from kind to EKS or GKE, with Terraform for the cluster.
