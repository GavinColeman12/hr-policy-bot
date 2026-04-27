import React from 'react';
import {
  MapPin, Clock, Heart, MessageCircle, ExternalLink,
  Sparkles, Gem, Zap, ShieldAlert, Mic2,
} from 'lucide-react';
import { format, formatDistanceToNowStrict, differenceInHours, isToday, isTomorrow, isThisWeek } from 'date-fns';

const VIBE_LABELS = {
  open_air: 'Open-air',
  club_night: 'Club night',
  mingle: 'Mingle',
  headliner: 'Headliner',
  play_party: 'Play party',
  other: 'Other',
};

const VIBE_ICONS = {
  open_air: '☀️',
  club_night: '🌙',
  mingle: '🤝',
  headliner: '🎤',
  play_party: '🔥',
  other: '✨',
};

const SCORE_LABELS = {
  quality: 'Quality',
  popularity: 'Popularity',
  fun_factor: 'Fun factor',
  demographic_fit: 'Fit',
};

/**
 * Returns a vivid "when" string preferring the colloquial form when close,
 * falling back to the explicit weekday + time as the event recedes.
 *  - Tonight 11 PM
 *  - Tomorrow 8 PM
 *  - Saturday 23:00
 *  - Sat May 4 · 8 PM
 */
function whenString(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return String(dateStr).slice(0, 16);
  const hours = differenceInHours(d, new Date());
  let prefix;
  if (isToday(d)) prefix = 'Tonight';
  else if (isTomorrow(d)) prefix = 'Tomorrow';
  else if (isThisWeek(d)) prefix = format(d, 'EEEE');
  else prefix = format(d, 'EEE MMM d');
  // Negative diff means event already passed today — keep prefix but show time.
  const time = format(d, 'h:mm a');
  if (hours > 0 && hours <= 6 && isToday(d)) {
    return `In ${hours}h · ${time}`;
  }
  return `${prefix} · ${time}`;
}

function endTimeString(startStr, endStr) {
  if (!endStr) return null;
  const s = new Date(startStr);
  const e = new Date(endStr);
  if (Number.isNaN(e.getTime())) return null;
  // Same day → just the closing hour, otherwise full short timestamp.
  if (s && format(s, 'yyyy-MM-dd') === format(e, 'yyyy-MM-dd')) {
    return `→ ${format(e, 'h:mm a')}`;
  }
  return `→ ${format(e, 'EEE h:mm a')}`;
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

function blurbFrom(description) {
  if (!description) return '';
  // Take the first sentence, max ~140 chars.
  const flat = description.replace(/\s+/g, ' ').trim();
  const cutAtSentence = flat.match(/^.{20,140}?[.!?](?=\s|$)/);
  if (cutAtSentence) return cutAtSentence[0];
  return flat.length > 140 ? flat.slice(0, 137) + '…' : flat;
}

/**
 * Pick the strongest curation signal — the highest-scoring axis with a
 * label that actually means something to a human reader.
 */
function curationReason(event) {
  const sb = event.score_breakdown || {};
  const entries = Object.entries(sb).filter(([, v]) => Number.isFinite(v));
  if (entries.length === 0) return null;
  const [topKey, topVal] = entries.reduce((a, b) => (a[1] >= b[1] ? a : b));
  if (topVal < 0.7) return null; // only flag genuinely strong dimensions
  const labels = {
    quality: 'Trustworthy event with solid lineup info',
    popularity: 'One of the biggest things happening',
    fun_factor: 'Going to be a great time',
    demographic_fit: 'Squarely in your scene',
  };
  return labels[topKey] || null;
}

function CurationBadge({ tier }) {
  if (tier === 'top_pick') {
    return <span className="badge-top-pick"><Sparkles size={12} /> Top pick</span>;
  }
  if (tier === 'hidden_gem') {
    return <span className="badge-hidden-gem"><Gem size={12} /> Hidden gem</span>;
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

  const isStory = event.scrape_source === 'story';
  const blurb = blurbFrom(event.description);
  const reason = curationReason(event);
  const endStr = endTimeString(event.date, event.end_date);

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
        <div className="event-card-tier-overlay">
          {tier !== 'standard' && <CurationBadge tier={tier} />}
          {isStory && (
            <span className="badge-just-dropped" title="Pulled from a 24h story">
              <Zap size={12} /> Just dropped
            </span>
          )}
        </div>
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

        {blurb && <p className="event-card-blurb">{blurb}</p>}

        {event.venue_name && (
          <div className="event-card-venue">
            <MapPin size={14} />
            <span>{event.venue_name}</span>
          </div>
        )}

        <div className="event-card-datetime">
          <Clock size={14} />
          <span>{whenString(event.date)}</span>
          {endStr && <span className="event-card-endtime">{endStr}</span>}
        </div>

        {/* Lineup */}
        {event.lineup && event.lineup.length > 0 && (
          <div className="event-card-lineup">
            <Mic2 size={13} className="event-card-lineup-icon" />
            <span className="event-card-lineup-list">
              {event.lineup.slice(0, 4).join(' · ')}
              {event.lineup.length > 4 && ` +${event.lineup.length - 4}`}
            </span>
          </div>
        )}

        <div className="event-card-badges">
          {event.distance_km != null && (
            <span className="distance-badge">{formatDistance(event.distance_km)} away</span>
          )}
          {event.price && (
            <span className={`price-badge ${event.is_free ? '' : 'paid'}`}>{event.price}</span>
          )}
          {event.min_age != null && event.min_age > 0 && (
            <span className="age-badge" title="Minimum age">
              <ShieldAlert size={12} /> {event.min_age}+
            </span>
          )}
        </div>

        {event.crowd_note && (
          <div className="event-card-crowd">{event.crowd_note}</div>
        )}

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

        {reason && <div className="event-card-reason">{reason}</div>}

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
