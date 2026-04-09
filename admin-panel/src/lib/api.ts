import axios from 'axios';

const api = axios.create({
  baseURL: '/api/admin',
});

// Add a request interceptor to include JWT token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
