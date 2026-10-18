/**
 * Fetch mock for tests. Routes "METHOD /path" to fixture JSON, records every request, and supports
 * per-test overrides (error envelopes, network failures, response sequences for polling).
 *
 *   const api = installMockApi();
 *   api.on("POST", "/api/investigations", { status: 409, body: errorEnvelope("conflict", "busy") });
 *   api.on("GET", "/api/investigations/nova.ses.01example", [
 *     { body: { ...investigationQueued, status: "running" } },
 *     { body: { ...investigationQueued, status: "completed" } },   // last entry repeats
 *   ]);
 *   ...
 *   expect(api.requests.at(-1)?.user).toBe("demo-responder");
 *
 * `vi.unstubAllGlobals()` (run in setup.ts afterEach) restores the real fetch.
 */
import { vi } from "vitest";
import incidentsFixture from "./fixtures/incidents.json";
import incident092 from "./fixtures/incident_092.json";
import incident101 from "./fixtures/incident_101.json";
import investigation092 from "./fixtures/investigation_092.json";
import investigationQueued from "./fixtures/investigation_queued.json";
import investigationAwaitingReview101 from "./fixtures/investigation_awaiting_review_101.json";
import investigationCompleted101 from "./fixtures/investigation_completed_101.json";
import investigationExecuted101 from "./fixtures/investigation_executed_101.json";
import investigationRejected101 from "./fixtures/investigation_rejected_101.json";
import investigationEvents101 from "./fixtures/investigation_events_101.json";
import investigations101 from "./fixtures/investigations_101.json";
import reviewResult101 from "./fixtures/review_result_101.json";
import memoriesDraft101 from "./fixtures/memories_draft_101.json";
import investigationEscalated101 from "./fixtures/investigation_escalated_101.json";
import investigationFailed101 from "./fixtures/investigation_failed_101.json";
import memories101 from "./fixtures/memories_101.json";
import retrieval101 from "./fixtures/retrieval_101.json";
import servicePayment from "./fixtures/service_payment.json";
import timeline101 from "./fixtures/timeline_101.json";
import error404 from "./fixtures/error_404.json";

export const fixtures = {
  incidents: incidentsFixture,
  incident_101: incident101,
  incident_092: incident092,
  timeline_101: timeline101,
  memories_101: memories101,
  service_payment: servicePayment,
  investigation_092: investigation092,
  investigation_queued: investigationQueued,
  investigation_completed_101: investigationCompleted101,
  investigation_awaiting_review_101: investigationAwaitingReview101,
  investigation_executed_101: investigationExecuted101,
  investigation_rejected_101: investigationRejected101,
  investigation_events_101: investigationEvents101,
  investigations_101: investigations101,
  review_result_101: reviewResult101,
  memories_draft_101: memoriesDraft101,
  investigation_escalated_101: investigationEscalated101,
  investigation_failed_101: investigationFailed101,
  retrieval_101: retrieval101,
  error_404: error404,
} as const;

export interface MockResponse {
  /** Default 200. */
  status?: number;
  /** JSON-serialised. Omit for an empty body. */
  body?: unknown;
  headers?: Record<string, string>;
  /** Reject like fetch does when the network is down. */
  networkError?: boolean;
  /** Resolve after this many ms (honours AbortSignal). Works with fake timers. */
  delayMs?: number;
}

export interface RecordedRequest {
  method: string;
  /** Full URL as passed to fetch. */
  url: string;
  /** Decoded pathname without the query string. */
  path: string;
  query: URLSearchParams;
  headers: Record<string, string>;
  /** Parsed JSON body, or undefined. */
  body: unknown;
  /** Value of the X-Demo-User header. */
  user: string | null;
}

export type Responder = MockResponse | ((req: RecordedRequest) => MockResponse | Promise<MockResponse>);

export interface MockApi {
  /** Every request, in order. */
  requests: RecordedRequest[];
  /** Override a route. A later `on` for the same route wins. An array is a sequence; its last entry repeats. */
  on(method: string, path: string | RegExp, response: Responder | Responder[]): MockApi;
  /** Requests matching a method and path (exact string or RegExp on the pathname). */
  requestsTo(method: string, path: string | RegExp): RecordedRequest[];
  /** The installed vi.fn. */
  fetch: ReturnType<typeof vi.fn>;
}

export function errorEnvelope(code: string, message: string, requestId = "req-test-0001", details?: unknown) {
  return { error: { code, message, request_id: requestId, ...(details === undefined ? {} : { details }) } };
}

const clone = <T,>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));

/** Default routes: every fixture at its real path. */
function defaultRoutes(): Array<[string, string | RegExp, Responder]> {
  return [
    ["GET", "/readyz", { body: { status: "ready", checks: { falkordb: true, postgres: true } } }],
    ["GET", "/healthz", { body: { status: "ok" } }],
    ["GET", "/api/incidents", { body: fixtures.incidents }],
    ["GET", "/api/incidents/nova.inc.101", { body: fixtures.incident_101 }],
    ["GET", "/api/incidents/nova.inc.092", { body: fixtures.incident_092 }],
    ["GET", "/api/incidents/nova.inc.101/timeline", { body: fixtures.timeline_101 }],
    ["GET", "/api/incidents/nova.inc.101/memories", { body: fixtures.memories_101 }],
    ["GET", "/api/incidents/nova.inc.101/retrieval", { body: fixtures.retrieval_101 }],
    ["GET", "/api/incidents/nova.inc.101/investigations", { body: fixtures.investigations_101 }],
    ["GET", /^\/api\/investigations\/[^/]+\/events$/, (req) => ({ body: { ...fixtures.investigation_events_101, investigation_id: req.path.split("/")[3] } })],
    ["GET", "/api/services/nova.svc.payment/context", { body: fixtures.service_payment }],
    ["GET", "/api/investigations/nova.ses.092", { body: fixtures.investigation_092 }],
    ["GET", "/api/investigations/nova.ses.01example", { body: fixtures.investigation_queued }],
    ...[
      fixtures.investigation_completed_101,
      fixtures.investigation_awaiting_review_101,
      fixtures.investigation_escalated_101,
      fixtures.investigation_failed_101,
    ].map((inv): [string, string, Responder] => ["GET", `/api/investigations/${inv.id}`, { body: inv }]),
    ["POST", "/api/investigations", { status: 201, body: fixtures.investigation_queued }],
  ];
}

interface Route {
  method: string;
  path: string | RegExp;
  responders: Responder[];
  calls: number;
}

function matches(route: { method: string; path: string | RegExp }, method: string, path: string) {
  if (route.method.toUpperCase() !== method.toUpperCase()) return false;
  return typeof route.path === "string" ? route.path === path : route.path.test(path);
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

export function installMockApi(): MockApi {
  const requests: RecordedRequest[] = [];
  // Overrides first (newest first), then defaults.
  const overrides: Route[] = [];
  const defaults: Route[] = defaultRoutes().map(([method, path, r]) => ({ method, path, responders: [r], calls: 0 }));

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const urlStr = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(urlStr, "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const headers: Record<string, string> = {};
    new Headers(init.headers).forEach((v, k) => {
      headers[k] = v;
    });
    let body: unknown;
    if (typeof init.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }
    const req: RecordedRequest = {
      method,
      url: urlStr,
      path: decodeURIComponent(url.pathname),
      query: url.searchParams,
      headers,
      body,
      user: headers["x-demo-user"] ?? null,
    };
    requests.push(req);

    const signal = init.signal ?? undefined;
    if (signal?.aborted) throw abortError();

    const route = [...overrides].reverse().find((r) => matches(r, method, req.path)) ??
      defaults.find((r) => matches(r, method, req.path));

    let spec: MockResponse;
    if (!route) {
      spec = { status: 404, body: errorEnvelope("not_found", `no mock for ${method} ${req.path}`) };
    } else {
      const responder = route.responders[Math.min(route.calls, route.responders.length - 1)]!;
      route.calls += 1;
      spec = typeof responder === "function" ? await responder(req) : responder;
    }

    if (spec.delayMs) {
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(resolve, spec.delayMs);
        signal?.addEventListener("abort", () => {
          clearTimeout(t);
          reject(abortError());
        });
      });
    }
    if (signal?.aborted) throw abortError();
    if (spec.networkError) throw new TypeError("Failed to fetch");

    const status = spec.status ?? 200;
    const text = spec.body === undefined ? "" : JSON.stringify(clone(spec.body));
    return new Response(status === 204 ? null : text, {
      status,
      headers: { "Content-Type": "application/json", ...spec.headers },
    });
  });

  vi.stubGlobal("fetch", fetchMock);

  const api: MockApi = {
    requests,
    fetch: fetchMock,
    on(method, path, response) {
      overrides.push({ method, path, responders: Array.isArray(response) ? response : [response], calls: 0 });
      return api;
    },
    requestsTo(method, path) {
      return requests.filter((r) => matches({ method, path }, r.method, r.path));
    },
  };
  return api;
}
