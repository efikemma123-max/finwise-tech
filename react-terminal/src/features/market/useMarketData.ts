/**
 * Custom React hook for market data streaming
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { getMarketDataService } from './websocket';
import type { Candle, KlineMessage } from '../../types/market';

export function useMarketData() {
  const serviceRef = useRef(getMarketDataService());
  const [isConnected, setIsConnected] = useState(false);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [latestCandle, setLatestCandle] = useState<Candle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const service = serviceRef.current;

    // Connect to WebSocket
    service.connect().catch((err) => {
      setError(`Connection failed: ${err.message}`);
    });

    // Handle connection state
    const unsubscribeConnected = service.on('connected', () => {
      setIsConnected(true);
      setError(null);
      console.log('Market data connected');
    });

    const unsubscribeDisconnected = service.on('disconnected', () => {
      setIsConnected(false);
      console.log('Market data disconnected');
    });

    const unsubscribeReconnected = service.on('reconnected', () => {
      setIsConnected(true);
      console.log('Market data reconnected');
    });

    // Handle kline data
    const unsubscribeKline = service.on('kline', (message: KlineMessage) => {
      if (message.type === 'history') {
        // Initial history load
        const historyCandles = Array.isArray(message.data) ? message.data : [message.data];
        setCandles(historyCandles);
        if (historyCandles.length > 0) {
          setLatestCandle(historyCandles[historyCandles.length - 1]);
        }
      } else if (message.type === 'update') {
        // Live update
        const updateCandle = Array.isArray(message.data) ? message.data[0] : message.data;
        setCandles((prev) => {
          const updated = [...prev];
          const lastIdx = updated.length - 1;

          // Replace if same timestamp, append if new
          if (lastIdx >= 0 && updated[lastIdx].time === updateCandle.time) {
            updated[lastIdx] = updateCandle;
          } else {
            updated.push(updateCandle);
          }

          // Keep only recent 500 candles in memory
          if (updated.length > 500) {
            updated.shift();
          }

          return updated;
        });
        setLatestCandle(updateCandle);
      }
    });

    // Handle errors
    const unsubscribeError = service.on('error', (err) => {
      setError(`Market data error: ${err.message}`);
    });

    // Cleanup
    return () => {
      unsubscribeConnected();
      unsubscribeDisconnected();
      unsubscribeReconnected();
      unsubscribeKline();
      unsubscribeError();
      service.disconnect();
    };
  }, []);

  const reconnect = useCallback(() => {
    const service = serviceRef.current;
    if (!service.isConnected()) {
      service.connect().catch((err) => {
        setError(`Reconnection failed: ${err.message}`);
      });
    }
  }, []);

  return {
    isConnected,
    candles,
    latestCandle,
    error,
    reconnect,
  };
}
