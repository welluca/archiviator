import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = '/api/v1';

const ACCESS_KEY = 'archiviator_access_token';
const REFRESH_KEY = 'archiviator_refresh_token';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

export const setTokens = (access: string, refresh: string) => {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
};

export const clearTokens = () => {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
};

export const getStoredAccessToken = (): string | null =>
  localStorage.getItem(ACCESS_KEY);

export const getStoredRefreshToken = (): string | null =>
  localStorage.getItem(REFRESH_KEY);

// Request interceptor — attach Bearer access token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = getStoredAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

/** Hard redirect to /login preserving the current in-app destination as ?next=
 * (LoginPage returns there after auth) — QR-scan deep links must survive this. */
const redirectToLogin = () => {
  if (window.location.pathname === '/login') return;
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.href = `/login?next=${encodeURIComponent(next)}`;
};

// Response interceptor — on 401 try refresh once, retry original request,
// otherwise clear tokens and redirect to /login.
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      const storedRefresh = getStoredRefreshToken();

      if (storedRefresh) {
        try {
          // Plain axios (not apiClient) so this call skips the interceptors
          const response = await axios.post(`${API_BASE_URL}/auth/refresh`, {
            refresh_token: storedRefresh,
          });
          // Refresh rotates BOTH tokens — store the new pair
          setTokens(response.data.access_token, response.data.refresh_token);
          originalRequest.headers.Authorization = `Bearer ${response.data.access_token}`;
          return apiClient(originalRequest);
        } catch {
          clearTokens();
          redirectToLogin();
          return Promise.reject(error);
        }
      } else {
        redirectToLogin();
      }
    }

    return Promise.reject(error);
  }
);

export default apiClient;
