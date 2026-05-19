import axios from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for adding auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for handling auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - redirect to login
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// API service functions
export const authAPI = {
  login: (email: string, password: string) =>
    api.post(
      '/auth/login',
      new URLSearchParams({ username: email, password }),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    ),
  register: (data: { email: string; password: string; full_name?: string }) =>
    api.post('/auth/register', data),
  refreshToken: (refreshToken: string) =>
    api.post('/auth/refresh', { refresh_token: refreshToken }),
};

export const userAPI = {
  getProfile: () => api.get('/users/me'),
  updateProfile: (data: { full_name?: string; avatar_url?: string }) =>
    api.put('/users/me', data),
  getTenants: () => api.get('/users/me/tenants'),
};

export const projectAPI = {
  list: () => api.get('/projects/'),
  get: (id: string) => api.get(`/projects/${id}`),
  create: (data: { name: string; domain: string; description?: string; keywords?: string[] }) =>
    api.post('/projects/', data),
  update: (id: string, data: { name?: string; description?: string; keywords?: string[] }) =>
    api.put(`/projects/${id}`, data),
  delete: (id: string) => api.delete(`/projects/${id}`),
};

export const crawlAPI = {
  start: (data: { url: string; project_id?: string; max_pages?: number; depth?: number }) =>
    api.post('/crawl/start', data),
  getStatus: (id: string) => api.get(`/crawl/${id}`),
  list: (project_id?: string) => api.get('/crawl/', { params: { project_id } }),
  cancel: (id: string) => api.post(`/crawl/${id}/cancel`),
};

export const serpAPI = {
  analyze: (data: { keywords: string[]; project_id?: string; location?: string; language?: string }) =>
    api.post('/serp/analyze', data),
  getStatus: (id: string) => api.get(`/serp/${id}`),
  list: (project_id?: string) => api.get('/serp/', { params: { project_id } }),
};

export const visibilityAPI = {
  query: (data: { keywords?: string[]; topics?: string[]; date_range?: object }) =>
    api.post('/visibility/query', data),
  getTrends: (days?: number) => api.get('/visibility/trends', { params: { days } }),
  getCompetitors: () => api.get('/visibility/competitors'),
};

export const agentAPI = {
  list: () => api.get('/agents/'),
  run: (agentType: string, data: { config?: object; input_data: object }) =>
    api.post(`/agents/${agentType}/run`, data),
};

export const billingAPI = {
  getSubscription: () => api.get('/billing/subscription'),
  createCheckout: (priceId: string) => api.post('/billing/checkout', { price_id: priceId }),
  cancelSubscription: () => api.delete('/billing/subscription'),
};
