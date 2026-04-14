import React from 'react';

const VIBE_LABELS = {
  kinky: 'Kinky', dating: 'Dating', nightlife: 'Nightlife', social: 'Social',
  music: 'Music', art_culture: 'Art & Culture', food_drink: 'Food & Drink',
  wellness: 'Wellness', adventure: 'Adventure', networking: 'Networking',
  lgbtq: 'LGBTQ+', underground: 'Underground', festival: 'Festival',
  sport_fitness: 'Sport & Fitness',
};

const SOURCE_LABELS = {
  google: 'Google', eventbrite: 'Eventbrite', meetup: 'Meetup',
  instagram: 'Instagram', reddit: 'Reddit', twitter: 'X / Twitter',
  facebook: 'Facebook', resident_advisor: 'Resident Advisor',
  fetlife: 'FetLife', ticketmaster: 'Ticketmaster',
  dice: 'Dice.fm', blog: 'Blogs', guides: 'Event Guides',
};

export default function FilterPanel({
  availableVibes, selectedVibes, setSelectedVibes,
  availableSources, selectedSources, setSelectedSources,
  sortBy, setSortBy, freeOnly, setFreeOnly,
  maxDistance, setMaxDistance,
}) {
  const toggleVibe = (vibe) => {
    const val = typeof vibe === 'string' ? vibe : vibe.value || vibe;
    setSelectedVibes((prev) =>
      prev.includes(val) ? prev.filter((v) => v !== val) : [...prev, val]
    );
  };

  const toggleSource = (source) => {
    const val = typeof source === 'string' ? source : source.value || source;
    setSelectedSources((prev) =>
      prev.includes(val) ? prev.filter((s) => s !== val) : [...prev, val]
    );
  };

  const getVibeValue = (v) => (typeof v === 'string' ? v : v.value || v);
  const getVibeLabel = (v) => {
    const val = getVibeValue(v);
    return VIBE_LABELS[val] || val.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  };

  const getSourceValue = (s) => (typeof s === 'string' ? s : s.value || s);
  const getSourceLabel = (s) => {
    const val = getSourceValue(s);
    return SOURCE_LABELS[val] || val.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  };

  return (
    <div className="filter-panel">
      {/* Vibes */}
      <div className="filter-section">
        <div className="filter-section-header">
          <h3>Vibes</h3>
          <div className="filter-actions">
            <button className="filter-action-btn" onClick={() => setSelectedVibes(availableVibes.map(getVibeValue))}>
              All
            </button>
            <button className="filter-action-btn" onClick={() => setSelectedVibes([])}>
              Clear
            </button>
          </div>
        </div>
        <div className="chip-group">
          {availableVibes.map((vibe) => {
            const val = getVibeValue(vibe);
            return (
              <button
                key={val}
                className={`chip ${selectedVibes.includes(val) ? 'active' : ''}`}
                data-vibe={val}
                onClick={() => toggleVibe(vibe)}
              >
                {getVibeLabel(vibe)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sources */}
      <div className="filter-section">
        <div className="filter-section-header">
          <h3>Sources</h3>
          <div className="filter-actions">
            <button className="filter-action-btn" onClick={() => setSelectedSources(availableSources.map(getSourceValue))}>
              All
            </button>
            <button className="filter-action-btn" onClick={() => setSelectedSources([])}>
              Clear
            </button>
          </div>
        </div>
        <div className="chip-group">
          {availableSources.map((source) => {
            const val = getSourceValue(source);
            return (
              <button
                key={val}
                className={`chip ${selectedSources.includes(val) ? 'active' : ''}`}
                data-source={val}
                onClick={() => toggleSource(source)}
              >
                {getSourceLabel(source)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Controls row */}
      <div className="filter-section">
        <div className="filter-controls-row">
          <select className="sort-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="engagement">Sort: Popularity</option>
            <option value="distance">Sort: Distance</option>
            <option value="date">Sort: Time</option>
            <option value="price">Sort: Price</option>
          </select>

          <label className="free-toggle">
            <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
            Free only
          </label>

          <div className="distance-slider">
            <span>Distance:</span>
            <input
              type="range" min="1" max="50" value={maxDistance}
              onChange={(e) => setMaxDistance(Number(e.target.value))}
            />
            <span>{maxDistance} km</span>
          </div>
        </div>
      </div>
    </div>
  );
}
