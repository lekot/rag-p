"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const API_BASE = "https://api.lekottt.ru";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const CURL_EXAMPLE = `curl -X POST ${API_BASE}/api/v1/rag/query \\
  -H "Authorization: Bearer rgp_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "dataset_id": "DS_UUID",
    "query": "what is hexagram 5?",
    "top_k": 5
  }'`;

const RESPONSE_EXAMPLE = `{
  "answer": "Hexagram 5, Xu (Waiting), ...",
  "chunks": [
    {
      "id": "chunk-uuid",
      "text": "...",
      "score": 0.94,
      "document_id": "doc-uuid",
      "document_name": "iching.txt"
    }
  ],
  "usage": { "prompt_tokens": 312, "completion_tokens": 87 },
  "trace": {
    "embedder": "litellm-embedder",
    "retriever": "pgvector-hybrid",
    "generator": "litellm-generator",
    "model": "deepseek/deepseek-v4-flash"
  }
}`;

const N8N_INSTALL_CMD = `cd ~/.n8n/custom
npm install n8n-nodes-rag-p`;

export default function DocsPage() {
  const [copied, setCopied] = useState(false);
  const [copiedN8n, setCopiedN8n] = useState(false);

  // Playground state
  const [apiKey, setApiKey] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const didInit = useRef(false);

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    const params = new URLSearchParams(window.location.search);
    const dsId = params.get("dataset_id");
    if (dsId) setDatasetId(dsId);
  }, []);

  async function handleRun() {
    if (!UUID_RE.test(datasetId.trim())) {
      setResult(
        JSON.stringify(
          {
            error: "dataset_id must be a UUID",
            hint: "Откройте нужный датасет и скопируйте UUID из адресной строки /datasets/<uuid>. Имя вроде TG_chat сюда не подходит.",
          },
          null,
          2
        )
      );
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/rag/query`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ dataset_id: datasetId.trim(), query, top_k: topK }),
      });
      const text = await resp.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(text) as unknown;
      } catch {
        parsed = text;
      }
      if (!resp.ok) {
        setResult(JSON.stringify({ error: resp.status, body: parsed }, null, 2));
      } else {
        setResult(JSON.stringify(parsed, null, 2));
      }
    } catch (err) {
      setResult(JSON.stringify({ error: String(err) }, null, 2));
    } finally {
      setRunning(false);
    }
  }

  function handleCopy() {
    void navigator.clipboard.writeText(CURL_EXAMPLE).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function handleCopyN8n() {
    void navigator.clipboard.writeText(N8N_INSTALL_CMD).then(() => {
      setCopiedN8n(true);
      setTimeout(() => setCopiedN8n(false), 2000);
    });
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold mb-2">Documentation</h1>
        <p className="text-muted-foreground">
          Programmatic access to your RAG pipelines — через REST API напрямую или через готовую
          ноду для n8n.
        </p>
      </div>

      <Tabs defaultValue="workflow" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="workflow">User workflow</TabsTrigger>
          <TabsTrigger value="rest">REST API</TabsTrigger>
          <TabsTrigger value="n8n">n8n integration</TabsTrigger>
        </TabsList>

        {/* === User workflow tab === */}
        <TabsContent value="workflow" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>From documents to a production pipeline</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm text-muted-foreground">
              <p>
                RAG-Platform is built around one practical loop: create a dataset, generate a
                golden Q&amp;A benchmark, run an experiment, promote the best result to a pipeline,
                then ask questions through that pipeline and inspect the answers in Runs.
              </p>
              <p>
                You need an active plan before creating datasets, generating golden Q&amp;A, running
                experiments, or executing pipeline runs. If the product shows
                <code className="mx-1 bg-muted px-1 py-0.5 rounded text-xs">402 Payment Required</code>,
                open <a href="/pricing" className="underline text-foreground hover:text-primary">Pricing</a>{" "}
                or <a href="/account/billing" className="underline text-foreground hover:text-primary">Billing</a>{" "}
                and activate a plan or quota.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Step-by-step</CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              <ol className="list-decimal list-inside space-y-3 text-muted-foreground">
                <li>
                  Open <a href="/datasets" className="underline text-foreground hover:text-primary">Datasets</a>{" "}
                  and click <strong>Upload / Create</strong>. Enter a dataset name and upload a
                  source file. Supported files include txt, md, json, csv, yaml, xml, html, pdf,
                  docx, and similar text formats up to 10 MB.
                </li>
                <li>
                  Open the dataset page and wait until the uploaded document is chunked and
                  indexed. Use <strong>Upload more</strong> when the dataset needs additional
                  documents.
                </li>
                <li>
                  In the dataset page, open <strong>Golden Q&amp;A</strong> and click
                  <strong> Generate Golden Q&amp;A</strong>. Pick a sample size from 5 to 50 chunks.
                  The app creates one benchmark question and expected answer per sampled chunk.
                </li>
                <li>
                  Open <a href="/experiments" className="underline text-foreground hover:text-primary">Experiments</a>{" "}
                  and click <strong>New Experiment</strong>. Select the dataset, choose one or more
                  plugin variants for the required stages, and click <strong>Run experiment</strong>.
                </li>
                <li>
                  Open the experiment result and compare the leaderboard. When a combination is
                  good enough, click <strong>Promote</strong>, enter a <strong>Pipeline name</strong>,
                  and confirm with <strong>Create pipeline</strong>.
                </li>
                <li>
                  Open the promoted pipeline in{" "}
                  <a href="/pipelines" className="underline text-foreground hover:text-primary">Pipelines</a>.
                  Use <strong>Run a query</strong> to ask a question through the selected production
                  configuration. You can also ask from the dataset page by selecting the pipeline in
                  the Ask block, or call the REST API with <code>pipeline_id</code>.
                </li>
                <li>
                  Open <a href="/runs" className="underline text-foreground hover:text-primary">Runs</a>{" "}
                  to inspect created runs. Each run keeps the query, status, answer, retrieved and
                  reranked chunks, token usage, duration, and RAGAS metrics when available.
                </li>
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Acceptance checklist</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              <ul className="list-disc list-inside space-y-2">
                <li>The dataset contains at least one uploaded document and non-zero chunks.</li>
                <li>Golden Q&amp;A shows generated items linked to source chunks.</li>
                <li>The experiment reaches a completed state and the leaderboard has scored rows.</li>
                <li>The best experiment combination is promoted to a named pipeline.</li>
                <li>A pipeline query creates a completed run.</li>
                <li>The run detail page shows the final answer and the supporting chunks used by retrieval.</li>
              </ul>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Troubleshooting</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              <div className="overflow-x-auto">
                <table className="w-full text-xs border rounded">
                  <thead className="bg-muted">
                    <tr>
                      <th className="text-left px-3 py-2">Symptom</th>
                      <th className="text-left px-3 py-2">What to check</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t">
                      <td className="px-3 py-2">Dataset creation, upload, golden generation, or run returns 402</td>
                      <td className="px-3 py-2">Open Billing and activate a plan or add quota.</td>
                    </tr>
                    <tr className="border-t">
                      <td className="px-3 py-2">Golden Q&amp;A button is disabled or creates no items</td>
                      <td className="px-3 py-2">Upload a document first and wait until chunking/indexing finishes.</td>
                    </tr>
                    <tr className="border-t">
                      <td className="px-3 py-2">Experiment has an empty or failed leaderboard</td>
                      <td className="px-3 py-2">Check that the dataset has golden Q&amp;A and that selected providers are available.</td>
                    </tr>
                    <tr className="border-t">
                      <td className="px-3 py-2">Pipeline run fails or does not answer</td>
                      <td className="px-3 py-2">Open the run detail page and inspect status, chunks, metrics, and error text.</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* === REST API tab === */}
        <TabsContent value="rest" className="space-y-8">
          {/* Authentication */}
          <Card>
            <CardHeader>
              <CardTitle>Authentication</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>
                All requests to the public API require an API key in the{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-xs">Authorization</code> header:
              </p>
              <pre className="bg-muted rounded p-3 text-xs font-mono overflow-x-auto">
                Authorization: Bearer rgp_YOUR_KEY
              </pre>
              <p className="text-muted-foreground">
                Generate a key in your{" "}
                <a href="/account" className="underline text-foreground hover:text-primary">
                  Account settings
                </a>
                . A key is shown only once — store it securely.
              </p>
            </CardContent>
          </Card>

          {/* Endpoint */}
          <Card>
            <CardHeader>
              <CardTitle>
                <span className="font-mono text-base bg-blue-100 text-blue-800 px-2 py-0.5 rounded mr-2">
                  POST
                </span>
                /api/v1/rag/query
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5 text-sm">
              <p className="text-muted-foreground">
                Runs a full RAG pipeline (embed → retrieve → generate) against a dataset you own.
                Optionally uses a specific published pipeline configuration.
              </p>

              {/* Request body */}
              <div>
                <h3 className="font-semibold mb-2">Request body (JSON)</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border rounded">
                    <thead className="bg-muted">
                      <tr>
                        <th className="text-left px-3 py-2">Field</th>
                        <th className="text-left px-3 py-2">Type</th>
                        <th className="text-left px-3 py-2">Required</th>
                        <th className="text-left px-3 py-2">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">dataset_id</td>
                        <td className="px-3 py-2">string</td>
                        <td className="px-3 py-2">yes</td>
                        <td className="px-3 py-2">UUID of the dataset to query</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">query</td>
                        <td className="px-3 py-2">string</td>
                        <td className="px-3 py-2">yes</td>
                        <td className="px-3 py-2">Natural language question</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">top_k</td>
                        <td className="px-3 py-2">integer</td>
                        <td className="px-3 py-2">no (default: 5)</td>
                        <td className="px-3 py-2">Number of chunks to retrieve</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">pipeline_id</td>
                        <td className="px-3 py-2">string | null</td>
                        <td className="px-3 py-2">no</td>
                        <td className="px-3 py-2">
                          UUID of a published pipeline; uses default config if omitted
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Response schema */}
              <div>
                <h3 className="font-semibold mb-2">Response (200 OK)</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border rounded">
                    <thead className="bg-muted">
                      <tr>
                        <th className="text-left px-3 py-2">Field</th>
                        <th className="text-left px-3 py-2">Type</th>
                        <th className="text-left px-3 py-2">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">answer</td>
                        <td className="px-3 py-2">string</td>
                        <td className="px-3 py-2">Generated answer</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">chunks[]</td>
                        <td className="px-3 py-2">array</td>
                        <td className="px-3 py-2">
                          Retrieved chunks — each has <code>id</code>, <code>text</code>,{" "}
                          <code>score</code>, <code>document_id</code>, <code>document_name</code>
                        </td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">usage</td>
                        <td className="px-3 py-2">object</td>
                        <td className="px-3 py-2">
                          <code>prompt_tokens</code>, <code>completion_tokens</code>
                        </td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">trace</td>
                        <td className="px-3 py-2">object</td>
                        <td className="px-3 py-2">
                          <code>embedder</code>, <code>retriever</code>, <code>generator</code>,{" "}
                          <code>model</code>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* curl example */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold">curl example</h3>
                  <Button size="sm" variant="outline" onClick={handleCopy}>
                    {copied ? "Copied!" : "Copy curl"}
                  </Button>
                </div>
                <pre className="bg-muted rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre">
                  {CURL_EXAMPLE}
                </pre>
              </div>

              {/* Try it now */}
              <div className="border rounded-lg p-4 space-y-4 bg-muted/30">
                <h3 className="font-semibold">Try it now</h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="try-apikey" className="text-xs">API key</Label>
                    <Input
                      id="try-apikey"
                      type="password"
                      placeholder="rgp_..."
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="text-xs font-mono h-8"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="try-dataset" className="text-xs">Dataset UUID</Label>
                    <Input
                      id="try-dataset"
                      type="text"
                      placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                      value={datasetId}
                      onChange={(e) => setDatasetId(e.target.value)}
                      className="text-xs font-mono h-8"
                    />
                    <p className="text-[11px] text-muted-foreground">
                      Нужен UUID из URL датасета, не его имя.
                    </p>
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="try-query" className="text-xs">Query</Label>
                  <Textarea
                    id="try-query"
                    placeholder="What is...?"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    rows={2}
                    className="text-xs resize-none"
                  />
                </div>
                <div className="flex items-center gap-4">
                  <div className="space-y-1">
                    <Label htmlFor="try-topk" className="text-xs">top_k</Label>
                    <Input
                      id="try-topk"
                      type="number"
                      min={1}
                      max={20}
                      value={topK}
                      onChange={(e) => setTopK(Number(e.target.value))}
                      className="text-xs w-20 h-8"
                    />
                  </div>
                  <Button
                    size="sm"
                    onClick={() => void handleRun()}
                    disabled={running || !apiKey || !datasetId || !query}
                    className="mt-5"
                  >
                    {running ? "Running..." : "Run"}
                  </Button>
                </div>
                {result !== null && (
                  <pre className="bg-background border rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre max-h-80 overflow-y-auto">
                    {result}
                  </pre>
                )}
                <p className="text-xs text-muted-foreground">
                  Этот вызов идентичен curl-команде сверху. Ключ хранится только в памяти браузера,
                  не отправляется на наш сервер кроме как через CORS-запрос к API.
                </p>
              </div>

              {/* Response example */}
              <div>
                <h3 className="font-semibold mb-2">Response example</h3>
                <pre className="bg-muted rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre">
                  {RESPONSE_EXAMPLE}
                </pre>
              </div>

              {/* Error codes */}
              <div>
                <h3 className="font-semibold mb-2">Error codes</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border rounded">
                    <thead className="bg-muted">
                      <tr>
                        <th className="text-left px-3 py-2">Status</th>
                        <th className="text-left px-3 py-2">Meaning</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">401</td>
                        <td className="px-3 py-2">Missing or invalid API key</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">402</td>
                        <td className="px-3 py-2">No active subscription / quota exceeded</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">404</td>
                        <td className="px-3 py-2">Dataset or pipeline not found / not yours</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">422</td>
                        <td className="px-3 py-2">Validation error or pipeline has no published version</td>
                      </tr>
                      <tr className="border-t">
                        <td className="px-3 py-2 font-mono">500</td>
                        <td className="px-3 py-2">Internal error (retriever or generator plugin unavailable)</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Rate limits */}
          <Card>
            <CardHeader>
              <CardTitle>Rate limits</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              Currently no rate limit enforced. Please be reasonable.
            </CardContent>
          </Card>
        </TabsContent>

        {/* === n8n integration tab === */}
        <TabsContent value="n8n" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>n8n community node</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p>
                Если у вас{" "}
                <a
                  href="https://n8n.io"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline text-foreground hover:text-primary"
                >
                  n8n
                </a>{" "}
                — установите ноду{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-xs">n8n-nodes-rag-p</code>,
                создайте credential с вашим API-ключом и используйте операции{" "}
                <strong>Query</strong>, <strong>Upload Document</strong>,{" "}
                <strong>Get Dataset</strong> в любом workflow. Без кода.
              </p>
              <p className="text-muted-foreground">
                README, changelog и полная документация —{" "}
                <a
                  href="https://www.npmjs.com/package/n8n-nodes-rag-p"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline text-foreground hover:text-primary"
                >
                  на странице пакета npm
                </a>
                .
              </p>
            </CardContent>
          </Card>

          {/* Step 1 — install */}
          <Card>
            <CardHeader>
              <CardTitle>Шаг 1. Установить ноду</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5 text-sm">
              <div>
                <h3 className="font-semibold mb-2">Облачная n8n или self-hosted с UI</h3>
                <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                  <li>Откройте n8n → <strong>Settings</strong> → <strong>Community Nodes</strong>.</li>
                  <li>Нажмите <strong>Install</strong>.</li>
                  <li>
                    Введите{" "}
                    <code className="bg-muted px-1 py-0.5 rounded text-xs">n8n-nodes-rag-p</code>.
                  </li>
                  <li>Примите risk warning и подтвердите.</li>
                </ol>
                <p className="mt-2 text-xs text-muted-foreground">
                  После установки в палитре нод появится <strong>RAG-Platform</strong>.
                </p>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold">Self-hosted без UI (Docker / npm)</h3>
                  <Button size="sm" variant="outline" onClick={handleCopyN8n}>
                    {copiedN8n ? "Copied!" : "Copy"}
                  </Button>
                </div>
                <pre className="bg-muted rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre">
                  {N8N_INSTALL_CMD}
                </pre>
                <p className="mt-2 text-xs text-muted-foreground">
                  Затем перезапустите процесс n8n (
                  <code className="bg-muted px-1 py-0.5 rounded">docker restart n8n</code> или
                  systemd unit).
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Step 2 — API key */}
          <Card>
            <CardHeader>
              <CardTitle>Шаг 2. Получить API-ключ</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <ol className="list-decimal list-inside space-y-1 text-muted-foreground">
                <li>
                  Откройте{" "}
                  <a
                    href="/account"
                    className="underline text-foreground hover:text-primary"
                  >
                    Account settings
                  </a>{" "}
                  → секция <strong>API keys</strong>.
                </li>
                <li>
                  Нажмите <strong>Create key</strong>, выдайте scopes для read и write (нужно
                  и для Query, и для Upload Document).
                </li>
                <li>
                  Скопируйте ключ вида{" "}
                  <code className="bg-muted px-1 py-0.5 rounded text-xs">rgp_...</code> — он
                  показывается один раз.
                </li>
              </ol>
            </CardContent>
          </Card>

          {/* Step 3 — credential */}
          <Card>
            <CardHeader>
              <CardTitle>Шаг 3. Создать credential в n8n</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                В n8n: <strong>Credentials</strong> → <strong>New</strong> →{" "}
                <strong>RAG-Platform API</strong>. Заполните три поля:
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border rounded">
                  <thead className="bg-muted">
                    <tr>
                      <th className="text-left px-3 py-2">Поле</th>
                      <th className="text-left px-3 py-2">Значение</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t">
                      <td className="px-3 py-2 font-mono">API Key</td>
                      <td className="px-3 py-2">
                        ваш ключ из шага 2 (
                        <code className="bg-muted px-1 py-0.5 rounded">rgp_...</code>)
                      </td>
                    </tr>
                    <tr className="border-t">
                      <td className="px-3 py-2 font-mono">Base URL</td>
                      <td className="px-3 py-2">
                        <code className="bg-muted px-1 py-0.5 rounded">{API_BASE}</code> (по
                        умолчанию)
                      </td>
                    </tr>
                    <tr className="border-t">
                      <td className="px-3 py-2 font-mono">Verify SSL</td>
                      <td className="px-3 py-2">
                        включено. Выключайте только для self-host с self-signed сертификатом
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                Credential проверяется автоматически вызовом{" "}
                <code className="bg-muted px-1 py-0.5 rounded">GET /api/v1/auth/me</code>. Если
                кнопка <strong>Test</strong> зелёная — всё ок.
              </p>
            </CardContent>
          </Card>

          {/* Step 4 — operations */}
          <Card>
            <CardHeader>
              <CardTitle>Шаг 4. Использовать в workflow</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                Нода <strong>RAG-Platform</strong> работает с ресурсом <strong>Dataset</strong>{" "}
                и поддерживает три операции:
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border rounded">
                  <thead className="bg-muted">
                    <tr>
                      <th className="text-left px-3 py-2">Operation</th>
                      <th className="text-left px-3 py-2">Параметры</th>
                      <th className="text-left px-3 py-2">Returns</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2 font-mono">Query</td>
                      <td className="px-3 py-2">
                        <code>Dataset ID</code>, <code>Query</code>, <code>Top K</code> (1..50)
                      </td>
                      <td className="px-3 py-2">
                        <code>{`{ answer, citations, usage }`}</code>
                      </td>
                    </tr>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2 font-mono">Upload Document</td>
                      <td className="px-3 py-2">
                        <code>Dataset ID</code>, <code>Input Type</code> (
                        <code>text</code>/<code>binary</code>), <code>Text Content</code> или{" "}
                        <code>Binary Property Name</code>, опц.&nbsp;<code>Filename</code>
                      </td>
                      <td className="px-3 py-2">
                        <code>{`{ document_id, chunks_count, status }`}</code>
                      </td>
                    </tr>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2 font-mono">Get Dataset</td>
                      <td className="px-3 py-2">
                        <code>Dataset ID</code>
                      </td>
                      <td className="px-3 py-2">
                        <code>{`{ id, name, documents_count, indexed_status }`}</code>
                      </td>
                    </tr>
                    <tr className="border-t align-top">
                      <td className="px-3 py-2 font-mono">
                        Get Usage Quota
                        <span className="ml-1 text-[10px] text-green-600 font-medium">NEW</span>
                      </td>
                      <td className="px-3 py-2">
                        <em>нет параметров</em>
                      </td>
                      <td className="px-3 py-2">
                        <code>{`{ remaining_queries, total_quota, plan_name, has_active_subscription }`}</code>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                <code>Dataset ID</code> — это UUID из URL вашего датасета (
                <code className="bg-muted px-1 py-0.5 rounded">/datasets/&lt;uuid&gt;</code>), не
                его имя.
              </p>
            </CardContent>
          </Card>

          {/* Example workflow */}
          <Card>
            <CardHeader>
              <CardTitle>Готовый пример: Telegram Q&amp;A bot</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                Бот, который отвечает на вопросы из вашей базы знаний прямо в Telegram. Три ноды,
                ноль кода:
              </p>
              <ol className="list-decimal list-inside space-y-2">
                <li>
                  <strong>Telegram Trigger</strong> — событие{" "}
                  <code className="bg-muted px-1 py-0.5 rounded">message</code>. Подключите бота
                  через Telegram credential.
                </li>
                <li>
                  <strong>RAG-Platform</strong> — operation <strong>Query</strong>:
                  <ul className="list-disc list-inside mt-1 ml-4 space-y-1 text-muted-foreground">
                    <li>
                      <code>Dataset ID</code> — UUID вашего датасета.
                    </li>
                    <li>
                      <code>Query</code> —{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">
                        {"{{ $json.message.text }}"}
                      </code>
                      .
                    </li>
                    <li>
                      <code>Top K</code> — например{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">5</code>.
                    </li>
                  </ul>
                </li>
                <li>
                  <strong>Telegram</strong> — operation{" "}
                  <strong>Send a text message</strong>:
                  <ul className="list-disc list-inside mt-1 ml-4 space-y-1 text-muted-foreground">
                    <li>
                      <code>Chat ID</code> —{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">
                        {"{{ $('Telegram Trigger').item.json.message.chat.id }}"}
                      </code>
                      .
                    </li>
                    <li>
                      <code>Text</code> —{" "}
                      <code className="bg-muted px-1 py-0.5 rounded">
                        {"{{ $json.answer }}"}
                      </code>
                      .
                    </li>
                  </ul>
                </li>
              </ol>
              <p className="text-xs text-muted-foreground">
                Для ингеста (пайплайн «новый файл в Drive → загрузка в датасет») используйте
                ноду <strong>Google Drive Trigger</strong> →{" "}
                <strong>RAG-Platform: Upload Document</strong> с{" "}
                <code className="bg-muted px-1 py-0.5 rounded">Input Type = binary</code>, затем
                опционально <strong>Wait</strong> + <strong>Get Dataset</strong> до{" "}
                <code className="bg-muted px-1 py-0.5 rounded">indexed_status == &quot;ready&quot;</code>.
              </p>
            </CardContent>
          </Card>

          {/* Limits */}
          <Card>
            <CardHeader>
              <CardTitle>Лимиты и ошибки</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>
                Нода ходит в тот же публичный API, что и REST-таб. Если у организации нет
                активной подписки или превышена квота, API возвращает{" "}
                <code className="bg-muted px-1 py-0.5 rounded">402 Payment Required</code> —
                нода покажет это как failure execution. Откройте{" "}
                <a
                  href="/account/billing"
                  className="underline text-foreground hover:text-primary"
                >
                  Billing
                </a>{" "}
                и активируйте план или докиньте баланс на overage wallet.
              </p>
              <p>
                Невалидный ключ или отозванный — <code className="bg-muted px-1 py-0.5 rounded">401</code>.
                Чужой / удалённый датасет — <code className="bg-muted px-1 py-0.5 rounded">404</code>.
              </p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
