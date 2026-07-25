/**
 * Status bar showing connection state and market data
 */

import React from 'react';
import type { Candle } from '../types/market';
import './StatusBar.css';

interface StatusBarProps {
  isConnected: boolean;
  latestCandle?: Candle | null;
  symbol?: string;
  error?: string | null;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  isConnected,
  latestCandle,
  symbol = 'BTCUSDT',
  error,
}) => {
  const formatPrice = (price: number) => {
    return price.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 8,
    });
  };

  const change =
    latestCandle && latestCandle.close !== latestCandle.open
      ? latestCandle.close - latestCandle.open
      : 0;

  const changePercent =
    latestCandle && latestCandle.open > 0
      ? ((change / latestCandle.open) * 100).toFixed(2)
      : '0.00';

  const changeColor = change >= 0 ? '#26a69a' : '#ef5350';

  return (
    <div className="status-bar">
      <div className="status-left">
        <div className={`connection-indicator ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className="indicator-dot"></span>
          <span className="indicator-text">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        {error && <div className="error-message">{error}</div>}
      </div>

      <div className="status-middle">
        <span className="symbol-name">{symbol}</span>
      </div>

      {latestCandle && (
        <div className="status-right">
          <div className="price-info">
            <span className="price-label">Close:</span>
            <span className="price-value">${formatPrice(latestCandle.close)}</span>
          </div>
          <div className="price-info">
            <span className="price-label">High:</span>
            <span className="price-value">${formatPrice(latestCandle.high)}</span>
          </div>
          <div className="price-info">
            <span className="price-label">Low:</span>
            <span className="price-value">${formatPrice(latestCandle.low)}</span>
          </div>
          <div className="price-info">
            <span className="price-label">Change:</span>
            <span className="change-value" style={{ color: changeColor }}>
              {change >= 0 ? '+' : ''}{formatPrice(change)} ({changePercent}%)
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
