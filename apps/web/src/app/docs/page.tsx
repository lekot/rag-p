"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const API_BASE = "https://api.lekottt.ru";

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
    "embedder": "cohere-embedder",
    "retriever": "pgvector-hybrid",
    "generator": "litellm-generator",
    "model": "deepseek/deepseek-v4-flash"
  }
}`;

export default function DocsPage() {
  const [copied, setCopied] = useState(false);

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
    setRunning(true);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/rag/query`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ dataset_id: datasetId, query, top_k: topK }),
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

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold mb-2">API Reference</h1>
        <p className="text-muted-foreground">
          Programmatic access to your RAG pipelines via Bearer token.
        </p>
      </div>

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
                <Label htmlFor="try-dataset" className="text-xs">Dataset ID</Label>
                <Input
                  id="try-dataset"
                  type="text"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={datasetId}
                  onChange={(e) => setDatasetId(e.target.value)}
                  className="text-xs font-mono h-8"
                />
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
    </div>
  );
}
