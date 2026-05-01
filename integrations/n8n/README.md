# n8n-nodes-rag-p

This is an [n8n](https://n8n.io) community node for [RAG-Platform (rag-p)](https://lekottt.ru) — a managed Retrieval-Augmented Generation service.

It lets you query your datasets, upload documents, and check dataset status from any n8n workflow.

[Installation](#installation) · [Operations](#operations) · [Credentials](#credentials) · [Example workflow](#example-workflow) · [Resources](#resources)

## Installation

Follow the [installation guide](https://docs.n8n.io/integrations/community-nodes/installation/) in the n8n community nodes documentation.

In short:

1. Open your n8n instance.
2. Go to **Settings → Community Nodes**.
3. Select **Install** and enter `n8n-nodes-rag-p`.
4. Agree to the risks of using community nodes and confirm.

After installation the **RAG-Platform** node will appear in the nodes panel.

### Manual install (self-hosted)

```bash
cd ~/.n8n/custom
npm install n8n-nodes-rag-p
```

Restart n8n.

## Credentials

Create a credential of type **RAG-Platform API**.

| Field      | Description                                                            |
| ---------- | ---------------------------------------------------------------------- |
| API Key    | Personal API key from `https://lekottt.ru/dashboard/api-keys`          |
| Base URL   | API base URL. Default `https://api.lekottt.ru`. Override for self-host |
| Verify SSL | Toggle off only for development with self-signed certificates          |

The credential is verified automatically against `GET /api/v1/auth/me`.

## Operations

The node currently supports three operations on the **Dataset** resource.

### Query

POST `/api/v1/rag/query` — run a RAG query against a dataset.

| Parameter   | Type   | Description                          |
| ----------- | ------ | ------------------------------------ |
| Dataset ID  | string | Target dataset id                    |
| Query       | string | Natural-language question            |
| Top K       | number | Number of chunks to retrieve (1..50) |

Returns: `{ answer, citations, usage }`.

### Upload Document

POST `/api/v1/datasets/{dataset_id}/documents` — upload a document into a dataset.

| Parameter            | Type             | Description                                      |
| -------------------- | ---------------- | ------------------------------------------------ |
| Dataset ID           | string           | Target dataset id                                |
| Input Type           | `text`/`binary`  | Whether to upload raw text or a binary file      |
| Text Content         | string           | (when `text`) Plain-text body                    |
| Binary Property Name | string           | (when `binary`) Property name on the input item  |
| Filename             | string, optional | Display name in the dataset                      |

Returns: `{ document_id, chunks_count, status }`.

### Get Dataset

GET `/api/v1/datasets/{dataset_id}` — read dataset metadata, useful for polling indexing status.

Returns: `{ id, name, documents_count, indexed_status }`.

## Example workflow

A simple Q&A bot:

1. **Trigger**: Telegram message received.
2. **RAG-Platform** → operation **Query**, with `query` mapped from the Telegram message text.
3. **Telegram** → send `{{ $json.answer }}` back to the chat.

For ingestion:

1. **Trigger**: Google Drive new file in folder.
2. **RAG-Platform** → operation **Upload Document**, with binary input from the previous node.
3. **Wait** + **RAG-Platform** → operation **Get Dataset**, until `indexed_status == "ready"`.

## Resources

- [n8n community nodes documentation](https://docs.n8n.io/integrations/community-nodes/)
- [rag-p API reference](https://lekottt.ru/docs)
- [Issues](https://github.com/Lekot/rag-p/issues)

## Publishing

Releases are automated via the [`n8n-publish.yml`](../../.github/workflows/n8n-publish.yml)
GitHub Actions workflow. It runs `npm ci && npm run build && npm publish --access public`
from `integrations/n8n/` against the public npm registry.

### One-time setup

Add an npm automation token (with publish rights on `n8n-nodes-rag-p`) as the
repository secret `NPM_TOKEN`:

```bash
gh secret set NPM_TOKEN --body "<npm-automation-token>"
```

### Releasing a new version

1. Bump `version` in [`package.json`](./package.json) and merge the change to
   `main`.
2. Trigger the workflow either manually or via a tag:

   **Manual run:**

   ```bash
   gh workflow run n8n-publish.yml
   ```

   **Tag-driven release** (pushes matching `n8n-v*` trigger automatically):

   ```bash
   git tag n8n-v0.1.1
   git push origin n8n-v0.1.1
   ```

The workflow itself does not bump the version — it publishes whatever is in
`integrations/n8n/package.json` on the checked-out ref.

## License

[MIT](LICENSE.md)
