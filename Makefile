.PHONY: install install-frontend dev dev-backend dev-frontend test lint typecheck fmt k8s-up k8s-build k8s-deploy k8s-lint k8s-down

install:
	cd backend && uv sync --all-extras

install-frontend:
	cd frontend && npm install

dev:
	docker compose up --build

dev-backend:
	cd backend && uv run uvicorn ara.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy src
	cd frontend && npm run lint

fmt:
	cd backend && uv run ruff format .

# ---- Local Kubernetes (kind + Helm) — see deploy/README.md ------------------
KIND_CLUSTER := ara
INGRESS_NGINX_MANIFEST := https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
METRICS_SERVER_MANIFEST := https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# Read single keys from .env without sourcing it (DB URLs contain shell-special chars).
env_get = $$(grep -E '^$(1)=' .env | cut -d= -f2-)

k8s-up:
	kind create cluster --name $(KIND_CLUSTER) --config deploy/kind/cluster.yaml
	kubectl apply -f $(INGRESS_NGINX_MANIFEST)
	kubectl apply -f $(METRICS_SERVER_MANIFEST)
	kubectl patch -n kube-system deployment metrics-server --type=json \
	  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl wait -n ingress-nginx --for=condition=ready pod \
	  --selector=app.kubernetes.io/component=controller --timeout=180s

k8s-build:
	docker build -t ara-backend:dev ./backend
	docker build -t ara-frontend:dev \
	  --build-arg NEXT_PUBLIC_SUPABASE_URL="$(call env_get,NEXT_PUBLIC_SUPABASE_URL)" \
	  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY="$(call env_get,NEXT_PUBLIC_SUPABASE_ANON_KEY)" \
	  ./frontend
	kind load docker-image ara-backend:dev ara-frontend:dev --name $(KIND_CLUSTER)

k8s-deploy:
	kubectl create secret generic ara-secrets --from-env-file=.env \
	  --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install ara deploy/helm/ara
	kubectl rollout restart deployment/ara-backend deployment/ara-frontend
	kubectl rollout status deployment/ara-backend --timeout=180s
	kubectl rollout status deployment/ara-frontend --timeout=180s

k8s-lint:
	helm lint deploy/helm/ara
	helm template ara deploy/helm/ara > /dev/null
	helm template ara deploy/helm/ara \
	  --set backend.terminationGracePeriodSeconds=30 \
	  --set backend.preStopSleepSeconds=0 \
	  --set backend.gracefulShutdownSeconds=0 \
	  --set backend.shutdownDrainSeconds=0 > /dev/null
	helm template ara deploy/helm/ara --set backend.shutdownDrainSeconds=115 2>&1 | grep -q "shutdown budget exceeded"

k8s-down:
	kind delete cluster --name $(KIND_CLUSTER)
