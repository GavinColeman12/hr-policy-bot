import React from 'react';
import { BarChart3, Globe, Clock, AlertTriangle } from 'lucide-react';

export default function StatsBar({ meta }) {
  if (!meta) return null;

  const { total, duration, sources_searched, source_errors } = meta;
  const errorList = source_errors
    ? (typeof source_errors === 'object' && !Array.isArray(source_errors))
      ? Object.entries(source_errors)
      : Array.isArray(source_errors)
        ? source_errors
        : []
    : [];

  return (
    <div className="stats-bar">
      <div className="stat-item">
        <BarChart3 size={16} className="stat-icon" />
        <span className="stat-value">{total}</span> events found
      </div>

      <div className="stat-item">
        <Globe size={16} className="stat-icon" />
        <span className="stat-value">
          {Array.isArray(sources_searched) ? sources_searched.length : 0}
        </span> sources searched
      </div>

      <div className="stat-item">
        <Clock size={16} className="stat-icon" />
        <span className="stat-value">{duration}s</span>
      </div>

      {errorList.length > 0 && (
        <div className="stat-item stat-errors">
          <AlertTriangle size={16} />
          <span>{errorList.length} source(s) had errors</span>
          <ul className="error-dropdown">
            {errorList.map((err, i) => (
              <li key={i}>
                {Array.isArray(err)
                  ? `${err[0]}: ${err[1]}`
                  : typeof err === 'object'
                    ? `${err.source || 'unknown'}: ${err.error || 'failed'}`
                    : String(err)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
