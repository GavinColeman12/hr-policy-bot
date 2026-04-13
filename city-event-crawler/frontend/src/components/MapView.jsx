import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';

const VIBE_LABELS = {
  kinky: 'Kinky', dating: 'Dating', nightlife: 'Nightlife', social: 'Social',
  music: 'Music', art_culture: 'Art & Culture', food_drink: 'Food & Drink',
  wellness: 'Wellness', adventure: 'Adventure', networking: 'Networking',
  lgbtq: 'LGBTQ+', underground: 'Underground', festival: 'Festival',
  sport_fitness: 'Sport & Fitness',
};

export default function MapView({ events, center, userLocation }) {
  const mapCenter = center || [48.8566, 2.3522];
  const eventsWithCoords = (events || []).filter(
    (e) => e.latitude != null && e.longitude != null
  );

  return (
    <div className="map-container">
      <MapContainer
        center={mapCenter}
        zoom={13}
        scrollWheelZoom={true}
        style={{ height: '100%', width: '100%' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {eventsWithCoords.map((event, idx) => (
          <Marker key={event.id || idx} position={[event.latitude, event.longitude]}>
            <Popup>
              <div>
                <p className="map-popup-title">{event.title}</p>
                {event.venue_name && (
                  <p className="map-popup-venue">{event.venue_name}</p>
                )}
                {event.vibes && event.vibes.length > 0 && (
                  <div className="map-popup-vibes">
                    {event.vibes.map((v) => (
                      <span key={v} className={`vibe-tag vibe-tag-${v}`} style={{ fontSize: '0.6rem', padding: '2px 6px' }}>
                        {VIBE_LABELS[v] || v}
                      </span>
                    ))}
                  </div>
                )}
                {event.engagement_score > 0 && (
                  <p className="map-popup-engagement">
                    Popularity: {Math.round(event.engagement_score)}
                  </p>
                )}
                {event.source_url && (
                  <a href={event.source_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '0.75rem' }}>
                    View Event
                  </a>
                )}
              </div>
            </Popup>
          </Marker>
        ))}

        {userLocation && (
          <Marker position={[userLocation.lat, userLocation.lon]}>
            <Popup>You are here</Popup>
          </Marker>
        )}
      </MapContainer>
    </div>
  );
}
