"use client";

import { useCallback, useState } from "react";
import { useUser } from "@/lib/auth";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface AuditEvent {
  id: string;
  user_id: string | null;
  user_email: string | null;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

const EVENT_TYPES = [
  "user.signup",
  "user.login",
  "user.logout",
  "key.create",
  "key.revoke",
  "dataset.create",
  "dataset.upload",
  "dataset.delete",
  "pipeline.promote",
  "invite.create",
  "invite.accept",
  "member.remove",
  "rag.query",
];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function AuditPage() {
  const user = useUser();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterEventType, setFilterEventType] = useState<string>("all");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  const LIMIT = 100;

  const fetchEvents = useCallback(
    async (reset = false) => {
      if (!user || user === undefined) return;
      const orgId = user.organization.id;
      setLoading(true);
      setError(null);

      const currentOffset = reset ? 0 : offset;
      const params = new URLSearchParams({
        limit: String(LIMIT),
        offset: String(currentOffset),
      });
      if (filterEventType && filterEventType !== "all") {
        params.set("event_type", filterEventType);
      }

      try {
        const resp = await fetch(`/api/orgs/${orgId}/audit?${params.toString()}`);
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error((body as { detail?: string }).detail ?? `HTTP ${resp.status}`);
        }
        const data: AuditEvent[] = await resp.json();
        if (reset) {
          setEvents(data);
          setOffset(data.length);
        } else {
          setEvents((prev) => [...prev, ...data]);
          setOffset((prev) => prev + data.length);
        }
        setHasMore(data.length === LIMIT);
        setLoaded(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        setLoading(false);
      }
    },
    [user, filterEventType, offset]
  );

  if (user === null) {
    return (
      <div className="max-w-4xl mx-auto mt-12 text-center text-muted-foreground">
        Требуется авторизация
      </div>
    );
  }

  if (user === undefined) {
    return (
      <div className="max-w-4xl mx-auto mt-12 text-center text-muted-foreground">
        Загрузка…
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Audit Log</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Журнал событий</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Filters */}
          <div className="flex gap-3 items-center">
            <Select
              value={filterEventType}
              onValueChange={(v) => {
                setFilterEventType(v);
                setOffset(0);
                setLoaded(false);
                setEvents([]);
              }}
            >
              <SelectTrigger className="w-[200px]">
                <SelectValue placeholder="Тип события" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все события</SelectItem>
                {EVENT_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              onClick={() => void fetchEvents(true)}
              disabled={loading}
            >
              {loading ? "Загрузка…" : loaded ? "Обновить" : "Загрузить"}
            </Button>
          </div>

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          {loaded && events.length === 0 && (
            <p className="text-sm text-muted-foreground">Событий не найдено.</p>
          )}

          {events.length > 0 && (
            <>
              <div className="overflow-auto rounded border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-40">Время</TableHead>
                      <TableHead>Событие</TableHead>
                      <TableHead>Пользователь</TableHead>
                      <TableHead>Ресурс</TableHead>
                      <TableHead>IP</TableHead>
                      <TableHead>Метаданные</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {events.map((e) => (
                      <TableRow key={e.id}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {formatDate(e.created_at)}
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
                            {e.event_type}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs">
                          {e.user_email ?? e.user_id ?? "system"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {e.resource_type}
                          {e.resource_id && (
                            <span className="ml-1 font-mono">
                              {e.resource_id.slice(0, 8)}…
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {e.ip_address ?? "—"}
                        </TableCell>
                        <TableCell className="text-xs font-mono text-muted-foreground max-w-xs truncate">
                          {JSON.stringify(e.metadata)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {hasMore && (
                <div className="text-center">
                  <Button variant="outline" onClick={() => void fetchEvents(false)} disabled={loading}>
                    {loading ? "Загрузка…" : "Загрузить ещё"}
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
