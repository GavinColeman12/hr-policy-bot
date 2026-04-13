import React from 'react';
import { MapPin, Clock, Users, Heart, MessageCircle, ExternalLink, TrendingUp } from 'lucide-react';
import { format } from 'date-fns';

const VIBE_LABELS = {
  kinky: 'Kinky', dating: 'Dating', nightlife: 'Nightlife', social: 'Social',
  music: 'Music', art_culture: 'Art & Culture', food_drink: 'Food & Drink',
  wellness: 'Wellness', adventure: 'Adventure', networking: 'Networking',
  lgbtq: 'LGBTQ+', underground: 'Underground', festival: 'Festival',
  sport_fitness: 'Sport & Fitness', other: 'Other',
};

const VIBE_ICONS = {
  kinky: '🔥', dating: '💕', nightlife: '🌙', social: '🤝',
  music: '🎵', art_culture: '🎨', food_drink: '🍷', wellness: '🧘',
  adventure: '🏔️', networking: '💼', lgbtq: '🌈', underground: '🕳️',
  festival: '🎪', sport_fitness: '💪', other: '✨',
};

function formatEventDate(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    return format(d, 'EEE, MMM d · h:mm a');
  } catch {
    return String(dateStr).slice(0, 16);
  }
}

function formatDistance(km) {
  if (km == null) return null;
  return km < 1 ? `${Math.round(km * 1000)}m` : `${km.toFixed(1)} km`;
}

function formatCount(n) {
  if (n == null || n === 0) return null;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function EventCard({ event }) {
  const primaryVibe = (event.vibes && event.vibes[0]) || 'other';

  return (
    <div className="event-card">
      {/* Image */}
      {event.image_url ? (
        <img src={event.image_url} alt={event.title} className="event-card-image" loading="lazy" />
      ) : (
        <div className={`event-card-image-placeholder vibe-${primaryVibe}`}>
          {VIBE_ICONS[primaryVibe] || '✨'}
        </div>
      )}

      <div className="event-card-body">
        {/* Source badge */}
        <span className={`event-card-source source-${event.source}`}>
          {event.source?.replace(/_/g, ' ')}
        </span>

        {/* Title */}
        <h3 className="event-card-title">{event.title}</h3>

        {/* Venue */}
        {event.venue_name && (
          <div className="event-card-venue">
            <MapPin size={14} />
            <span>{event.venue_name}</span>
          </div>
        )}

        {/* Date/Time */}
        <div className="event-card-datetime">
          <Clock size={14} />
          <span>{formatEventDate(event.date)}</span>
        </div>

        {/* Badges: distance, price */}
        <div className="event-card-badges">
          {event.distance_km != null && (
            <span className="distance-badge">
              {formatDistance(event.distance_km)} away
            </span>
          )}
          {event.price && (
            <span className={`price-badge ${event.is_free ? '' : 'paid'}`}>
              {event.price}
            </span>
          )}
        </div>

        {/* Vibe tags */}
        {event.vibes && event.vibes.length > 0 && (
          <div className="vibe-tags">
            {event.vibes.map((vibe) => (
              <span key={vibe} className={`vibe-tag vibe-tag-${vibe}`}>
                {VIBE_LABELS[vibe] || vibe}
              </span>
            ))}
          </div>
        )}

        {/* Engagement metrics */}
        <div className="event-card-engagement">
          {formatCount(event.attendee_count) && (
            <div className="engagement-item">
              <Users size={14} />
              <span className="count">{formatCount(event.attendee_count)}</span>
              going
            </div>
          )}
          {formatCount(event.interested_count) && (
            <div className="engagement-item">
              <Users size={14} />
              <span className="count">{formatCount(event.interested_count)}</span>
              interested
            </div>
          )}
          {formatCount(event.likes) && (
            <div className="engagement-item">
              <Heart size={14} />
              <span className="count">{formatCount(event.likes)}</span>
            </div>
          )}
          {formatCount(event.comments) && (
            <div className="engagement-item">
              <MessageCircle size={14} />
              <span className="count">{formatCount(event.comments)}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="event-card-footer">
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="view-event-btn"
          >
            View Event <ExternalLink size={12} />
          </a>
          {event.engagement_score > 0 && (
            <div className="engagement-score">
              <TrendingUp size={14} />
              {Math.round(event.engagement_score)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
