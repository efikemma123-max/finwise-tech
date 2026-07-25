/**
 * Indicator configuration panel
 * Allows enabling/disabling indicators and configuring parameters
 */

import React, { useState } from 'react';
import type { IndicatorConfig } from '../types/market';
import './IndicatorPanel.css';

interface IndicatorPanelProps {
  config: IndicatorConfig;
  onConfigChange: (config: IndicatorConfig) => void;
}

export const IndicatorPanel: React.FC<IndicatorPanelProps> = ({ config, onConfigChange }) => {
  const [expanded, setExpanded] = useState(false);

  const handleMovingAverageToggle = () => {
    onConfigChange({
      ...config,
      moving_averages: {
        ...config.moving_averages,
        enabled: !config.moving_averages.enabled,
      },
    });
  };

  const handleRSIToggle = () => {
    onConfigChange({
      ...config,
      rsi: {
        ...config.rsi,
        enabled: !config.rsi.enabled,
      },
    });
  };

  const handleMACDToggle = () => {
    onConfigChange({
      ...config,
      macd: {
        ...config.macd,
        enabled: !config.macd.enabled,
      },
    });
  };

  return (
    <div className="indicator-panel">
      <button className="panel-toggle" onClick={() => setExpanded(!expanded)}>
        <span>📊 Indicators</span>
        <span className="toggle-icon">{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div className="panel-content">
          {/* Phase 1: MVP */}
          <div className="indicator-group">
            <h3 className="group-title">📈 Phase 1: MVP</h3>
            <label className="indicator-option">
              <input
                type="checkbox"
                checked={config.moving_averages.enabled}
                onChange={handleMovingAverageToggle}
              />
              <span>Moving Averages (EMA 20/50)</span>
            </label>
          </div>

          {/* Phase 2: In Development */}
          <div className="indicator-group">
            <h3 className="group-title">⚙️ Phase 2: In Development</h3>
            <label className="indicator-option disabled">
              <input
                type="checkbox"
                checked={config.rsi.enabled}
                onChange={handleRSIToggle}
                disabled
              />
              <span>RSI (Relative Strength Index)</span>
            </label>
            <label className="indicator-option disabled">
              <input
                type="checkbox"
                checked={config.macd.enabled}
                onChange={handleMACDToggle}
                disabled
              />
              <span>MACD (Moving Average Convergence)</span>
            </label>
          </div>

          {/* Phase 3: Future */}
          <div className="indicator-group">
            <h3 className="group-title">🎯 Phase 3: Future</h3>
            <p className="phase-note">Drawing tools, Trendlines, Support/Resistance</p>
          </div>
        </div>
      )}
    </div>
  );
};
