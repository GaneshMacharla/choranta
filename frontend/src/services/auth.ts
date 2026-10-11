import { request } from './api';
import { User } from '../types';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export const authService = {
  login: async (email: string, password: string): Promise<LoginResponse> => {
    return request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  loginWithGoogle: async (credential: string): Promise<LoginResponse> => {
    return request<LoginResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },

  getConfig: async (): Promise<{ google_client_id: string | null }> => {
    return request<{ google_client_id: string | null }>('/auth/config');
  },

  getCurrentUser: async (): Promise<User> => {
    return request<User>('/auth/me', {
      method: 'GET',
    });
  },
};
