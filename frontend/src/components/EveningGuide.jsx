import React, { useState } from 'react';
import { Sparkles, Gem, X, ChevronDown, ChevronRight } from 'lucide-react';

function findEvent(events, id) {
  return events.find((e) => e.id === id) || null;
}

function StepRow({ position, event }) {
  if (!event) return null;
  return (
    <div className="evening-guide__step">
      <div className="evening-guide__step-num">{position + 1}</div>
      <div>
        <div className="evening-guide__step-title">{event.title}</div>
        {event.venue_name && (
          <div className="evening-guide__step-venue">{event.venue_name}</div>
        )}
      </div>
    </div>
  );
}

export default function EveningGuide({ guide, events }) {
  const [showGems, setShowGems] = useState(true);
  const [showSkips, setShowSkips] = useState(false);

  if (!guide || !events || events.length === 0) return null;

  const topPick = guide.top_pick_id ? findEvent(events, guide.top_pick_id) : null;
  const itinerary = (guide.itinerary_ids || [])
    .map((id) => findEvent(events, id))
    .filter(Boolean);
  const hiddenGems = (guide.hidden_gem_ids || [])
    .map((id) => findEvent(events, id))
    .filter(Boolean);
  const skips = (guide.skip_ids || [])
    .map((id) => findEvent(events, id))
    .filter(Boolean);

  return (
    <section className="evening-guide" aria-label="Tonight's curated guide">
      {guide.demographic_note && (
        <div className="evening-guide__demo-note">{guide.demographic_note}</div>
      )}
      <p className="evening-guide__summary">{guide.summary_text}</p>

      {topPick && (
        <div className="evening-guide__top-pick">
          <div className="evening-guide__section-label">
            <Sparkles size={14} /> Top pick
          </div>
          <div className="evening-guide__step-title">{topPick.title}</div>
          {topPick.venue_name && (
            <div className="evening-guide__step-venue">{topPick.venue_name}</div>
          )}
        </div>
      )}

      {itinerary.length > 0 && (
        <div className="evening-guide__itinerary">
          <div className="evening-guide__section-label">Suggested itinerary</div>
          {itinerary.map((event, i) => (
            <StepRow key={event.id} position={i} event={event} />
          ))}
        </div>
      )}

      {hiddenGems.length > 0 && (
        <div className="evening-guide__collapsible">
          <button
            className="evening-guide__toggle"
            onClick={() => setShowGems((v) => !v)}
            aria-expanded={showGems}
          >
            {showGems ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <Gem size={14} /> Hidden gems ({hiddenGems.length})
          </button>
          {showGems && (
            <ul className="evening-guide__list">
              {hiddenGems.map((event) => (
                <li key={event.id}>
                  <span>{event.title}</span>
                  {event.venue_name && (
                    <span className="evening-guide__list-venue"> · {event.venue_name}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {skips.length > 0 && (
        <div className="evening-guide__collapsible">
          <button
            className="evening-guide__toggle"
            onClick={() => setShowSkips((v) => !v)}
            aria-expanded={showSkips}
          >
            {showSkips ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <X size={14} /> Skip ({skips.length})
          </button>
          {showSkips && (
            <ul className="evening-guide__list evening-guide__list--skip">
              {skips.map((event) => (
                <li key={event.id}>{event.title}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
