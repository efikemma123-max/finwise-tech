import { useMemo, useState } from 'react';
import './Dashboard.css';
import {
  BellIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  LogoMark,
  SearchIcon,
  SlidersIcon,
  SyncIcon,
} from '../market/MarketIcons';

interface DashboardProps {
  onOpenNotifications: () => void;
  onSelectMarket: () => void;
  displayName: string;
}

interface PerformanceCard {
  label: string;
  value: string;
  delta: string;
  tone: 'positive' | 'negative';
}

interface TradeHistoryItem {
  id: string;
  symbol: string;
  side: 'Buy' | 'Sell';
  amount: string;
  value: string;
  time: string;
  badge: string;
}

const PERFORMANCE_CARDS: PerformanceCard[] = [
  { label: 'Total Profit', value: '+2,450.75', delta: '12.45% vs last 24h', tone: 'positive' },
  { label: 'Total Loss', value: '-942.30', delta: '5.32% vs last 24h', tone: 'negative' },
];

const TRADE_HISTORY: TradeHistoryItem[] = [
  { id: 'btc', symbol: 'BTC/USDT', side: 'Buy', amount: '+0.045 BTC', value: '+1,234.50 USDT', time: 'May 29, 2025 - 10:24 AM', badge: 'B' },
  { id: 'eth', symbol: 'ETH/USDT', side: 'Sell', amount: '-1.250 ETH', value: '-2,450.00 USDT', time: 'May 29, 2025 - 09:15 AM', badge: 'E' },
  { id: 'sol', symbol: 'SOL/USDT', side: 'Buy', amount: '+12.00 SOL', value: '+1,020.00 USDT', time: 'May 28, 2025 - 08:42 PM', badge: 'S' },
  { id: 'xrp', symbol: 'XRP/USDT', side: 'Sell', amount: '-500 XRP', value: '-230.00 USDT', time: 'May 28, 2025 - 07:30 PM', badge: 'X' },
];

function getInitials(displayName: string) {
  const parts = displayName
    .split(/\s+/)
    .map((part) => part.trim())
    .filter(Boolean);

  if (parts.length === 0) {
    return 'FW';
  }

  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }

  return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase();
}

export function Dashboard({ onOpenNotifications, onSelectMarket, displayName }: DashboardProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const winRate = 68;
  const netPnl = '+1,508.45';
  const initials = getInitials(displayName);

  const winRateStyle = useMemo(
    () => ({ background: `conic-gradient(#2ce9ca 0deg ${winRate * 3.6}deg, rgba(255, 255, 255, 0.08) ${winRate * 3.6}deg 360deg)` }),
    [winRate]
  );

  return (
    <div className="dashboard-screen">
      <header className="dashboard-topbar">
        <div className="dashboard-brand">
          <div className="dashboard-brand__mark">
            <LogoMark />
          </div>
          <div>
            <p className="dashboard-brand__name">Finwise AI</p>
            <span className="dashboard-brand__tag">Smart crypto insights</span>
          </div>
        </div>

        <div className="dashboard-topbar__actions">
          <button className="dashboard-icon-button" type="button" onClick={onOpenNotifications} aria-label="Open notifications">
            <BellIcon />
            <span className="dashboard-icon-button__badge">3</span>
          </button>
          <button className="dashboard-avatar" type="button" aria-label={`Open profile for ${displayName}`} title={displayName}>
            {initials}
          </button>
        </div>
      </header>

      <section className="dashboard-search-row">
        <label className="glass-card dashboard-search">
          <SearchIcon />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search trading pairs (e.g. BTC/USDT)"
            aria-label="Search trading pairs"
          />
        </label>
        <button className="glass-card dashboard-icon-button dashboard-icon-button--square" type="button" aria-label="Filter pairs">
          <SlidersIcon />
        </button>
      </section>

      <section className="glass-card dashboard-sync">
        <div className="dashboard-sync__icon">
          <SyncIcon />
        </div>
        <div className="dashboard-sync__copy">
          <div className="dashboard-sync__title-row">
            <strong>Engine Syncing</strong>
            <span className="dashboard-live-pill">Live</span>
          </div>
          <p>Real-time market data is being updated and your mobile workspace stays in lockstep.</p>
        </div>
      </section>

      <button className="glass-card dashboard-spotlight" type="button" onClick={onSelectMarket}>
        <div>
          <h1>Market Analysis</h1>
          <p>Real-time overview of the crypto market</p>
        </div>
        <span className="dashboard-spotlight__timeframe">
          24H
          <ChevronDownIcon />
        </span>
      </button>

      <section className="glass-card dashboard-pnl">
        <div className="dashboard-section-heading">
          <div>
            <h2>Profit &amp; Loss (P&amp;L)</h2>
            <p>Daily performance across your active book.</p>
          </div>
          <button type="button">View all</button>
        </div>

        <div className="dashboard-pnl__grid">
          {PERFORMANCE_CARDS.map((card) => (
            <article key={card.label} className={`dashboard-metric-card dashboard-metric-card--${card.tone}`}>
              <span className="dashboard-metric-card__label">{card.label}</span>
              <strong>{card.value}</strong>
              <small>{card.delta}</small>
              <div className="dashboard-metric-card__spark" aria-hidden="true">
                <span />
              </div>
            </article>
          ))}
        </div>

        <div className="dashboard-performance-row">
          <div className="dashboard-performance-row__metric">
            <span>Net P&amp;L</span>
            <strong>{netPnl} <em>USDT</em></strong>
          </div>

          <div className="dashboard-win-rate">
            <div className="dashboard-win-rate__ring" style={winRateStyle}>
              <div className="dashboard-win-rate__ring-core">{winRate}%</div>
            </div>
            <div>
              <span>Winning Trades</span>
              <strong>34 of 50</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="glass-card dashboard-history">
        <div className="dashboard-section-heading">
          <div>
            <h2>Trade History</h2>
            <p>Recent activity from your mobile desk.</p>
          </div>
          <button type="button">View all</button>
        </div>

        <div className="dashboard-history__list">
          {TRADE_HISTORY.map((trade) => (
            <article key={trade.id} className="dashboard-trade-row">
              <div className={`dashboard-trade-row__badge dashboard-trade-row__badge--${trade.id}`}>{trade.badge}</div>
              <div className="dashboard-trade-row__main">
                <div className="dashboard-trade-row__headline">
                  <strong>{trade.symbol}</strong>
                  <span className={`dashboard-trade-row__side dashboard-trade-row__side--${trade.side.toLowerCase()}`}>
                    {trade.side}
                  </span>
                </div>
                <span>{trade.time}</span>
              </div>
              <div className="dashboard-trade-row__stats">
                <strong>{trade.amount}</strong>
                <span>{trade.value}</span>
              </div>
              <span className="dashboard-trade-row__chevron" aria-hidden="true">
                <ChevronRightIcon />
              </span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
