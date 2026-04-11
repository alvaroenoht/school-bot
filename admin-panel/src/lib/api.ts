import axios from 'axios';

const api = axios.create({
  baseURL: '/api/admin',
});

// Ensure every request URL ends with a trailing slash to avoid 307 redirects
// that strip the Authorization header.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Add trailing slash if the path has no extension and doesn't already end with /
  if (config.url && !config.url.endsWith('/') && !config.url.includes('?')) {
    config.url = config.url + '/';
  }
  return config;
});

export default api;
