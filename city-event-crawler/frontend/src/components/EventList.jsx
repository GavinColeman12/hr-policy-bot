import React, { useState } from 'react';
import EventCard from './EventCard';
import { Search } from 'lucide-react';

const PAGE_SIZE = 24;

export default function EventList({ events }) {
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  if (!events || events.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon"><Search size={64} strokeWidth={1} /></div>
        <h3>No events found</h3>
        <p>
          Select a city and date, then hit Discover to find events.
          Try adjusting your filters or expanding the search radius.
        </p>
      </div>
    );
  }

  const visible = events.slice(0, visibleCount);
  const hasMore = visibleCount < events.length;

  return (
    <div>
      <div className="results-header">
        <h2>Events ({events.length})</h2>
        <span>Showing {Math.min(visibleCount, events.length)} of {events.length}</span>
      </div>

      <div className="event-grid">
        {visible.map((event, idx) => (
          <EventCard key={event.id || idx} event={event} />
        ))}
      </div>

      {hasMore && (
        <div className="load-more-container">
          <button
            className="load-more-btn"
            onClick={() => setVisibleCount((prev) => prev + PAGE_SIZE)}
          >
            Load More ({events.length - visibleCount} remaining)
          </button>
        </div>
      )}
    </div>
  );
}
