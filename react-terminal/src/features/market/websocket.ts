/**
 * WebSocket service for real-time market data streaming
 * Connects to FastAPI backend (bybit_ws_backend.py)
 */

import type { Candle, KlineMessage } from '../../types/market';

function getDefaultWebSocketUrl(): string {
  const configuredUrl = import.meta.env.VITE_WS_URL?.trim();
  if (configuredUrl) {
    return configuredUrl;
  }

  if (typeof window === 'undefined') {
    return 'ws://localhost:8000/ws/kline';
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/kline`;
}

export class MarketDataService {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 3000;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();
  private isIntentionallyClosed = false;

  constructor(url?: string) {
    this.url = url || getDefaultWebSocketUrl();
  }

  /**
   * Connect to WebSocket backend
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url);
        this.isIntentionallyClosed = false;

        this.ws.onopen = () => {
          console.log('[MarketDataService] Connected to', this.url);
          this.reconnectAttempts = 0;
          this.emit('connected');
          resolve();
        };

        this.ws.onmessage = (event) => {
          try {
            const message: KlineMessage = JSON.parse(event.data);
            this.emit('kline', message);
          } catch (error) {
            console.error('[MarketDataService] Failed to parse message:', error);
          }
        };

        this.ws.onerror = (error) => {
          console.error('[MarketDataService] WebSocket error:', error);
          this.emit('error', error);
          reject(error);
        };

        this.ws.onclose = () => {
          console.log('[MarketDataService] Disconnected');
          this.emit('disconnected');
          if (!this.isIntentionallyClosed) {
            this.attemptReconnect();
          }
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Disconnect from WebSocket
   */
  disconnect(): void {
    this.isIntentionallyClosed = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.listeners.clear();
    console.log('[MarketDataService] Intentionally disconnected');
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[MarketDataService] Max reconnection attempts reached');
      this.emit('reconnect_failed');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1);
    console.log(
      `[MarketDataService] Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${Math.round(delay)}ms`
    );

    setTimeout(() => {
      this.connect()
        .then(() => {
          console.log('[MarketDataService] Reconnected successfully');
          this.emit('reconnected');
        })
        .catch((error) => {
          console.error('[MarketDataService] Reconnection failed:', error);
        });
    }, delay);
  }

  /**
   * Subscribe to an event
   */
  on(event: string, callback: (data: any) => void): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);

    // Return unsubscribe function
    return () => {
      this.listeners.get(event)?.delete(callback);
    };
  }

  /**
   * Emit an event to all listeners
   */
  private emit(event: string, data?: any): void {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      callbacks.forEach((callback) => {
        try {
          callback(data);
        } catch (error) {
          console.error(`[MarketDataService] Error in listener for '${event}':`, error);
        }
      });
    }
  }

  /**
   * Get connection status
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}

// Singleton instance
let serviceInstance: MarketDataService | null = null;

export function getMarketDataService(): MarketDataService {
  if (!serviceInstance) {
    serviceInstance = new MarketDataService();
  }
  return serviceInstance;
}
