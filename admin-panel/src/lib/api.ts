import axios from 'axios';

// Resolve API base at runtime:
// - On Caddy (:5005), use relative /api/admin (Caddy proxies to schoolbot)
// - On direct Next.js (:3001 dev), go straight to backend at :8002
// - During SSR, fall back to relative
function resolveBaseURL(): string {
  if (typeof window === 'undefined') return '/api/admin';
  const port = window.location.port;
  if (port === '3001') return 'http://localhost:8002/api/admin';
  return '/api/admin';
}

const api = axios.create({
  baseURL: resolveBaseURL(),
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem('admin_token');
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.location.reload();
      }
    }
    return Promise.reject(error);
  }
);

export default api;
