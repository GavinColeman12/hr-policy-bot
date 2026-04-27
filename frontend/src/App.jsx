import React, { useState, useEffect, useCallback } from 'react';
import { searchEvents, getCities, getVibes } from './services/api';
import useGeolocation from './hooks/useGeolocation';
import SearchBar from './components/SearchBar';
import FilterPanel from './components/FilterPanel';
import EventList from './components/EventList';
import EveningGuide from './components/EveningGuide';
import MapView from './components/MapView';
import StatsBar from './components/StatsBar';
import { List, Map, AlertCircle } from 'lucide-react';

const ALL_VIBES = [
  'kinky', 'dating', 'nightlife', 'social', 'music', 'art_culture',
  'food_drink', 'wellness', 'adventure', 'networking', 'lgbtq',
  'underground', 'festival', 'sport_fitness',
];

const TIER_RANK = { top_pick: 0, hidden_gem: 1, standard: 2, skip: 3 };

export default function App() {
  // Search state
  const [city, setCity] = useState('');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [selectedVibes, setSelectedVibes] = useState([]);

  // Results state
  const [events, setEvents] = useState([]);
  const [filteredEvents, setFilteredEvents] = useState([]);
  const [curatedGuide, setCuratedGuide] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchMeta, setSearchMeta] = useState(null);

  // Filter state
  const [sortBy, setSortBy] = useState('curation');
  const [curationFilter, setCurationFilter] = useState('all');
  const [freeOnly, setFreeOnly] = useState(false);
  const [maxDistance, setMaxDistance] = useState(50);

  // View state
  const [view, setView] = useState('list');

  // Available options
  const [cities, setCities] = useState([]);
  const [availableVibes, setAvailableVibes] = useState(ALL_VIBES);

  const geo = useGeolocation();

  useEffect(() => {
    const loadOptions = async () => {
      try {
        const citiesData = await getCities();
        if (Array.isArray(citiesData)) setCities(citiesData);
      } catch {
        setCities([]);
      }
      try {
        const vibesData = await getVibes();
        if (Array.isArray(vibesData) && vibesData.length > 0) setAvailableVibes(vibesData);
      } catch { /* keep defaults */ }
    };
    loadOptions();
  }, []);

  // Apply local filters
  useEffect(() => {
    let result = [...events];

    if (curationFilter === 'top_pick') {
      result = result.filter((e) => e.curation_tier === 'top_pick');
    } else if (curationFilter === 'hidden_gem') {
      result = result.filter((e) => e.curation_tier === 'hidden_gem');
    } else if (curationFilter === 'exclude_skip') {
      result = result.filter((e) => e.curation_tier !== 'skip');
    }

    if (freeOnly) {
      result = result.filter((e) => e.is_free === true || (e.price && e.price.toLowerCase() === 'free'));
    }

    if (maxDistance < 50) {
      result = result.filter((e) => e.distance_km == null || e.distance_km <= maxDistance);
    }

    if (selectedVibes.length > 0) {
      result = result.filter((e) =>
        e.vibes && e.vibes.some((v) => selectedVibes.includes(v))
      );
    }

    const rawEngagement = (e) =>
      (e.engagement_score ?? 0) ||
      ((e.likes ?? 0) + 2 * (e.comments ?? 0) + 3 * (e.attendee_count ?? 0));

    result.sort((a, b) => {
      switch (sortBy) {
        case 'curation': {
          const ta = TIER_RANK[a.curation_tier ?? 'standard'] ?? 2;
          const tb = TIER_RANK[b.curation_tier ?? 'standard'] ?? 2;
          if (ta !== tb) return ta - tb;
          // Within a tier, respect Claude's itinerary order if set
          const pa = a.suggested_itinerary_position ?? 999;
          const pb = b.suggested_itinerary_position ?? 999;
          if (pa !== pb) return pa - pb;
          // Final tiebreaker: raw engagement
          return rawEngagement(b) - rawEngagement(a);
        }
        case 'engagement':
          return rawEngagement(b) - rawEngagement(a);
        case 'distance':
          return (a.distance_km ?? 999) - (b.distance_km ?? 999);
        case 'date': {
          // ISO timestamps sort lexically, but guard for missing values
          const ad = a.date ? new Date(a.date).getTime() : Infinity;
          const bd = b.date ? new Date(b.date).getTime() : Infinity;
          return ad - bd;
        }
        default:
          return 0;
      }
    });

    setFilteredEvents(result);
  }, [events, sortBy, curationFilter, freeOnly, maxDistance, selectedVibes]);

  const handleSearch = useCallback(async () => {
    if (!city) return;

    setLoading(true);
    setError(null);
    setSearchMeta(null);

    const startTime = performance.now();

    try {
      const request = { city, date, radius_km: maxDistance };
      if (selectedVibes.length > 0) request.vibes = selectedVibes;
      if (geo.latitude && geo.longitude) {
        request.latitude = geo.latitude;
        request.longitude = geo.longitude;
      }

      const response = await searchEvents(request);
      const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);

      const eventList = response.events || [];
      setEvents(eventList);
      setCuratedGuide(response.curated_guide || null);
      setSearchMeta({
        total: eventList.length,
        duration: response.search_duration_seconds || elapsed,
        accounts_discovered: response.accounts_discovered || 0,
        accounts_triaged: response.accounts_triaged || 0,
        posts_scraped: response.posts_scraped || 0,
        events_extracted: response.events_extracted || 0,
        errors: response.errors || [],
      });
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Search failed. Please try again.';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [city, date, selectedVibes, maxDistance, geo]);

  const cityCoords = getCityCoords(city);

  return (
    <div className="app">
      <header className="app-header">
        <h1>City Event Crawler</h1>
        <p>Instagram deep discovery, curated by Claude</p>
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

        {curatedGuide && events.length > 0 && (
          <EveningGuide guide={curatedGuide} events={events} />
        )}

        <FilterPanel
          availableVibes={availableVibes}
          selectedVibes={selectedVibes}
          setSelectedVibes={setSelectedVibes}
          curationFilter={curationFilter}
          setCurationFilter={setCurationFilter}
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

        {searchMeta && <StatsBar meta={searchMeta} />}

        {(events.length > 0 || loading) && (
          <div className="view-toggle">
            <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>
              <List size={16} /> List
            </button>
            <button className={view === 'map' ? 'active' : ''} onClick={() => setView('map')}>
              <Map size={16} /> Map
            </button>
          </div>
        )}

        {loading ? (
          <div className="loading-container">
            <div className="spinner" />
            <p>Discovering accounts, scraping posts, and curating tonight's lineup...</p>
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

function getCityCoords(city) {
  const coords = {
    budapest: [47.4979, 19.0402], berlin: [52.52, 13.405], prague: [50.0755, 14.4378],
    vienna: [48.2082, 16.3738], warsaw: [52.2297, 21.0122], krakow: [50.0647, 19.945],
    amsterdam: [52.3676, 4.9041], barcelona: [41.3851, 2.1734], paris: [48.8566, 2.3522],
    london: [51.5074, -0.1278], rome: [41.9028, 12.4964], lisbon: [38.7223, -9.1393],
    copenhagen: [55.6761, 12.5683], stockholm: [59.3293, 18.0686], dublin: [53.3498, -6.2603],
    madrid: [40.4168, -3.7038], munich: [48.1351, 11.582], milan: [45.4642, 9.19],
    athens: [37.9838, 23.7275], istanbul: [41.0082, 28.9784], brussels: [50.8503, 4.3517],
    helsinki: [60.1699, 24.9384], oslo: [59.9139, 10.7522],
  };
  const key = (city || '').toLowerCase().trim();
  return coords[key] || [48.8566, 2.3522];
}
