# Plugin reference

This document enumerates all plugins available in the RAG Platform plugin registry. It is intentionally verbose so the bench corpus has enough vocabulary to exercise the retriever realistically.

## Chunkers

### recursive-character

Default. Splits text on a list of separators in order: paragraph break, line break, sentence boundary, word boundary, character. Keeps overlap to preserve cross-chunk context.

Parameters:
- `chunk_size` (int, default 512): target size in characters, not tokens.
- `chunk_overlap` (int, default 64): overlap between consecutive chunks.
- `separators` (list[str], optional): override default separator order.

Use when: documents are mostly natural language, no obvious structure.

### sentence-window

Tokenises into sentences (using spaCy multilingual model), then concatenates a sliding window of N sentences. Useful for fine-grained retrieval where the answer is in a single sentence but surrounding context helps the generator.

Parameters:
- `window_size` (int, default 3).
- `stride` (int, default 1).
- `language` (str, default "auto").

### markdown-aware

Respects markdown structure: headings split chunks, code blocks stay intact, tables are emitted as one chunk regardless of size. Designed for documentation corpora.

Parameters:
- `max_chunk_size` (int, default 1024): hard limit even for headings.
- `respect_code_blocks` (bool, default true).

### semantic

Embeds candidate sentences and merges adjacent sentences whose cosine similarity exceeds threshold. Slower than the alternatives because it requires an embedder during chunking, but produces semantically coherent chunks.

Parameters:
- `threshold` (float, default 0.7).
- `embedder` (str, default "ollama-embedder/bge-m3").
- `min_chunk_size` (int, default 128).

## Embedders

### ollama-embedder

Calls a local Ollama server via HTTP. Cheapest option once the model is pulled, no per-token billing, but requires GPU on the worker for acceptable throughput.

Parameters:
- `model` (str, default "bge-m3"): any model in `ollama list`.
- `host` (str, default `$OLLAMA_HOST`).
- `batch_size` (int, default 16).
- `timeout_sec` (int, default 60).

### litellm-embedder

Generic adapter over the LiteLLM library. Supports OpenAI, Cohere, Voyage, Mistral, Vertex AI. Pay-per-token.

Parameters:
- `model` (str, required): in LiteLLM convention, e.g. `openai/text-embedding-3-small`.
- `input_type` (str): `search_document` for corpus, `search_query` for queries (Cohere-only).
- `dimensions` (int, optional): some models support truncation.

### cohere-embedder

Direct Cohere SDK wrapper. Used when `COHERE_API_KEY` is set and `OLLAMA_HOST` is not. Slightly faster than litellm-embedder for Cohere-specific models because it avoids the LiteLLM dispatch layer.

## Retrievers

### pgvector-hybrid

Default. Combines cosine similarity over the `embedding` column with full-text search over the `tsvector` column. The two scores are min-max normalised inside a single window function and combined with configurable weights.

Parameters:
- `top_k` (int, default 5).
- `dense_weight` (float, default 0.6).
- `bm25_weight` (float, default 0.4).
- `bm25_language` (str, default "russian"): mapped to `tsvector` config.

### pgvector-dense

Cosine similarity only. Faster for small datasets where BM25 adds noise. Identical SQL to `pgvector-hybrid` minus the `tsvector` join.

### multi-query

Wraps another retriever. Generates N paraphrases of the query via an LLM, retrieves top-k for each, deduplicates by chunk id, returns the union. Improves recall at the cost of LLM latency.

Parameters:
- `inner_retriever` (str, required): e.g. `pgvector-hybrid`.
- `num_paraphrases` (int, default 3).
- `paraphrase_model` (str, default "openai/gpt-4o-mini").

## Rerankers

### cohere-rerank

Calls Cohere `rerank-multilingual-v3.0`. Takes top-N from the retriever (default N=20), returns top-K reranked.

### bge-reranker

Local cross-encoder via `bge-reranker-v2-m3`. Deployed alongside Ollama. Slower per pair than Cohere API but no per-call cost.

## Generators

### litellm-generator

Default. Routes to any LLM supported by LiteLLM. Supports streaming, function calling, structured output (JSON schema).

Parameters:
- `model` (str, required): e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-haiku`, `deepseek/deepseek-chat`.
- `temperature` (float, default 0.0): defaults to deterministic.
- `max_tokens` (int, default 1024).
- `system_prompt_template` (str, optional): jinja2 template, gets `{context}`, `{question}`.

### extractive-fallback

When all generator calls fail (network, billing, model errors), this fallback returns the highest-scoring chunk verbatim. Marked as `extractive=true` in the trace so the frontend can label the answer accordingly. Does not call any external API.

## Scorers (eval-only)

### ragas-faithfulness

Uses a judge LLM to score whether the generated answer is supported by the retrieved context. Score in [0, 1].

### ragas-answer-relevance

Reverse-generates questions from the answer and computes cosine similarity to the original question. Score in [0, 1].

### ragas-context-precision

For each retrieved chunk, asks the judge whether it was used in the answer. Returns mean precision over the top-k.

### ragas-context-recall

Compares the retrieved context against the golden answer to estimate recall. Requires a golden Q&A set in the dataset.

### retrieval-hit

Boolean: was the gold chunk among the top-k? Cheaper than RAGAS, useful for chunker grid search.

### answer-similarity

Cosine similarity between embeddings of the generated answer and the golden answer.

## Composite

### composite-score

Not a real plugin but a derived metric stored in `experiments.leaderboard_json`. Weighted average of the metrics that were computed for the combination. Default weights: faithfulness 0.4, answer_relevance 0.3, context_recall 0.3.

## Adding a new plugin

1. Create file under `apps/api/src/ragp_api/plugins/<kind>/<name>.py`.
2. Subclass the appropriate base class from `plugins.base`.
3. Decorate the class with `@register_plugin("kind", "name")`.
4. Define `params_schema: dict[str, Any]` (JSON Schema 2020-12).
5. Implement the abstract methods (`embed`, `retrieve`, `generate`, etc.).
6. Add unit tests under `apps/api/tests/plugins/`.
7. Re-deploy — registry is populated at import time.

## Known issues

- Plugin registry currently has no concept of versions. Renaming a plugin breaks every saved pipeline pointing at the old name.
- `params_schema` is duck-typed — there is no static check that the runtime params match the schema.
- Generators that require auth credentials read them from env at call-time, not from plugin params. This makes per-tenant credential management impossible without a config service.
