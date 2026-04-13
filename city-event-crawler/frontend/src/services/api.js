import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Search for events.
 * @param {object} searchRequest - { city, date, vibes?, latitude?, longitude?, radius_km? }
 * @returns {Promise<object>} Search response with events, sources, timing, etc.
 */
export async function searchEvents(searchRequest) {
  const { data } = await api.post('/search', searchRequest);
  return data;
}

/**
 * Get available cities.
 * @returns {Promise<string[]>}
 */
export async function getCities() {
  const { data } = await api.get('/cities');
  return data;
}

/**
 * Get available vibes.
 * @returns {Promise<string[]>}
 */
export async function getVibes() {
  const { data } = await api.get('/vibes');
  return data;
}

/**
 * Get available source platforms.
 * @returns {Promise<string[]>}
 */
export async function getSources() {
  const { data } = await api.get('/sources');
  return data;
}

export default api;
