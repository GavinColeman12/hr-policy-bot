import { useState, useEffect } from 'react';

/**
 * Custom hook to get the user's browser geolocation.
 * @returns {{ latitude: number|null, longitude: number|null, error: string|null, loading: boolean }}
 */
export default function useGeolocation() {
  const [state, setState] = useState({
    latitude: null,
    longitude: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    if (!navigator.geolocation) {
      setState((prev) => ({
        ...prev,
        error: 'Geolocation is not supported by your browser',
        loading: false,
      }));
      return;
    }

    const onSuccess = (position) => {
      setState({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        error: null,
        loading: false,
      });
    };

    const onError = (err) => {
      setState((prev) => ({
        ...prev,
        error: err.message,
        loading: false,
      }));
    };

    navigator.geolocation.getCurrentPosition(onSuccess, onError, {
      enableHighAccuracy: false,
      timeout: 10000,
      maximumAge: 300000,
    });
  }, []);

  return state;
}
