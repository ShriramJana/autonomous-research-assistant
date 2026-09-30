# Running ARA on Kubernetes (local, kind)

Local kind cluster + Helm chart for the FastAPI backend and the Next.js
frontend. Production runs on Cloud Run + Vercel; this is the place to see how
the app behaves with several backend replicas, rolling restarts and
autoscaling.

The interesting constraint is SSE. A research run holds one HTTP stream open
for minutes, and the run itself executes as a background task on whichever
backend pod received `POST /api/research`. Most of the non-obvious pieces
here exist for that reason.

## Prerequisites

```bash
brew install kind helm kubectl   # macOS; use winget/choco/apt elsewhere
docker info                      # Docker must be running
```

A filled-in repo-root `.env` (same one the app uses locally). The cluster
talks to the same Supabase project.

One-time Supabase step for Google sign-in on the cluster: Supabase dashboard →
Authentication → URL Configuration → Redirect URLs → add
`http://ara.localtest.me:8088/**`.

## Up and running

```bash
make k8s-up       # kind cluster + ingress-nginx + metrics-server
make k8s-build    # build both images, load them into kind
make k8s-deploy   # Secret from .env, helm upgrade --install, wait for rollout
```

Open http://ara.localtest.me:8088 (`localtest.me` resolves to 127.0.0.1).

```bash
kubectl get pods -o wide
kubectl logs -l app=ara-backend -f --prefix     # which pod logs what
kubectl get hpa ara-backend -w
make k8s-down                                   # delete the cluster
```

After code changes: `make k8s-build && make k8s-deploy`.

`.env` becomes the `ara-secrets` Secret as-is. Values in `.env` must be unquoted (`KEY=value`, not `KEY=\"value\"`): `kubectl --from-env-file` and the image build keep quote characters literally. If it contains
`ANTHROPIC_API_KEY`, the cluster has the owner-key free tier (production does
not). Chart `config:` values override same-named `.env` keys.

## How live streams work across pods

Every event a run emits is written to `report_events` and followed, in the
same transaction, by `NOTIFY ara_events, '<report id>'`. Each backend pod
keeps one `LISTEN ara_events` connection. When a doorbell for report X rings,
every stream on that pod watching X re-reads the rows newer than the last
one it sent. If the listener connection is down, streams re-read every 2s
anyway, so a dead listener costs latency, not events.

The notification carries only the id. The database stays the source of truth,
and a `report_complete` event, which holds the whole report, never has to fit
in NOTIFY's 8000-byte payload limit.

Look for `event doorbell: listening on ara_events` once per backend pod in
the logs.

## What each lifecycle setting does

| Setting | Default | Why |
|---|---|---|
| `backend.preStopSleepSeconds` | 10 | Pod leaves the Service endpoints before SIGTERM, so no new stream lands on a dying pod |
| `backend.terminationGracePeriodSeconds` | 120 | Upper bound on the whole shutdown before SIGKILL |
| `backend.shutdownDrainSeconds` | 100 | After uvicorn stops accepting connections, the app waits this long for in-flight research runs, then cancels the rest. Must be < grace − preStop (the chart refuses to render otherwise) |
| ingress `proxy-buffering: off` | — | nginx would otherwise batch SSE events |
| ingress `proxy-read-timeout: 3600` | — | The default 60s cuts long runs |
| HPA `scaleDownStabilizationSeconds` | 300 | Scale-down waits instead of removing pods mid-run |

## Experiments

Real runs spend API credit on whichever key the user saved (roughly $0.55
for a standard-depth run on Anthropic; use Quick depth where you can).

Find the pod running a report: `kubectl logs -l app=ara-backend --prefix | grep <report id>`.

### 1. Kill the pod running a report

Start a run, find its pod, then `kubectl delete pod <pod> --grace-period=0 --force`.

Expected: the run dies with the pod (runs are not persisted jobs), and the
viewer's stream stops receiving events, even when the stream is served by the
other pod. This documents the known limit; see Next steps.

| Trial | Stream served by same pod? | What the viewer saw | Report status after |
|---|---|---|---|
| 1 | | | |
| 2 | | | |

### 2. Rolling restart: protections off vs on

Protections off:

```bash
helm upgrade ara deploy/helm/ara \
  --set backend.terminationGracePeriodSeconds=30 \
  --set backend.preStopSleepSeconds=0 \
  --set backend.shutdownDrainSeconds=0
```

Start N runs, `kubectl rollout restart deployment/ara-backend`, count runs
that reach `report_complete`. Then `helm upgrade ara deploy/helm/ara` (defaults
back on) and repeat.

| Config | Runs started | Completed | Failed / stuck |
|---|---|---|---|
| Protections off | | | |
| Protections on | | | |

### 3. Autoscaling under concurrent runs

Start several runs at once and watch `kubectl get hpa ara-backend -w`.
Research runs are mostly network-bound, so CPU may not move much. That is a
finding in itself: CPU is a poor proxy for "people mid-run".

| Concurrent runs | Peak CPU % | Replicas reached | Time to scale | Runs failed |
|---|---|---|---|---|
| | | | | |

## Next steps

- Make runs survive pod death: a lease on the report row plus a worker that
  resumes or fails stale runs, so viewers see an error instead of silence.
- A fake-LLM mode for free, repeatable load tests.
- Scale on an active-stream metric (Prometheus + custom metrics adapter)
  instead of CPU.
- Push images to a registry and run the chart on GKE, with Terraform for the
  cluster.
- Move from ingress-nginx to the Gateway API.
