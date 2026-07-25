import './NotificationsPanel.css';

interface Notification {
  id: string;
  type: 'price_alert' | 'order_filled' | 'trade_signal' | 'error';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
}

export function NotificationsPanel() {
  const notifications: Notification[] = [
    {
      id: '1',
      type: 'price_alert',
      title: 'BTC Alert',
      message: 'Bitcoin touched $50,000 - your price alert triggered',
      timestamp: new Date(Date.now() - 5 * 60000),
      read: false,
    },
    {
      id: '2',
      type: 'order_filled',
      title: 'Order Filled',
      message: 'Your BTC buy order for 0.5 BTC has been filled',
      timestamp: new Date(Date.now() - 15 * 60000),
      read: false,
    },
    {
      id: '3',
      type: 'trade_signal',
      title: 'Trading Signal',
      message: 'Golden cross detected on ETH/USDT - bullish signal',
      timestamp: new Date(Date.now() - 30 * 60000),
      read: true,
    },
  ];

  const getNotificationIcon = (type: Notification['type']) => {
    switch (type) {
      case 'price_alert':
        return '🔔';
      case 'order_filled':
        return '✅';
      case 'trade_signal':
        return '📊';
      case 'error':
        return '⚠️';
    }
  };

  const formatTime = (date: Date) => {
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);

    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="notifications-list">
      {notifications.map((notif) => (
        <div
          key={notif.id}
          className={`notification-item ${notif.type} ${!notif.read ? 'unread' : ''}`}
        >
          <div className="notification-icon">{getNotificationIcon(notif.type)}</div>
          <div className="notification-content">
            <div className="notification-title">{notif.title}</div>
            <div className="notification-message">{notif.message}</div>
            <div className="notification-time">{formatTime(notif.timestamp)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
