import React from 'react';
import { MapPin, Clock, Heart, MessageCircle, ExternalLink, Sparkles, Gem } from 'lucide-react';
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

const SCORE_LABELS = {
  quality: 'Quality',
  popularity: 'Popularity',
  fun_factor: 'Fun factor',
  demographic_fit: 'Fit',
};

function formatEventDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return String(dateStr).slice(0, 16);
  try {
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

function CurationBadge({ tier }) {
  if (tier === 'top_pick') {
    return (
      <span className="badge-top-pick">
        <Sparkles size={12} /> Top pick
      </span>
    );
  }
  if (tier === 'hidden_gem') {
    return (
      <span className="badge-hidden-gem">
        <Gem size={12} /> Hidden gem
      </span>
    );
  }
  if (tier === 'skip') {
    return <span className="badge-skip">Skip</span>;
  }
  return null;
}

function ScoreBreakdown({ scores }) {
  if (!scores || Object.keys(scores).length === 0) return null;
  return (
    <div className="score-breakdown">
      {Object.entries(SCORE_LABELS).map(([key, label]) => {
        const value = Number(scores[key] ?? 0);
        return (
          <div key={key} className="score-breakdown__row">
            <span className="score-breakdown__label">{label}</span>
            <span className="score-breakdown__bar">
              <span
                className="score-breakdown__fill"
                style={{ width: `${Math.round(value * 100)}%` }}
              />
            </span>
            <span className="score-breakdown__value">{value.toFixed(2)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function EventCard({ event }) {
  const primaryVibe = (event.vibes && event.vibes[0]) || 'other';
  const tier = event.curation_tier || 'standard';
  const tierClass =
    tier === 'top_pick' ? 'is-top-pick'
    : tier === 'hidden_gem' ? 'is-hidden-gem'
    : tier === 'skip' ? 'is-skip'
    : '';

  return (
    <div className={`event-card ${tierClass}`}>
      {/* Image */}
      <div className="event-card-image-wrap">
        {event.image_url ? (
          <img src={event.image_url} alt={event.title} className="event-card-image" loading="lazy" />
        ) : (
          <div className={`event-card-image-placeholder vibe-${primaryVibe}`}>
            {VIBE_ICONS[primaryVibe] || '✨'}
          </div>
        )}
        {tier !== 'standard' && (
          <div className="event-card-tier-overlay">
            <CurationBadge tier={tier} />
          </div>
        )}
      </div>

      <div className="event-card-body">
        <div className="event-card-meta-row">
          <span className={`event-card-source source-${event.source}`}>
            {event.source?.replace(/_/g, ' ')}
          </span>
          {event.account_handle && (
            <span className="account-handle-chip">@{event.account_handle}</span>
          )}
        </div>

        <h3 className="event-card-title">{event.title}</h3>

        {event.venue_name && (
          <div className="event-card-venue">
            <MapPin size={14} />
            <span>{event.venue_name}</span>
          </div>
        )}

        <div className="event-card-datetime">
          <Clock size={14} />
          <span>{formatEventDate(event.date)}</span>
        </div>

        <div className="event-card-badges">
          {event.distance_km != null && (
            <span className="distance-badge">{formatDistance(event.distance_km)} away</span>
          )}
          {event.price && (
            <span className={`price-badge ${event.is_free ? '' : 'paid'}`}>{event.price}</span>
          )}
        </div>

        {event.vibes && event.vibes.length > 0 && (
          <div className="vibe-tags">
            {event.vibes.map((vibe) => (
              <span key={vibe} className={`vibe-tag vibe-tag-${vibe}`}>
                {VIBE_LABELS[vibe] || vibe}
              </span>
            ))}
          </div>
        )}

        <div className="event-card-engagement">
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

        <ScoreBreakdown scores={event.score_breakdown} />

        <div className="event-card-footer">
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="view-event-btn"
          >
            View on Instagram <ExternalLink size={12} />
          </a>
        </div>
      </div>
    </div>
  );
}
