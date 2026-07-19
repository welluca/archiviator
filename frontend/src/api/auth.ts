import apiClient, { setTokens } from './client';
import type { AuthResponse, User } from '../types';

export const authApi = {
  async login(credentials: { username: string; password: string }): Promise<AuthResponse> {
    // Backend uses OAuth2PasswordRequestForm — send form-encoded data
    const formData = new URLSearchParams();
    formData.append('username', credentials.username);
    formData.append('password', credentials.password);

    const { data } = await apiClient.post<AuthResponse>('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });

    setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async refreshToken(refreshToken: string): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>('/auth/refresh', {
      refresh_token: refreshToken,
    });
    // Refresh rotates both tokens — persist the new pair
    setTokens(data.access_token, data.refresh_token);
    return data;
  },

  async logout(refreshToken: string): Promise<void> {
    await apiClient.post('/auth/logout', { refresh_token: refreshToken });
  },

  async getCurrentUser(): Promise<User> {
    const { data } = await apiClient.get<User>('/auth/me');
    return data;
  },
};
