import { startTransition, useState } from 'react';
import { useMarketAnalysis, type Timeframe } from './useMarketAnalysis';
import { MarketChart } from './MarketChart';
import {
  BarsIcon,
  ChevronDownIcon,
  DrawIcon,
  ExpandIcon,
  GearIcon,
  LogoMark,
  MenuIcon,
  RobotIcon,
  SearchIcon,
  WarningIcon,
  WaveIcon,
} from './MarketIcons';

export function MarketAnalysisScreen() {
  const [showToolPanel, setShowToolPanel] = useState(true);
  const [showBands, setShowBands] = useState(true);
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(false);
  const [activeDrawingTool, setActiveDrawingTool] = useState<'trend' | 'levels' | 'fib' | 'measure'>('trend');

  const {
    chartCandles,
    confidence,
    error,
    isConnected,
    movingAverage,
    orderBook,
    overviewMetrics,
    priceChangePercent,
    priceLine,
    rangeHigh,
    rangeLow,
    reconnect,
    searchQuery,
    selectedPair,
    selectedTimeframe,
    setSearchQuery,
    setSelectedPair,
    setSelectedTimeframe,
    showIndicators,
    setShowIndicators,
    showVolume,
    setShowVolume,
    sparkBars,
    summaryMetrics,
    tickerRail,
    timeframeTabs,
    topTimeframes,
  } = useMarketAnalysis();

  const signalTone =
    Math.abs(priceChangePercent) > 2.3 ? (priceChangePercent > 0 ? 'Bullish' : 'Bearish') : 'Neutral';

  return (
    <div className="market-screen">
        <header className="market-header">
          <button className="icon-chip" type="button" aria-label="Open menu">
            <MenuIcon />
          </button>

          <div className="market-header__brand">
            <div className="market-header__logo">
              <LogoMark />
            </div>
            <p className="market-header__eyebrow">Finwise AI</p>
          </div>

          <div className="market-header__actions">
            <div className={`live-pill ${isConnected ? 'live-pill--connected' : 'live-pill--disconnected'}`}>
              <span className="live-pill__dot" />
              <span>{isConnected ? 'Live Feed' : 'Reconnect'}</span>
            </div>
            <button className="icon-chip" type="button" aria-label="Settings">
              <GearIcon />
            </button>
          </div>
        </header>

        <section className="page-heading">
          <div>
            <h1>Market Analysis</h1>
            <p>Live chart, depth, and execution levels for your selected market.</p>
          </div>
        </section>

        <section className="filter-grid">
          <label className="field-card field-card--search">
            <span className="field-card__label">Search pair</span>
            <div className="field-card__control">
              <SearchIcon />
              <input
                aria-label="Search trading pairs"
                placeholder="Search 50+ pairs (BTC, ETH, USDC...)"
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
          </label>

          <label className="field-card">
            <span className="field-card__label">Trading pair</span>
            <div className="field-card__control field-card__control--select">
              <select
                aria-label="Select trading pair"
                value={selectedPair}
                onChange={(event) => setSelectedPair(event.target.value)}
              >
                <option value="BTCUSDT">BTCUSDT</option>
              </select>
              <ChevronDownIcon />
            </div>
          </label>

          <div className="field-card field-card--timeframe">
            <span className="field-card__label">Timeframe</span>
            <div className="timeframe-pills timeframe-pills--compact">
              {topTimeframes.map((frame) => (
                <button
                  key={frame}
                  className={`timeframe-pill ${selectedTimeframe === frame ? 'timeframe-pill--active' : ''}`}
                  type="button"
                  onClick={() => handleTimeframeChange(frame, setSelectedTimeframe)}
                >
                  {frame}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="glass-card market-summary-card">
          <div className="market-summary-card__metrics">
            {summaryMetrics.map((metric) => (
              <article key={metric.label} className="summary-stat">
                <span className="summary-stat__label">{metric.label}</span>
                <strong className={`summary-stat__value summary-stat__value--${metric.tone ?? 'neutral'}`}>
                  {metric.value}
                </strong>
                {metric.detail ? (
                  <span className={`summary-stat__detail summary-stat__detail--${metric.tone ?? 'neutral'}`}>
                    {metric.detail}
                  </span>
                ) : null}
              </article>
            ))}
          </div>

          <div className="market-summary-card__spark">
            <span className="summary-stat__label">Activity</span>
            <div className="spark-bars" aria-hidden="true">
              {sparkBars.map((bar, index) => (
                <span
                  key={`${bar.height}-${index}`}
                  className={`spark-bars__bar spark-bars__bar--${bar.tone}`}
                  style={{ height: `${bar.height}%` }}
                />
              ))}
            </div>
          </div>
        </section>

        <section className="glass-card chart-card">
          <div className="chart-card__header">
            <div>
              <div className="chart-card__title-row">
                <h2>{selectedPair} Perpetual</h2>
                <span className="chart-card__dot" />
                <span className="chart-card__timeframe">{selectedTimeframe}</span>
              </div>
              <p className={`chart-card__ohlc ${priceChangePercent >= 0 ? 'chart-card__ohlc--positive' : 'chart-card__ohlc--negative'}`}>
                {priceLine}
              </p>
            </div>
            <div className="chart-card__live-badge">
              <span className="chart-card__live-dot" />
              Live
            </div>
          </div>

          <div className="chart-card__body">
            <MarketChart
              candles={chartCandles}
              movingAverage={movingAverage}
              showIndicators={showIndicators}
              showVolume={showVolume}
            />
            <div className="chart-card__watermark">TV</div>
          </div>

          <div className="chart-toolbar">
            <div className="chart-toolbar__top">
              <div className="timeframe-pills">
                {timeframeTabs.map((frame) => (
                  <button
                    key={frame}
                    className={`timeframe-pill ${selectedTimeframe === frame ? 'timeframe-pill--active' : ''}`}
                    type="button"
                    onClick={() => handleTimeframeChange(frame, setSelectedTimeframe)}
                  >
                    {frame}
                  </button>
                ))}
              </div>

              <div className="chart-toolbar__actions">
                <button
                  className={`toolbar-chip ${showIndicators ? 'toolbar-chip--active' : ''}`}
                  type="button"
                  onClick={() => setShowIndicators((current) => !current)}
                >
                  <WaveIcon />
                  Indicators
                </button>
                <button
                  className={`toolbar-chip ${showToolPanel ? 'toolbar-chip--active' : ''}`}
                  type="button"
                  onClick={() => setShowToolPanel((current) => !current)}
                >
                  <DrawIcon />
                  Drawing Tools
                </button>
                <button
                  className={`icon-chip icon-chip--toolbar ${showVolume ? 'icon-chip--active' : ''}`}
                  type="button"
                  aria-label="Toggle volume bars"
                  onClick={() => setShowVolume((current) => !current)}
                >
                  <BarsIcon />
                </button>
                <button className="icon-chip icon-chip--toolbar" type="button" aria-label="Expand chart">
                  <ExpandIcon />
                </button>
                <button className="icon-chip icon-chip--toolbar" type="button" aria-label="Chart settings">
                  <GearIcon />
                </button>
              </div>
            </div>

            {showToolPanel ? (
              <div className="chart-tools-panel">
                <div className="chart-tools-panel__group">
                  <span className="chart-tools-panel__label">Indicators</span>
                  <div className="chart-tools-panel__pills">
                    <button
                      className={`chart-tools-pill ${showIndicators ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setShowIndicators((current) => !current)}
                    >
                      EMA 20 / 50
                    </button>
                    <button
                      className={`chart-tools-pill ${showBands ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setShowBands((current) => !current)}
                    >
                      Bollinger Bands
                    </button>
                    <button
                      className={`chart-tools-pill ${showRsi ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setShowRsi((current) => !current)}
                    >
                      RSI 14
                    </button>
                    <button
                      className={`chart-tools-pill ${showMacd ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setShowMacd((current) => !current)}
                    >
                      MACD
                    </button>
                  </div>
                </div>

                <div className="chart-tools-panel__group">
                  <span className="chart-tools-panel__label">Drawing Tools</span>
                  <div className="chart-tools-panel__pills">
                    <button
                      className={`chart-tools-pill ${activeDrawingTool === 'trend' ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setActiveDrawingTool('trend')}
                    >
                      Trend Line
                    </button>
                    <button
                      className={`chart-tools-pill ${activeDrawingTool === 'levels' ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setActiveDrawingTool('levels')}
                    >
                      Key Levels
                    </button>
                    <button
                      className={`chart-tools-pill ${activeDrawingTool === 'fib' ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setActiveDrawingTool('fib')}
                    >
                      Fibonacci
                    </button>
                    <button
                      className={`chart-tools-pill ${activeDrawingTool === 'measure' ? 'chart-tools-pill--active' : ''}`}
                      type="button"
                      onClick={() => setActiveDrawingTool('measure')}
                    >
                      Measure
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="glass-card orderbook-card">
          <div className="section-title-row">
            <h3>Order Book</h3>
            <span className="section-title-row__meta">Depth</span>
          </div>

          <div className="orderbook-card__mid">
            <strong>{orderBook.midPrice}</strong>
            <span>Mid Price</span>
            <span>Spread {orderBook.spread}</span>
          </div>

          <div className="orderbook-card__columns">
            <div className="orderbook-column">
              <div className="orderbook-column__head">
                <span>Bids</span>
                <span>Size</span>
              </div>
              {orderBook.bids.map((row) => (
                <div key={`bid-${row.price}`} className="orderbook-row orderbook-row--bid">
                  <span className="orderbook-row__depth" style={{ width: `${row.depth}%` }} />
                  <strong>{row.price}</strong>
                  <span>{row.size}</span>
                </div>
              ))}
            </div>

            <div className="orderbook-column">
              <div className="orderbook-column__head orderbook-column__head--ask">
                <span>Asks</span>
                <span>Size</span>
              </div>
              {orderBook.asks.map((row) => (
                <div key={`ask-${row.price}`} className="orderbook-row orderbook-row--ask">
                  <span className="orderbook-row__depth" style={{ width: `${row.depth}%` }} />
                  <strong>{row.price}</strong>
                  <span>{row.size}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="glass-card overview-card">
          <div className="section-title-row">
            <h3>Market Overview</h3>
          </div>
          <div className="overview-grid">
            {overviewMetrics.map((metric) => (
              <article key={metric.label} className="overview-grid__item">
                <span>{metric.label}</span>
                <strong className={`overview-grid__value overview-grid__value--${metric.tone ?? 'neutral'}`}>
                  {metric.value}
                </strong>
              </article>
            ))}
          </div>
        </section>

        <section className="glass-card signal-card">
          <div className="section-title-row">
            <h3>AI Signal</h3>
            <span className="signal-chip">3/6 used today</span>
          </div>

          <div className="signal-card__content">
            <div className="signal-avatar">
              <div className="signal-avatar__core">
                <RobotIcon />
              </div>
            </div>

            <div className="signal-card__details">
              <div className="signal-card__topline">
                <div>
                  <span className="signal-card__label">Status</span>
                  <strong className={`signal-card__status signal-card__status--${signalTone.toLowerCase()}`}>
                    {signalTone.toUpperCase()}
                  </strong>
                </div>
                <div className="signal-card__confidence">
                  <div className="signal-card__confidence-row">
                    <span>Confidence</span>
                    <strong>{confidence}%</strong>
                  </div>
                  <div className="signal-card__meter">
                    <span style={{ width: `${confidence}%` }} />
                  </div>
                </div>
              </div>

              <p className="signal-card__analysis">
                Price is consolidating near key levels. Wait for breakout confirmation before increasing size.
              </p>

              <div className="signal-card__levels">
                <div>
                  <span>Support</span>
                  <strong>{formatScreenPrice(rangeLow)}</strong>
                </div>
                <div>
                  <span>Resistance</span>
                  <strong>{formatScreenPrice(rangeHigh)}</strong>
                </div>
              </div>

              <button className="signal-card__cta" type="button">
                Get AI Signal
              </button>
            </div>
          </div>
        </section>

        <section className="glass-card upgrade-card">
          <div>
            <strong>Unlock Full Potential</strong>
            <p>Upgrade for premium AI signals, backtesting, and more.</p>
          </div>
          <button className="upgrade-card__cta" type="button">
            Upgrade Now
          </button>
        </section>

        <section className="ticker-rail">
          {tickerRail.map((item) => (
            <article key={item.symbol} className="ticker-rail__item">
              <span className="ticker-rail__symbol">{item.symbol}</span>
              <strong>{item.price}</strong>
              <span className={`ticker-rail__change ticker-rail__change--${item.tone}`}>{item.change}</span>
            </article>
          ))}
        </section>

        {error ? (
          <button className="connection-banner" type="button" onClick={reconnect}>
            <WarningIcon />
            <span>{error}</span>
          </button>
        ) : null}
    </div>
  );
}

function handleTimeframeChange(
  frame: Timeframe,
  setSelectedTimeframe: (value: Timeframe) => void
) {
  startTransition(() => setSelectedTimeframe(frame));
}

function formatScreenPrice(value: number) {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
