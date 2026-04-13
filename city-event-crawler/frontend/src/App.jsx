import React, { useState, useEffect, useCallback } from 'react';
import { searchEvents, getCities, getVibes, getSources } from './services/api';
import useGeolocation from './hooks/useGeolocation';
import SearchBar from './components/SearchBar';
import FilterPanel from './components/FilterPanel';
import EventList from './components/EventList';
import MapView from './components/MapView';
import StatsBar from './components/StatsBar';
import { List, Map, AlertCircle } from 'lucide-react';

const ALL_VIBES = [
  'kinky', 'dating', 'nightlife', 'social', 'music', 'art_culture',
  'food_drink', 'wellness', 'adventure', 'networking', 'lgbtq',
  'underground', 'festival', 'sport_fitness',
];

const ALL_SOURCES = [
  'google', 'eventbrite', 'meetup', 'instagram', 'reddit', 'twitter',
  'facebook', 'resident_advisor', 'fetlife', 'ticketmaster', 'yelp',
];

export default function App() {
  // Search state
  const [city, setCity] = useState('');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [selectedVibes, setSelectedVibes] = useState([]);
  const [selectedSources, setSelectedSources] = useState([]);

  // Results state
  const [events, setEvents] = useState([]);
  const [filteredEvents, setFilteredEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchMeta, setSearchMeta] = useState(null);

  // Filter state
  const [sortBy, setSortBy] = useState('engagement');
  const [freeOnly, setFreeOnly] = useState(false);
  const [maxDistance, setMaxDistance] = useState(50);

  // View state
  const [view, setView] = useState('list');

  // Available options (from API or defaults)
  const [cities, setCities] = useState([]);
  const [availableVibes, setAvailableVibes] = useState(ALL_VIBES);
  const [availableSources, setAvailableSources] = useState(ALL_SOURCES);

  // Geolocation
  const geo = useGeolocation();

  // Load cities and options on mount
  useEffect(() => {
    const loadOptions = async () => {
      try {
        const citiesData = await getCities();
        if (Array.isArray(citiesData)) {
          setCities(citiesData);
        } else if (citiesData && typeof citiesData === 'object') {
          setCities(Object.keys(citiesData));
        }
      } catch {
        // Fallback to built-in list
        setCities([
          'amsterdam', 'athens', 'antwerp', 'barcelona', 'belgrade', 'berlin',
          'bratislava', 'brussels', 'bucharest', 'budapest', 'cologne',
          'copenhagen', 'dublin', 'edinburgh', 'florence', 'frankfurt',
          'geneva', 'hamburg', 'helsinki', 'istanbul', 'krakow', 'lisbon',
          'ljubljana', 'london', 'madrid', 'milan', 'munich', 'naples',
          'oslo', 'paris', 'porto', 'prague', 'riga', 'rome', 'seville',
          'sofia', 'stockholm', 'tallinn', 'thessaloniki', 'valencia',
          'vienna', 'vilnius', 'warsaw', 'zagreb', 'zurich',
        ]);
      }

      try {
        const vibesData = await getVibes();
        if (Array.isArray(vibesData) && vibesData.length > 0) {
          setAvailableVibes(vibesData);
        }
      } catch {
        // keep defaults
      }

      try {
        const sourcesData = await getSources();
        if (Array.isArray(sourcesData) && sourcesData.length > 0) {
          setAvailableSources(sourcesData);
        }
      } catch {
        // keep defaults
      }
    };
    loadOptions();
  }, []);

  // Apply local filters whenever events/filters change
  useEffect(() => {
    let result = [...events];

    // Free only filter
    if (freeOnly) {
      result = result.filter((e) => e.is_free === true || (e.price && e.price.toLowerCase() === 'free'));
    }

    // Distance filter
    if (maxDistance < 50) {
      result = result.filter((e) => {
        if (e.distance_km == null) return true;
        return e.distance_km <= maxDistance;
      });
    }

    // Vibe filter (client-side additional)
    if (selectedVibes.length > 0) {
      result = result.filter((e) =>
        e.vibes && e.vibes.some((v) => selectedVibes.includes(v))
      );
    }

    // Source filter
    if (selectedSources.length > 0) {
      result = result.filter((e) => selectedSources.includes(e.source));
    }

    // Sort
    result.sort((a, b) => {
      switch (sortBy) {
        case 'engagement':
          return (b.engagement_score || 0) - (a.engagement_score || 0);
        case 'distance':
          return (a.distance_km ?? 999) - (b.distance_km ?? 999);
        case 'date':
          return (a.date || '').localeCompare(b.date || '') || (a.start_time || '').localeCompare(b.start_time || '');
        case 'price': {
          const aFree = a.is_free || (a.price && a.price.toLowerCase() === 'free') ? 0 : 1;
          const bFree = b.is_free || (b.price && b.price.toLowerCase() === 'free') ? 0 : 1;
          return aFree - bFree;
        }
        default:
          return 0;
      }
    });

    setFilteredEvents(result);
  }, [events, sortBy, freeOnly, maxDistance, selectedVibes, selectedSources]);

  // Search handler
  const handleSearch = useCallback(async () => {
    if (!city) return;

    setLoading(true);
    setError(null);
    setSearchMeta(null);

    const startTime = performance.now();

    try {
      const request = {
        city,
        date,
        radius_km: maxDistance,
      };

      if (selectedVibes.length > 0) {
        request.vibes = selectedVibes;
      }

      if (geo.latitude && geo.longitude) {
        request.latitude = geo.latitude;
        request.longitude = geo.longitude;
      }

      const response = await searchEvents(request);
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

      const eventList = response.events || response.results || [];
      setEvents(eventList);
      setSearchMeta({
        total: eventList.length,
        duration: response.duration || elapsed,
        sources_searched: response.sources_searched || [],
        source_errors: response.source_errors || {},
      });
    } catch (err) {
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
      const message = err.response?.data?.detail || err.message || 'Search failed. Please try again.';
      setError(message);

      // If we still got some data back on partial failure
      if (err.response?.data?.events) {
        setEvents(err.response.data.events);
        setSearchMeta({
          total: err.response.data.events.length,
          duration: elapsed,
          sources_searched: err.response.data.sources_searched || [],
          source_errors: err.response.data.source_errors || {},
        });
      }
    } finally {
      setLoading(false);
    }
  }, [city, date, selectedVibes, maxDistance, geo]);

  // City coordinates for map centering
  const cityCoords = getCityCoords(city);

  return (
    <div className="app">
      <header className="app-header">
        <h1>City Event Crawler</h1>
        <p>Discover events across European cities by vibe</p>
      </header>

      <main className="app-main">
        <SearchBar
          city={city}
          setCity={setCity}
          date={date}
          setDate={setDate}
          cities={cities}
          onSearch={handleSearch}
          loading={loading}
        />

        <FilterPanel
          availableVibes={availableVibes}
          selectedVibes={selectedVibes}
          setSelectedVibes={setSelectedVibes}
          availableSources={availableSources}
          selectedSources={selectedSources}
          setSelectedSources={setSelectedSources}
          sortBy={sortBy}
          setSortBy={setSortBy}
          freeOnly={freeOnly}
          setFreeOnly={setFreeOnly}
          maxDistance={maxDistance}
          setMaxDistance={setMaxDistance}
        />

        {error && (
          <div className="error-banner">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}

        {searchMeta && (
          <StatsBar meta={searchMeta} />
        )}

        {(events.length > 0 || loading) && (
          <div className="view-toggle">
            <button
              className={view === 'list' ? 'active' : ''}
              onClick={() => setView('list')}
            >
              <List size={16} /> List
            </button>
            <button
              className={view === 'map' ? 'active' : ''}
              onClick={() => setView('map')}
            >
              <Map size={16} /> Map
            </button>
          </div>
        )}

        {loading ? (
          <div className="loading-container">
            <div className="spinner" />
            <p>Crawling events across platforms...</p>
          </div>
        ) : view === 'list' ? (
          <EventList events={filteredEvents} />
        ) : (
          <MapView
            events={filteredEvents}
            center={cityCoords}
            userLocation={geo.latitude ? { lat: geo.latitude, lon: geo.longitude } : null}
          />
        )}
      </main>
    </div>
  );
}

/** Quick lookup for city center coords (for map centering). */
function getCityCoords(city) {
  const coords = {
    budapest: [47.4979, 19.0402],
    berlin: [52.52, 13.405],
    prague: [50.0755, 14.4378],
    vienna: [48.2082, 16.3738],
    warsaw: [52.2297, 21.0122],
    krakow: [50.0647, 19.945],
    amsterdam: [52.3676, 4.9041],
    barcelona: [41.3851, 2.1734],
    paris: [48.8566, 2.3522],
    london: [51.5074, -0.1278],
    rome: [41.9028, 12.4964],
    lisbon: [38.7223, -9.1393],
    copenhagen: [55.6761, 12.5683],
    stockholm: [59.3293, 18.0686],
    dublin: [53.3498, -6.2603],
    madrid: [40.4168, -3.7038],
    munich: [48.1351, 11.582],
    milan: [45.4642, 9.19],
    athens: [37.9838, 23.7275],
    istanbul: [41.0082, 28.9784],
    brussels: [50.8503, 4.3517],
    helsinki: [60.1699, 24.9384],
    oslo: [59.9139, 10.7522],
    belgrade: [44.7866, 20.4489],
    bucharest: [44.4268, 26.1025],
    sofia: [42.6977, 23.3219],
    zagreb: [45.815, 15.9819],
    tallinn: [59.437, 24.7536],
    riga: [56.9496, 24.1052],
    vilnius: [54.6872, 25.2797],
    porto: [41.1579, -8.6291],
    seville: [37.3891, -5.9845],
    florence: [43.7696, 11.2558],
    hamburg: [53.5511, 9.9937],
    cologne: [50.9375, 6.9603],
    frankfurt: [50.1109, 8.6821],
    geneva: [46.2044, 6.1432],
    zurich: [47.3769, 8.5417],
    naples: [40.8518, 14.2681],
    valencia: [39.4699, -0.3763],
    edinburgh: [55.9533, -3.1883],
    antwerp: [51.2194, 4.4025],
    thessaloniki: [40.6401, 22.9444],
    bratislava: [48.1486, 17.1077],
    ljubljana: [46.0569, 14.5058],
  };
  const key = (city || '').toLowerCase().trim();
  return coords[key] || [48.8566, 2.3522]; // default to Paris
}
