import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,  // 5 minutes - the Claude pipeline can take a couple of minutes
  headers: { 'Content-Type': 'application/json' },
});

export async function searchEvents(searchRequest) {
  const { data } = await api.post('/search', searchRequest);
  return data;
}

export async function getCities() {
  const { data } = await api.get('/cities');
  return data;
}

export async function getVibes() {
  const { data } = await api.get('/vibes');
  return data;
}

export default api;
