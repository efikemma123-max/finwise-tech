/**
 * Market data types for Finwise trading terminal
 */

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartSeries {
  time: number;
  value: number;
}

export interface KlineMessage {
  type: 'history' | 'update';
  data: Candle | Candle[];
}

export interface IndicatorSeries {
  name: string;
  type: 'line' | 'histogram';
  color: string;
  data: ChartSeries[];
  width?: number;
}

export interface IndicatorConfig {
  moving_averages: {
    enabled: boolean;
    ema: number[];
    sma: number[];
  };
  rsi: {
    enabled: boolean;
    period?: number;
  };
  macd: {
    enabled: boolean;
    fast?: number;
    slow?: number;
    signal?: number;
  };
  bollinger_bands?: {
    enabled: boolean;
    period?: number;
    std_dev?: number;
  };
}

export interface OrderBookLevel {
  price: number;
  size: number;
}

export interface OrderBook {
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  timestamp: number;
}

export interface Trade {
  id: string;
  price: number;
  quantity: number;
  side: 'buy' | 'sell';
  timestamp: number;
}
