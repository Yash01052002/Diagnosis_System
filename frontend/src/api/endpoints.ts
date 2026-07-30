// Thin, typed wrappers over the REST endpoints. React Query hooks in hooks.ts
// build on these; components can also call them directly (e.g. login).
import { api } from "./client";
import type {
  Crash,
  CrashGroup,
  CrashListItem,
  Device,
  DeviceApiKey,
  DeviceApiKeyCreated,
  DeviceStats,
  Diagnosis,
  KnowledgeBaseStats,
  KnowledgeDocument,
  LoginResponse,
  Page,
  Role,
  SearchResponse,
  TokenPair,
  User,
} from "./types";

/** Drop empty/undefined query params so they don't hit the URL as "?x=". */
function clean<T extends object>(params?: T): Partial<T> | undefined {
  if (!params) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out as Partial<T>;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>("/auth/login", { email, password }).then((r) => r.data),
  register: (body: { email: string; password: string; full_name?: string }) =>
    api.post<User>("/auth/register", body).then((r) => r.data),
  refresh: (refresh_token: string) =>
    api.post<TokenPair>("/auth/refresh", { refresh_token }).then((r) => r.data),
  logout: (all_sessions = false) =>
    api.post("/auth/logout", { all_sessions }).then((r) => r.data),
  me: () => api.get<User>("/auth/me").then((r) => r.data),
  forgotPassword: (email: string) =>
    api.post("/auth/forgot-password", { email }).then((r) => r.data),
  resetPassword: (token: string, new_password: string) =>
    api.post("/auth/reset-password", { token, new_password }).then((r) => r.data),
  changePassword: (current_password: string, new_password: string) =>
    api
      .post("/auth/change-password", { current_password, new_password })
      .then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Users (admin) + self-service profile
// ---------------------------------------------------------------------------
export interface UserListParams {
  q?: string;
  role?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
}

export const usersApi = {
  list: (params: UserListParams) =>
    api.get<Page<User>>("/users", { params: clean(params) }).then((r) => r.data),
  roles: () => api.get<Role[]>("/users/roles").then((r) => r.data),
  get: (id: string) => api.get<User>(`/users/${id}`).then((r) => r.data),
  create: (body: {
    email: string;
    password: string;
    full_name?: string;
    roles: string[];
    is_active: boolean;
  }) => api.post<User>("/users", body).then((r) => r.data),
  update: (
    id: string,
    body: Partial<{
      full_name: string | null;
      email: string;
      is_active: boolean;
      roles: string[];
    }>,
  ) => api.patch<User>(`/users/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/users/${id}`).then((r) => r.data),
  updateMe: (body: { full_name?: string | null; email?: string }) =>
    api.patch<User>("/users/me", body).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
export interface DeviceListParams {
  q?: string;
  status?: string;
  hardware_model?: string;
  firmware_version?: string;
  tag?: string;
  page?: number;
  page_size?: number;
}

export const devicesApi = {
  list: (params: DeviceListParams) =>
    api.get<Page<Device>>("/devices", { params: clean(params) }).then((r) => r.data),
  get: (id: string) => api.get<Device>(`/devices/${id}`).then((r) => r.data),
  create: (body: Record<string, unknown>) =>
    api.post<Device>("/devices", body).then((r) => r.data),
  update: (id: string, body: Record<string, unknown>) =>
    api.patch<Device>(`/devices/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/devices/${id}`).then((r) => r.data),
  stats: (id: string) =>
    api.get<DeviceStats>(`/devices/${id}/stats`).then((r) => r.data),
  apiKeys: (id: string) =>
    api.get<DeviceApiKey[]>(`/devices/${id}/api-keys`).then((r) => r.data),
  createApiKey: (id: string, name: string) =>
    api
      .post<DeviceApiKeyCreated>(`/devices/${id}/api-keys`, { name })
      .then((r) => r.data),
  revokeApiKey: (id: string, keyId: string) =>
    api.delete(`/devices/${id}/api-keys/${keyId}`).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Crashes
// ---------------------------------------------------------------------------
export interface CrashListParams {
  device?: string;
  firmware_version?: string;
  fault_type?: string;
  severity?: string;
  status?: string;
  task_name?: string;
  group_id?: string;
  page?: number;
  page_size?: number;
}

export const crashesApi = {
  list: (params: CrashListParams) =>
    api
      .get<Page<CrashListItem>>("/crashes", { params: clean(params) })
      .then((r) => r.data),
  get: (id: string) => api.get<Crash>(`/crashes/${id}`).then((r) => r.data),
  update: (
    id: string,
    body: Partial<{ status: string; severity: string; notes: string }>,
  ) => api.patch<Crash>(`/crashes/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/crashes/${id}`).then((r) => r.data),
  symbolicate: (id: string) =>
    api.post<Crash>(`/crashes/${id}/symbolicate`).then((r) => r.data),
  diagnose: (id: string) =>
    api.post<Diagnosis>(`/crashes/${id}/diagnose`).then((r) => r.data),
  diagnoses: (id: string) =>
    api.get<Diagnosis[]>(`/crashes/${id}/diagnoses`).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Crash groups
// ---------------------------------------------------------------------------
export interface CrashGroupListParams {
  status?: string;
  fault_type?: string;
  severity?: string;
  page?: number;
  page_size?: number;
}

export const groupsApi = {
  list: (params: CrashGroupListParams) =>
    api
      .get<Page<CrashGroup>>("/crash-groups", { params: clean(params) })
      .then((r) => r.data),
  top: (limit = 10) =>
    api
      .get<CrashGroup[]>("/crash-groups/top", { params: { limit } })
      .then((r) => r.data),
  get: (id: string) => api.get<CrashGroup>(`/crash-groups/${id}`).then((r) => r.data),
  crashes: (id: string, page = 1, page_size = 20) =>
    api
      .get<Page<CrashListItem>>(`/crash-groups/${id}/crashes`, {
        params: { page, page_size },
      })
      .then((r) => r.data),
  update: (
    id: string,
    body: Partial<{ status: string; severity: string; title: string; notes: string }>,
  ) => api.patch<CrashGroup>(`/crash-groups/${id}`, body).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Knowledge base & diagnoses (Phase 3)
// ---------------------------------------------------------------------------
export interface DocumentListParams {
  q?: string;
  source_type?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export const knowledgeApi = {
  list: (params: DocumentListParams) =>
    api
      .get<Page<KnowledgeDocument>>("/knowledge-base/documents", {
        params: clean(params),
      })
      .then((r) => r.data),
  get: (id: string) =>
    api.get<KnowledgeDocument>(`/knowledge-base/documents/${id}`).then((r) => r.data),
  stats: () =>
    api.get<KnowledgeBaseStats>("/knowledge-base/stats").then((r) => r.data),
  create: (body: {
    title: string;
    content: string;
    source_type: string;
    metadata?: Record<string, unknown> | null;
  }) =>
    api
      .post<KnowledgeDocument>("/knowledge-base/documents", body)
      .then((r) => r.data),
  upload: (file: File, source_type: string, title?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("source_type", source_type);
    if (title) form.append("title", title);
    return api
      .post<KnowledgeDocument>("/knowledge-base/documents/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },
  remove: (id: string) =>
    api.delete(`/knowledge-base/documents/${id}`).then((r) => r.data),
  search: (query: string, top_k = 6) =>
    api
      .post<SearchResponse>("/knowledge-base/search", { query, top_k })
      .then((r) => r.data),
};

export const diagnosesApi = {
  get: (id: string) => api.get<Diagnosis>(`/diagnoses/${id}`).then((r) => r.data),
};
