export class ApiError extends Error {
  status: number;
  details?: any;

  constructor(message: string, status: number, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

const API_BASE = '/api';

export async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('choranta_token');
  
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
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
    throw new ApiError(message, response.status, data?.details);
  }

  return data as T;
}
