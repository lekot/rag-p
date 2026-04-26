#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="rag-p-dev"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── 1. Ensure prerequisites ──────────────────────────────────────────────────

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: $1 not found. Install it first:"
        echo "  $2"
        exit 1
    fi
}

check_cmd docker   "https://docs.docker.com/get-docker/"
check_cmd kubectl  "https://kubernetes.io/docs/tasks/tools/"
check_cmd helm     "https://helm.sh/docs/intro/install/"

if ! command -v kind &>/dev/null; then
    echo "kind not found. Installing..."
    OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
    ARCH="$(uname -m)"
    [ "$ARCH" = "x86_64" ] && ARCH="amd64"
    [ "$ARCH" = "aarch64" ] && ARCH="arm64"
    KIND_URL="https://kind.sigs.k8s.io/dl/v0.23.0/kind-${OS}-${ARCH}"
    curl -Lo /usr/local/bin/kind "$KIND_URL"
    chmod +x /usr/local/bin/kind
    echo "kind installed."
fi

# ── 2. Create cluster if not exists ─────────────────────────────────────────

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "Cluster '${CLUSTER_NAME}' already exists, skipping creation."
else
    echo "Creating kind cluster '${CLUSTER_NAME}'..."
    kind create cluster --name "${CLUSTER_NAME}" --config "${SCRIPT_DIR}/kind-config.yaml"
    echo "Cluster created."
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"

# ── 3. Install CloudNativePG operator ────────────────────────────────────────

echo "Installing CloudNativePG operator..."
kubectl apply --server-side -f \
    https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.23/releases/cnpg-1.23.0.yaml

echo "Waiting for CNPG operator to be ready..."
kubectl rollout status deployment/cnpg-controller-manager -n cnpg-system --timeout=120s

# ── 4. Install ingress-nginx ─────────────────────────────────────────────────

echo "Installing ingress-nginx for kind..."
kubectl apply -f \
    https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.1/deploy/static/provider/kind/deploy.yaml

echo "Waiting for ingress-nginx to be ready..."
kubectl wait --namespace ingress-nginx \
    --for=condition=ready pod \
    --selector=app.kubernetes.io/component=controller \
    --timeout=120s

# ── 5. Add Helm repos and update deps ────────────────────────────────────────

echo "Adding Bitnami Helm repo..."
helm repo add bitnami https://charts.bitnami.com/bitnami || true
helm repo update

echo "Updating chart dependencies..."
helm dep update "${ROOT_DIR}/charts/rag-p"

# ── 6. Done ───────────────────────────────────────────────────────────────────

echo ""
echo "Bootstrap complete."
echo ""
echo "To start the dev stack:"
echo "  cd ${ROOT_DIR} && tilt up"
echo ""
echo "Useful commands:"
echo "  kubectl get pods -n rag-p"
echo "  kubectl logs -n rag-p deploy/rag-p-rag-p-api"
echo "  ./infra/scripts/teardown.sh   # delete the cluster"
