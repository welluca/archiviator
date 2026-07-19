import apiClient from './client';

/** List row — the plaintext token is NEVER returned after creation. */
export interface DeviceToken {
  id: number;
  label: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

/** Create response — `token` (adt_…) is shown exactly once, stored hashed. */
export interface DeviceTokenCreated {
  id: number;
  label: string;
  token: string;
}

/** Capture-scope device tokens (iOS Shortcuts etc.). A device token can ONLY
 * hit /intake/capture, /labels/resolve/{tag} and attachment upload — all
 * management endpoints here are JWT-only. */
export const deviceTokensApi = {
  async create(label: string): Promise<DeviceTokenCreated> {
    const { data } = await apiClient.post<DeviceTokenCreated>('/auth/device-tokens', {
      label,
    });
    return data;
  },

  async list(): Promise<DeviceToken[]> {
    const { data } = await apiClient.get<DeviceToken[]>('/auth/device-tokens');
    return data;
  },

  async revoke(id: number): Promise<void> {
    await apiClient.post(`/auth/device-tokens/${id}/revoke`);
  },
};
