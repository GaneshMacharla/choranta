export class ApiError extends Error {
  status: number;
  details?: any;
  /** The whole error response (some endpoints add a `code` and the record of what was attempted) */
  body?: any;

  constructor(message: string, status: number, details?: any, body?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
    this.body = body;
  }
}

const API_BASE = '/api';

// The backend stores UTC timestamps without a zone ("2026-10-17T04:47:08"), which browsers read as local time
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

/** Marks zoneless timestamps in an API response as UTC so they display in the viewer's timezone. */
export function markUtc<T>(value: T): T {
  if (typeof value === 'string') return (NAIVE_DATETIME.test(value) ? `${value}Z` : value) as T;
  if (Array.isArray(value)) return value.map(markUtc) as T;
  if (value && typeof value === 'object') {
    for (const key of Object.keys(value)) (value as any)[key] = markUtc((value as any)[key]);
  }
  return value;
}

export async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('choranta_token');
  
  const headers = new Headers(options.headers || {});
  // File uploads (FormData) set their own multipart boundary
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  // Handle empty responses (e.g. 204)
  if (response.status === 204) {
    return {} as T;
  }

  let data: any;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 401) {
      // Clear token on 401 unauthorized
      localStorage.removeItem('choranta_token');
      localStorage.removeItem('choranta_user');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    const message = data?.error || data?.detail || response.statusText || 'Request failed';
    throw new ApiError(message, response.status, data?.details, markUtc(data));
  }

  return markUtc(data) as T;
}
