import { useState } from 'react';
import './TradeDesk.css';

type OrderType = 'market' | 'limit';
type Side = 'buy' | 'sell';

export function TradeDesk() {
  const [orderType, setOrderType] = useState<OrderType>('market');
  const [side, setSide] = useState<Side>('buy');
  const [symbol, setSymbol] = useState('BTC/USDT');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');

  const handleSubmitOrder = (e: React.FormEvent) => {
    e.preventDefault();
    // Handle order submission
    console.log({ orderType, side, symbol, quantity, price });
    alert('Order submitted! (Demo mode)');
  };

  return (
    <div className="trade-desk">
      {/* Order Form */}
      <div className="card order-form">
        <h2>Place Order</h2>

        {/* Symbol Selector */}
        <div className="form-group">
          <label>Pair</label>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="form-input">
            <option>BTC/USDT</option>
            <option>ETH/USDT</option>
            <option>SOL/USDT</option>
            <option>XRP/USDT</option>
          </select>
        </div>

        {/* Side Toggle */}
        <div className="form-group">
          <label>Side</label>
          <div className="side-toggle">
            <button
              className={`side-btn buy ${side === 'buy' ? 'active' : ''}`}
              onClick={() => setSide('buy')}
            >
              Buy
            </button>
            <button
              className={`side-btn sell ${side === 'sell' ? 'active' : ''}`}
              onClick={() => setSide('sell')}
            >
              Sell
            </button>
          </div>
        </div>

        {/* Order Type Toggle */}
        <div className="form-group">
          <label>Type</label>
          <div className="order-type-toggle">
            <button
              className={`type-btn ${orderType === 'market' ? 'active' : ''}`}
              onClick={() => setOrderType('market')}
            >
              Market
            </button>
            <button
              className={`type-btn ${orderType === 'limit' ? 'active' : ''}`}
              onClick={() => setOrderType('limit')}
            >
              Limit
            </button>
          </div>
        </div>

        {/* Quantity Input */}
        <div className="form-group">
          <label>Quantity</label>
          <input
            type="number"
            placeholder="Enter quantity"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="form-input"
            step="0.001"
          />
        </div>

        {/* Price Input (Limit Orders Only) */}
        {orderType === 'limit' && (
          <div className="form-group">
            <label>Limit Price</label>
            <input
              type="number"
              placeholder="Enter limit price"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className="form-input"
              step="0.01"
            />
          </div>
        )}

        {/* Submit Button */}
        <button 
          onClick={handleSubmitOrder}
          className={`submit-btn ${side === 'buy' ? 'buy' : 'sell'}`}
        >
          {side === 'buy' ? '🟢' : '🔴'} {side.toUpperCase()} {symbol}
        </button>
      </div>

      {/* Recent Orders */}
      <div className="card recent-orders">
        <h3>Recent Orders</h3>
        <div className="orders-list">
          <div className="order-item">
            <div className="order-header">
              <span className="pair">BTC/USDT</span>
              <span className="status filled">FILLED</span>
            </div>
            <div className="order-details">
              <span>Buy 0.5 @ $49,000</span>
              <span className="time">2 hours ago</span>
            </div>
          </div>
          <div className="order-item">
            <div className="order-header">
              <span className="pair">ETH/USDT</span>
              <span className="status pending">PENDING</span>
            </div>
            <div className="order-details">
              <span>Limit Sell 5 @ $2,050</span>
              <span className="time">30 min ago</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
