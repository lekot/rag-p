#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="rag-p-dev"

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "Deleting kind cluster '${CLUSTER_NAME}'..."
    kind delete cluster --name "${CLUSTER_NAME}"
    echo "Cluster deleted."
else
    echo "Cluster '${CLUSTER_NAME}' not found, nothing to delete."
fi
