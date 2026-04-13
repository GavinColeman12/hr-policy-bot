import React from 'react';
import { Search } from 'lucide-react';

export default function SearchBar({ city, setCity, date, setDate, cities, onSearch, loading }) {
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && city) onSearch();
  };

  const cityList = Array.isArray(cities)
    ? cities.map((c) => (typeof c === 'string' ? c : c.name || c.label || ''))
    : [];

  return (
    <div className="search-bar">
      <div className="search-field" style={{ flex: 2 }}>
        <label>City</label>
        <select
          value={city}
          onChange={(e) => setCity(e.target.value)}
          onKeyDown={handleKeyDown}
        >
          <option value="">Select a city...</option>
          {cityList.map((c) => (
            <option key={c} value={typeof c === 'string' ? c.toLowerCase() : c}>
              {typeof c === 'string' ? c.charAt(0).toUpperCase() + c.slice(1) : c}
            </option>
          ))}
        </select>
      </div>

      <div className="search-field">
        <label>Date</label>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          onKeyDown={handleKeyDown}
        />
      </div>

      <button
        className="discover-btn"
        onClick={onSearch}
        disabled={!city || loading}
      >
        {loading ? (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} />
            Crawling...
          </span>
        ) : (
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Search size={16} />
            Discover
          </span>
        )}
      </button>
    </div>
  );
}
