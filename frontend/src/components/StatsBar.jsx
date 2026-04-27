import React from 'react';
import { BarChart3, Clock, AlertTriangle, Users, Search, FileText } from 'lucide-react';

export default function StatsBar({ meta }) {
  if (!meta) return null;

  const {
    total,
    duration,
    accounts_discovered,
    accounts_triaged,
    posts_scraped,
    events_extracted,
    errors,
  } = meta;
  const errorList = Array.isArray(errors) ? errors : [];

  return (
    <div className="stats-bar">
      <div className="stat-item">
        <BarChart3 size={16} className="stat-icon" />
        <span className="stat-value">{total}</span> events
      </div>

      <div className="stat-item" title="Accounts discovered → triaged">
        <Users size={16} className="stat-icon" />
        <span className="stat-value">{accounts_triaged ?? 0}</span> / {accounts_discovered ?? 0} accounts
      </div>

      <div className="stat-item" title="Posts scraped from Instagram">
        <Search size={16} className="stat-icon" />
        <span className="stat-value">{posts_scraped ?? 0}</span> posts
      </div>

      <div className="stat-item" title="Events extracted by Claude">
        <FileText size={16} className="stat-icon" />
        <span className="stat-value">{events_extracted ?? 0}</span> extracted
      </div>

      <div className="stat-item">
        <Clock size={16} className="stat-icon" />
        <span className="stat-value">{duration}s</span>
      </div>

      {errorList.length > 0 && (
        <div className="stat-item stat-errors">
          <AlertTriangle size={16} />
          <span>{errorList.length} stage(s) had errors</span>
          <ul className="error-dropdown">
            {errorList.map((err, i) => (
              <li key={i}>
                {typeof err === 'object' ? `${err.stage || 'unknown'}: ${err.error || 'failed'}` : String(err)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
