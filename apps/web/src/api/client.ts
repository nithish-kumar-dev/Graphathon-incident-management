import { createContext, createElement, useContext, useMemo, useRef, type ReactNode } from "react";
import type {
  AlertIn,
  AlertIngestResult,
  ApiErrorBody,
  DemoUser,
  IncidentDetail,
  IncidentList,
  IncidentMemories,
  IncidentStatus,
  IncidentSummary,
  IncidentTimeline,
  IncidentUpdate,
  InvestigationEvents,
  InvestigationIn,
  InvestigationList,
  InvestigationOut,
  MemoryReviewOut,
  ReviewIn,
  ReviewResult,
  ReadinessBody,
  RetrievalBundle,
  ServiceContext,
} from "./types";

/** Every failed request becomes an ApiError. Aborted requests reject with the original AbortError instead. */
export class ApiError extends Error {
  /** HTTP status; 0 when the request never got a response. */
  readonly status: number;
  /** Server error code (e.g. "not_found", "forbidden"), or a client code: "network_error", "invalid_response", "client_error". */
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(init: { status: number; code: string; message: string; requestId?: string | null; details?: unknown }) {
    super(init.message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? null;
  }
}

/** True for the rejection produced by aborting an AbortSignal. Callers should ignore these. */
export function isAbortError(err: unknown): boolean {
  return (
    (typeof DOMException !== "undefined" && err instanceof DOMException && err.name === "AbortError") ||
    (err instanceof Error && err.name === "AbortError")
  );
}

/** Normalise anything thrown into an ApiError (keeps ApiError instances as they are). */
export function toApiError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  const message = err instanceof Error ? err.message : String(err);
  return new ApiError({ status: 0, code: "client_error", message });
}

function isErrorBody(body: unknown): body is ApiErrorBody {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const e = (body as { error: unknown }).error;
  return typeof e === "object" && e !== null && typeof (e as { code?: unknown }).code === "string";
}

type Query = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
}

export interface ApiResult<T> {
  data: T;
  status: number;
}

export interface ListIncidentsParams {
  status?: IncidentStatus;
  limit?: number;
  offset?: number;
}

export interface ServiceContextParams {
  /** 1–3, server default 2. */
  depth?: number;
  /** 1–90, server default 30. */
  deploymentDays?: number;
  limit?: number;
}

export interface MemoriesParams {
  includeUnverified?: boolean;
  limit?: number;
}

export interface Readiness {
  ready: boolean;
  /** HTTP status of /readyz (200 or 503). */
  httpStatus: number;
  body: ReadinessBody | null;
}

export interface ApiClient {
  listIncidents(params?: ListIncidentsParams, signal?: AbortSignal): Promise<IncidentList>;
  getIncident(incidentId: string, signal?: AbortSignal): Promise<IncidentDetail>;
  /** PATCH; the server returns the updated IncidentSummary. */
  updateIncident(incidentId: string, patch: IncidentUpdate, signal?: AbortSignal): Promise<IncidentSummary>;
  getTimeline(incidentId: string, signal?: AbortSignal): Promise<IncidentTimeline>;
  getMemories(incidentId: string, params?: MemoriesParams, signal?: AbortSignal): Promise<IncidentMemories>;
  getServiceContext(serviceId: string, params?: ServiceContextParams, signal?: AbortSignal): Promise<ServiceContext>;
  /** 201 -> created: true; 200 (existing active investigation in the same mode) -> created: false. */
  createInvestigation(
    input: InvestigationIn,
    signal?: AbortSignal,
  ): Promise<{ investigation: InvestigationOut; created: boolean }>;
  getInvestigation(investigationId: string, signal?: AbortSignal): Promise<InvestigationOut>;
  getRetrieval(incidentId: string, signal?: AbortSignal): Promise<RetrievalBundle>;
  /** Earlier and current runs for an incident, newest first. */
  listInvestigations(incidentId: string, limit?: number, signal?: AbortSignal): Promise<InvestigationList>;
  /** Orchestrator step events for one run, in causal order. */
  getInvestigationEvents(investigationId: string, signal?: AbortSignal): Promise<InvestigationEvents>;
  /** Record a human decision on a proposed action. Approving a simulation run executes it in simulation only. */
  reviewAction(actionId: string, input: ReviewIn, signal?: AbortSignal): Promise<ReviewResult>;
  /** Mark the draft memory written after an execution as verified (successful or failed). */
  validateMemory(memoryId: string, outcome: "successful" | "failed", signal?: AbortSignal): Promise<MemoryReviewOut>;
  rejectMemory(memoryId: string, signal?: AbortSignal): Promise<MemoryReviewOut>;
  /** 201 -> created: true (new alert); 200 -> created: false (dedup or replay). */
  ingestAlert(alert: AlertIn, signal?: AbortSignal): Promise<AlertIngestResult & { created: boolean }>;
  /** Never throws for 503; resolves with ready: false. Network failures still throw ApiError("network_error"). */
  getReadiness(signal?: AbortSignal): Promise<Readiness>;
}

export interface CreateClientOptions {
  /** Prefix for every path. Default "" (same origin; Vite proxies /api, /healthz, /readyz). */
  baseUrl?: string;
}

const seg = encodeURIComponent;

export function createClient(getUser: () => DemoUser, options: CreateClientOptions = {}): ApiClient {
  const baseUrl = options.baseUrl ?? "";

  async function send(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(opts.query ?? {})) {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    }
    const search = qs.toString();
    const url = `${baseUrl}${path}${search ? `?${search}` : ""}`;
    const headers: Record<string, string> = { Accept: "application/json", "X-Demo-User": getUser() };
    let body: string | undefined;
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    try {
      // Resolve fetch at call time so test mocks installed later are honoured.
      return await globalThis.fetch(url, { method, headers, body, signal: opts.signal });
    } catch (err) {
      if (isAbortError(err) || opts.signal?.aborted) throw err;
      throw new ApiError({
        status: 0,
        code: "network_error",
        message: `Could not reach the API (${method} ${path}). Is the backend running on :8000?`,
        details: err instanceof Error ? err.message : String(err),
      });
    }
  }

  async function readJson(res: Response): Promise<unknown> {
    const text = await res.text();
    if (text === "") return null;
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new ApiError({
        status: res.status,
        code: "invalid_response",
        message: `Expected JSON from the API but got something else (HTTP ${res.status}).`,
        requestId: res.headers.get("X-Request-ID"),
      });
    }
  }

  function errorFrom(res: Response, body: unknown): ApiError {
    if (isErrorBody(body)) {
      return new ApiError({
        status: res.status,
        code: body.error.code,
        message: body.error.message,
        requestId: body.error.request_id ?? res.headers.get("X-Request-ID"),
        details: body.error.details,
      });
    }
    return new ApiError({
      status: res.status,
      code: `http_${res.status}`,
      message: res.statusText || `HTTP ${res.status}`,
      requestId: res.headers.get("X-Request-ID"),
      details: body,
    });
  }

  async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<ApiResult<T>> {
    const res = await send(method, path, opts);
    let body: unknown;
    try {
      body = await readJson(res);
    } catch (err) {
      if (!res.ok && err instanceof ApiError && err.code === "invalid_response") throw errorFrom(res, null);
      throw err;
    }
    if (!res.ok) throw errorFrom(res, body);
    return { data: body as T, status: res.status };
  }

  const get = async <T>(path: string, query?: Query, signal?: AbortSignal) =>
    (await request<T>("GET", path, { query, signal })).data;

  return {
    listIncidents: (params = {}, signal) => get<IncidentList>("/api/incidents", { ...params }, signal),
    getIncident: (id, signal) => get<IncidentDetail>(`/api/incidents/${seg(id)}`, undefined, signal),
    updateIncident: async (id, patch, signal) =>
      (await request<IncidentSummary>("PATCH", `/api/incidents/${seg(id)}`, { body: patch, signal })).data,
    getTimeline: (id, signal) => get<IncidentTimeline>(`/api/incidents/${seg(id)}/timeline`, undefined, signal),
    getMemories: (id, params = {}, signal) =>
      get<IncidentMemories>(
        `/api/incidents/${seg(id)}/memories`,
        { include_unverified: params.includeUnverified, limit: params.limit },
        signal,
      ),
    getServiceContext: (id, params = {}, signal) =>
      get<ServiceContext>(
        `/api/services/${seg(id)}/context`,
        { depth: params.depth, deployment_days: params.deploymentDays, limit: params.limit },
        signal,
      ),
    createInvestigation: async (input, signal) => {
      const r = await request<InvestigationOut>("POST", "/api/investigations", { body: input, signal });
      return { investigation: r.data, created: r.status === 201 };
    },
    getInvestigation: (id, signal) => get<InvestigationOut>(`/api/investigations/${seg(id)}`, undefined, signal),
    getRetrieval: (id, signal) => get<RetrievalBundle>(`/api/incidents/${seg(id)}/retrieval`, undefined, signal),
    listInvestigations: (id, limit, signal) =>
      get<InvestigationList>(`/api/incidents/${seg(id)}/investigations`, { limit }, signal),
    getInvestigationEvents: (id, signal) =>
      get<InvestigationEvents>(`/api/investigations/${seg(id)}/events`, undefined, signal),
    reviewAction: async (id, input, signal) =>
      (await request<ReviewResult>("POST", `/api/actions/${seg(id)}/review`, { body: input, signal })).data,
    validateMemory: async (id, outcome, signal) =>
      (await request<MemoryReviewOut>("POST", `/api/memories/${seg(id)}/validate`, { body: { outcome }, signal })).data,
    rejectMemory: async (id, signal) =>
      (await request<MemoryReviewOut>("POST", `/api/memories/${seg(id)}/reject`, { signal })).data,
    ingestAlert: async (alert, signal) => {
      const r = await request<AlertIngestResult>("POST", "/api/alerts", { body: alert, signal });
      return { ...r.data, created: r.status === 201 };
    },
    getReadiness: async (signal) => {
      const res = await send("GET", "/readyz", { signal });
      let body: unknown = null;
      try {
        body = await readJson(res);
      } catch {
        body = null;
      }
      const parsed =
        typeof body === "object" && body !== null && "status" in body ? (body as ReadinessBody) : null;
      return { ready: res.ok && parsed?.status === "ready", httpStatus: res.status, body: parsed };
    },
  };
}

// ------------------------------------------------------------------ React context
export interface ApiContextValue {
  client: ApiClient;
  user: DemoUser;
}

const ApiContext = createContext<ApiContextValue | null>(null);

export interface ApiProviderProps {
  user: DemoUser;
  /** Inject a client (tests). Defaults to createClient reading the current `user`. */
  client?: ApiClient;
  children?: ReactNode;
}

/**
 * Provides a stable ApiClient plus the current demo user. The client reads the user through a ref,
 * so it never changes identity; include `user` in your effect deps to refetch when it changes.
 */
export function ApiProvider({ user, client, children }: ApiProviderProps) {
  const userRef = useRef(user);
  userRef.current = user;
  const defaultClient = useMemo(() => createClient(() => userRef.current), []);
  const value = useMemo<ApiContextValue>(() => ({ client: client ?? defaultClient, user }), [client, defaultClient, user]);
  return createElement(ApiContext.Provider, { value }, children);
}

export function useApi(): ApiContextValue {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi() must be used inside <ApiProvider>");
  return ctx;
}
