export type CurrencyCode = 'USD' | 'EUR' | 'GBP';
export type ChartRange = '1H' | '1D' | '1W' | '1M' | '1Y' | 'All';
export type BottomTab = 'home' | 'markets' | 'trade' | 'portfolio' | 'settings';
export type QuickActionId = 'deposit' | 'withdraw' | 'trade' | 'convert';

export interface PortfolioPoint {
  label: string;
  value: number;
}

export interface PortfolioRangeSet {
  range: ChartRange;
  points: PortfolioPoint[];
}

export interface MarketCardData {
  pair: string;
  price: number;
  changePct: number;
  sparkline: number[];
}

export interface AIInsightData {
  confidence: number;
  signal: 'BUY' | 'SELL' | 'HOLD';
  badge: string;
  description: string;
  analysisAge: string;
}

export interface QuickActionData {
  id: QuickActionId;
  label: string;
}
