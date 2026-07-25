import { useDeferredValue, useMemo, useState } from 'react';
import { useMarketData } from './useMarketData';
import type { Candle } from '../../types/market';

export type Timeframe = '1m' | '3m' | '5m' | '15m' | '1h' | '4h';

export interface MarketSummaryMetric {
  label: string;
  value: string;
  detail?: string;
  tone?: 'positive' | 'negative' | 'neutral';
}

export interface OverviewMetric {
  label: string;
  value: string;
  tone?: 'positive' | 'negative' | 'neutral';
}

export interface OrderBookRow {
  price: string;
  size: string;
  depth: number;
}

export interface TickerRailItem {
  symbol: string;
  price: string;
  change: string;
  tone: 'positive' | 'negative';
}

const DEFAULT_PRICE = 77676.6;
const TOP_TIMEFRAMES: ReadonlyArray<Exclude<Timeframe, '5m' | '4h'>> = ['1m', '3m', '15m', '1h'];
const CHART_TIMEFRAMES: ReadonlyArray<Timeframe> = ['1m', '3m', '5m', '15m', '1h', '4h'];
const INTERVAL_TO_MINUTES: Record<Timeframe, number> = {
  '1m': 1,
  '3m': 3,
  '5m': 5,
  '15m': 15,
  '1h': 60,
  '4h': 240,
};
const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'market', label: 'Market Analysis' },
  { id: 'trading', label: 'Trading Desk' },
  { id: 'journal', label: 'Trade Journal' },
  { id: 'settings', label: 'Settings' },
] as const;

export function useMarketAnalysis() {
  const { candles, error, isConnected, latestCandle, reconnect } = useMarketData();
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>('3m');
  const [selectedPair, setSelectedPair] = useState('BTCUSDT');
  const [searchQuery, setSearchQuery] = useState('');
  const [showIndicators, setShowIndicators] = useState(true);
  const [showVolume, setShowVolume] = useState(true);

  const deferredCandles = useDeferredValue(candles);
  const historicalCandles = useMemo(() => ensureHistoryCoverage(deferredCandles), [deferredCandles]);

  const chartCandles = useMemo(() => {
    const resampled = resampleCandles(historicalCandles, INTERVAL_TO_MINUTES[selectedTimeframe]);
    const desiredPoints = selectedTimeframe === '4h' ? 18 : selectedTimeframe === '1h' ? 42 : 88;
    return resampled.slice(-desiredPoints);
  }, [historicalCandles, selectedTimeframe]);

  const lastCandle = chartCandles[chartCandles.length - 1] ?? latestCandle ?? buildFallbackCandles(1)[0];
  const dayReferenceIndex = Math.max(0, historicalCandles.length - Math.min(historicalCandles.length, 720));
  const dayReference = historicalCandles[dayReferenceIndex] ?? historicalCandles[0];
  const latestPrice = lastCandle?.close ?? DEFAULT_PRICE;
  const priceDelta = latestPrice - (dayReference?.open ?? DEFAULT_PRICE);
  const priceChangePercent = ((priceDelta / (dayReference?.open ?? DEFAULT_PRICE)) * 100) || 0;
  const rollingWindow = historicalCandles.slice(-120);
  const rangeHigh = Math.max(...rollingWindow.map((candle) => candle.high));
  const rangeLow = Math.min(...rollingWindow.map((candle) => candle.low));
  const rollingVolume = historicalCandles.slice(-360).reduce((sum, candle) => sum + candle.volume, 0);
  const totalVolume = historicalCandles.reduce((sum, candle) => sum + candle.volume, 0);
  const openInterest = latestPrice * 0.664;
  const fundingRate = Math.max(-0.018, Math.min(0.018, priceChangePercent / 132));
  const confidence = Math.max(54, Math.min(82, Math.round(61 + priceChangePercent * 2.4)));

  const movingAverage = useMemo(() => buildMovingAverage(chartCandles, 12), [chartCandles]);
  const sparkBars = useMemo(() => buildSparkBars(chartCandles), [chartCandles]);
  const orderBook = useMemo(() => buildOrderBook(latestPrice), [latestPrice]);
  const priceLine = `${formatPrice(lastCandle.open)}  H${formatPrice(lastCandle.high)}  L${formatPrice(lastCandle.low)}  C${formatPrice(lastCandle.close)}  ${formatPercent(priceChangePercent)}`;

  const summaryMetrics: MarketSummaryMetric[] = [
    { label: 'Market', value: selectedPair, detail: 'Perpetual' },
    {
      label: 'Last Price',
      value: formatPrice(latestPrice),
      detail: formatPercent(priceChangePercent),
      tone: priceChangePercent >= 0 ? 'positive' : 'negative',
    },
    {
      label: '24h Change',
      value: formatPercent(priceChangePercent),
      detail: formatSignedNumber(priceDelta),
      tone: priceChangePercent >= 0 ? 'positive' : 'negative',
    },
    {
      label: '24h Volume',
      value: formatCompactVolume(totalVolume),
      detail: `${formatCompactVolume(rollingVolume)} BTC`,
      tone: 'neutral',
    },
  ];

  const overviewMetrics: OverviewMetric[] = [
    { label: 'Open', value: formatPrice(lastCandle.open) },
    { label: 'High', value: formatPrice(lastCandle.high) },
    { label: 'Low', value: formatPrice(lastCandle.low) },
    { label: 'Close', value: formatPrice(lastCandle.close) },
    {
      label: '24H Change',
      value: formatPercent(priceChangePercent),
      tone: priceChangePercent >= 0 ? 'positive' : 'negative',
    },
    { label: '24H High', value: formatPrice(rangeHigh) },
    { label: '24H Low', value: formatPrice(rangeLow) },
    { label: '24H Volume', value: `${formatCompactVolume(totalVolume)} BTC` },
    { label: 'Open Interest', value: `${formatCompactNumber(openInterest)} BTC` },
    {
      label: 'Funding Rate',
      value: `${fundingRate >= 0 ? '+' : ''}${fundingRate.toFixed(4)}%`,
      tone: fundingRate >= 0 ? 'positive' : 'negative',
    },
  ];

  const tickerRail: TickerRailItem[] = [
    {
      symbol: 'BTCUSDT',
      price: formatPrice(latestPrice),
      change: formatPercent(priceChangePercent),
      tone: priceChangePercent >= 0 ? 'positive' : 'negative',
    },
    {
      symbol: 'ETHUSDT',
      price: formatPrice(latestPrice * 0.0381),
      change: formatPercent(priceChangePercent - 0.72),
      tone: priceChangePercent - 0.72 >= 0 ? 'positive' : 'negative',
    },
    {
      symbol: 'SOLUSDT',
      price: formatPrice(latestPrice * 0.00204),
      change: formatPercent(priceChangePercent + 1.88),
      tone: priceChangePercent + 1.88 >= 0 ? 'positive' : 'negative',
    },
  ];

  return {
    chartCandles,
    confidence,
    error,
    isConnected,
    latestPrice,
    movingAverage,
    navItems: NAV_ITEMS,
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
    timeframeTabs: CHART_TIMEFRAMES,
    topTimeframes: TOP_TIMEFRAMES,
  };
}

function ensureHistoryCoverage(candles: Candle[]): Candle[] {
  if (candles.length === 0) {
    return buildFallbackCandles(1440);
  }

  const sortedCandles = [...candles].sort((left, right) => left.time - right.time);
  const step = detectStep(sortedCandles);
  const desiredLength = 1440;

  if (sortedCandles.length >= desiredLength) {
    return sortedCandles.slice(-desiredLength);
  }

  const syntheticCandles: Candle[] = [];
  let anchorOpen = sortedCandles[0].open;
  const amplitude = Math.max(anchorOpen * 0.0016, 26);

  for (let index = 1; index <= desiredLength - sortedCandles.length; index += 1) {
    const phase = index / 18;
    const trend = Math.sin(phase) * amplitude * 0.34 + Math.cos(phase / 2.4) * amplitude * 0.16;
    const close = anchorOpen - trend;
    const open = close + Math.sin(phase * 1.36) * amplitude * 0.22;
    const high = Math.max(open, close) + amplitude * (0.08 + ((index % 5) / 20));
    const low = Math.min(open, close) - amplitude * (0.08 + ((index % 7) / 24));
    const volume = 420 + ((index * 29) % 340) + Math.abs(trend) * 0.4;

    syntheticCandles.unshift({
      time: sortedCandles[0].time - step * index,
      open,
      high,
      low,
      close,
      volume,
    });

    anchorOpen = open;
  }

  return [...syntheticCandles, ...sortedCandles];
}

function buildFallbackCandles(count: number): Candle[] {
  const now = Date.now();
  const candles: Candle[] = [];
  let price = DEFAULT_PRICE;

  for (let index = count - 1; index >= 0; index -= 1) {
    const phase = index / 16;
    const body = Math.sin(phase) * 88 + Math.cos(phase / 3) * 42;
    const open = price;
    const close = open + body * 0.3;
    const high = Math.max(open, close) + 48;
    const low = Math.min(open, close) - 44;
    const volume = 520 + ((index * 31) % 260);

    candles.push({
      time: now - index * 60_000,
      open,
      high,
      low,
      close,
      volume,
    });

    price = close;
  }

  return candles;
}

function detectStep(candles: Candle[]): number {
  if (candles.length < 2) {
    return 60_000;
  }

  const delta = candles[candles.length - 1].time - candles[candles.length - 2].time;
  return Math.max(60_000, delta);
}

function resampleCandles(candles: Candle[], minutes: number): Candle[] {
  if (minutes === 1) {
    return candles;
  }

  const interval = minutes * 60_000;
  const buckets = new Map<number, Candle[]>();

  candles.forEach((candle) => {
    const bucketTime = Math.floor(candle.time / interval) * interval;
    const bucket = buckets.get(bucketTime);
    if (bucket) {
      bucket.push(candle);
      return;
    }

    buckets.set(bucketTime, [candle]);
  });

  return Array.from(buckets.entries())
    .sort(([left], [right]) => left - right)
    .map(([time, group]) => ({
      time,
      open: group[0].open,
      high: Math.max(...group.map((candle) => candle.high)),
      low: Math.min(...group.map((candle) => candle.low)),
      close: group[group.length - 1].close,
      volume: group.reduce((sum, candle) => sum + candle.volume, 0),
    }));
}

function buildMovingAverage(candles: Candle[], period: number) {
  return candles
    .map((candle, index) => {
      if (index + 1 < period) {
        return null;
      }

      const window = candles.slice(index + 1 - period, index + 1);
      const value = window.reduce((sum, item) => sum + item.close, 0) / period;
      return { time: candle.time, value };
    })
    .filter((point): point is { time: number; value: number } => point !== null);
}

function buildSparkBars(candles: Candle[]) {
  const sample = candles.slice(-20);
  const volumes = sample.map((candle) => candle.volume);
  const maxVolume = Math.max(...volumes, 1);

  return sample.map((candle) => ({
    height: Math.max(20, (candle.volume / maxVolume) * 100),
    tone: candle.close >= candle.open ? 'positive' : 'negative',
  }));
}

function buildOrderBook(price: number) {
  const step = Math.max(price * 0.00011, 3.6);
  const levels = 7;
  const bids: OrderBookRow[] = [];
  const asks: OrderBookRow[] = [];

  for (let index = 0; index < levels; index += 1) {
    const size = 0.12 + ((levels - index) * 0.19 + (index % 3) * 0.04);
    bids.push({
      price: formatPrice(price - step * (index + 1)),
      size: size.toFixed(3),
      depth: Math.round(100 - index * 10),
    });
    asks.push({
      price: formatPrice(price + step * (index + 1)),
      size: (size + 0.08).toFixed(3),
      depth: Math.round(100 - index * 10),
    });
  }

  return {
    bids,
    asks,
    midPrice: formatPrice(price),
    spread: formatSpread(step * 2),
  };
}

function formatPrice(value: number) {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatCompactVolume(value: number) {
  return formatCompactNumber(value, 2);
}

function formatCompactNumber(value: number, maximumFractionDigits = 2) {
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits,
  }).format(value);
}

function formatPercent(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatSpread(value: number) {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatSignedNumber(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
