#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="rag-p"
RELEASE_NAME="rag-p"
POSTGRES_POD="${RELEASE_NAME}-postgres-1"

echo "Waiting for postgres pod to be ready..."
kubectl wait pod "${POSTGRES_POD}" \
    -n "${NAMESPACE}" \
    --for=condition=ready \
    --timeout=120s

echo "Seeding dev data..."
kubectl exec -n "${NAMESPACE}" "${POSTGRES_POD}" -- psql -U ragp -d ragp -c "
-- Stub: insert dev organization and user
INSERT INTO organizations (id, name, created_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'Dev Org', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO users (id, email, organization_id, created_at)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    'dev@rag-p.local',
    '00000000-0000-0000-0000-000000000001',
    NOW()
)
ON CONFLICT DO NOTHING;
" || echo "NOTE: seed SQL may fail if schema is not yet migrated. Run migrations first."

echo "Seed complete (or skipped if tables do not exist yet)."
