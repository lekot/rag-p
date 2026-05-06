# Product logic audit: RAG pipeline, service, paywall

Date: 2026-05-06

Scope: tenant isolation, API/session authorization, dataset/pipeline/experiment
coherence, usage accounting, paywall behavior, frontend product journeys, and
integration tooling.

## Findings

| ID | Area | Finding | Status | Resolution |
| --- | --- | --- | --- | --- |
| AUTH-001 | Org membership | Removed invited users kept tenant access through legacy `Membership` rows. | Fixed | Removing an org member now also removes the legacy membership row, and auth resolution no longer trusts stale legacy membership when `OrgMember` rows exist for the org. |
| AUTH-002 | API keys | Ordinary org members could manage API keys. | Fixed | Key list/create/delete now require owner/admin role. Removed members cannot use stale session org membership to manage keys. |
| EXP-001 | Experiments | Experiment creation accepted dataset IDs from another org. | Fixed | `POST /experiments` validates dataset ownership before persisting or enqueueing. |
| EXP-002 | Experiment worker | Golden Q&A loading in the worker was dataset-ID scoped only. | Fixed | Golden item loading now joins through org-owned datasets. |
| EXP-003 | Experiment grid | Frontend required embedders for coherent promoted pipelines, but direct API calls could omit them. | Fixed | Backend now requires chunker, embedder, retriever, and generator slots in experiment grids. |
| BILL-001 | Golden Q&A paywall | Golden generation could call DeepSeek before active-plan/quota checks. | Fixed | Golden routes return 402 before LLM calls when no plan/quota is available; service reserves one Q before each DeepSeek call and records usage with reserved quota. |
| BILL-002 | Inline pipeline runs | Successful inline runs consumed quota but did not write usage events. Failed runs could leak reserved quota. | Fixed | Inline runs now record usage without double-consuming reserved quota and release the reservation for failed non-billable runs. |
| PIPE-001 | Pipeline dataset binding | Pipelines accepted foreign/missing dataset IDs, and inline runs ignored pipeline dataset binding. | Fixed | Pipeline create/update validate dataset ownership. Runs use an effective dataset ID, reject conflicts, and pass the effective ID to retrievers and persisted run records. |
| INGEST-001 | Document upload | Upload returned `201 pending` even when enqueueing chunking failed. | Fixed | Upload now returns `503 document_enqueue_failed`, cleans the DB document, releases storage quota, and best-effort deletes raw object storage when enqueue fails. |
| PAY-001 | Frontend paywall UX | Costly dataset/upload/search/ask/experiment actions surfaced raw 402/API errors. | Fixed | Shared frontend paywall helper maps 402/no-plan errors to pricing CTA; no-plan upload is blocked before dataset creation. |
| UX-001 | Auth cache | Account logout/delete used soft navigation and could leave stale auth cache in the client. | Fixed | Account logout/delete now hard-navigate to `/login`. |
| UX-002 | Pipeline editor | Edit-mode changes could be lost until internal submit, and detail page set edit state during render. | Fixed | `PipelineEditor` emits edit-mode changes immediately; pipeline detail initializes edit state in an effect. |
| UX-003 | Dataset pipeline journey | Dataset pages did not create dataset-bound pipelines. | Fixed | Dataset detail links to `/pipelines/new?dataset_id=...`; new pipeline page passes `dataset_id` to creation. |
| TOOL-001 | Plugin registry | Broken external entry points from stale local dist-info could crash plugin discovery. | Fixed | Registry now logs and skips broken external entry points while preserving errors from current-project entry points. Built-ins re-register after test registry resets. |
| TOOL-002 | n8n integration | `n8n-workflow: "*"` resolved to vulnerable dependencies. Lint also failed on stale community-node rules. | Fixed | `n8n-workflow` is pinned to `2.20.0`, peer range is `>=2.20.0 <3`, lockfile resolves `0` high vulnerabilities, and lint/build/pack pass. |

## Deferred

| ID | Area | Reason |
| --- | --- | --- |
| A11Y-001 | Dialog descriptions | Existing Radix dialogs still warn in tests about missing `DialogDescription`/`aria-describedby`. Behavior is covered and passing; this is a small accessibility polish item. |

## Verification

Local quality gate:

- Backend: `ruff format --check apps/api/src apps/api/tests`, `ruff check apps/api/src apps/api/tests`, `mypy apps/api/src`, `pytest apps/api/tests -q`.
- Web: `pnpm --dir apps/web lint`, `pnpm --dir apps/web typecheck`, `pnpm --dir apps/web test`.
- n8n: `npm audit --audit-level=high`, `npm run lint`, `npm run build`, `npm pack --dry-run`.
