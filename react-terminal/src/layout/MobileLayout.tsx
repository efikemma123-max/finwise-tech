import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import './MobileLayout.css';
import { Dashboard } from '../features/dashboard/Dashboard';
import { TradeDesk } from '../features/trade/TradeDesk';
import { BellIcon, NavIcon } from '../features/market/MarketIcons';
import { SavedSessionGate } from '../features/auth/SavedSessionGate';

type ViewType = 'dashboard' | 'market' | 'trade' | 'copilot';

const MarketAnalysisScreen = lazy(() =>
  import('../features/market/MarketAnalysisScreen').then((module) => ({
    default: module.MarketAnalysisScreen,
  })),
);
const CopilotChat = lazy(() =>
  import('../features/copilot/CopilotChat').then((module) => ({
    default: module.CopilotChat,
  })),
);
const NotificationsPanel = lazy(() =>
  import('../features/notifications/NotificationsPanel').then((module) => ({
    default: module.NotificationsPanel,
  })),
);

const FALLBACK_USERNAME = 'Efikemma';
const SAVED_SESSION_KEY = 'finwise.mobileSavedSession';

const NAV_ITEMS: Array<{ id: ViewType | 'alerts'; label: string; iconId?: string; badge?: number }> = [
  { id: 'dashboard', label: 'Dashboard', iconId: 'dashboard' },
  { id: 'market', label: 'Markets', iconId: 'market' },
  { id: 'trade', label: 'Trade', iconId: 'trading' },
  { id: 'copilot', label: 'Copilot', iconId: 'journal' },
  { id: 'alerts', label: 'Alerts', badge: 3 },
];

export function MobileLayout() {
  const [activeView, setActiveView] = useState<ViewType>('dashboard');
  const [showNotifications, setShowNotifications] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [savedUsername, setSavedUsername] = useState(FALLBACK_USERNAME);

  useEffect(() => {
    try {
      const rawSession = window.localStorage.getItem(SAVED_SESSION_KEY);
      if (!rawSession) {
        return;
      }

      const parsedSession = JSON.parse(rawSession) as { username?: string; authenticated?: boolean };
      const username = String(parsedSession.username ?? '').trim();

      if (username) {
        setSavedUsername(username);
      }

      if (parsedSession.authenticated) {
        setIsAuthenticated(true);
      }
    } catch {
      window.localStorage.removeItem(SAVED_SESSION_KEY);
    }
  }, []);

  function handleContinueSession(username: string) {
    const normalizedUsername = username.trim() || FALLBACK_USERNAME;

    setSavedUsername(normalizedUsername);
    setIsAuthenticated(true);
    window.localStorage.setItem(
      SAVED_SESSION_KEY,
      JSON.stringify({ username: normalizedUsername, authenticated: true }),
    );
  }

  const activeScreen = useMemo(() => {
    if (activeView === 'dashboard') {
      return (
        <Dashboard
          displayName={savedUsername}
          onOpenNotifications={() => setShowNotifications(true)}
          onSelectMarket={() => setActiveView('market')}
        />
      );
    }

    if (activeView === 'market') {
      return (
        <Suspense fallback={<ScreenLoading label="Loading markets" />}>
          <MarketAnalysisScreen />
        </Suspense>
      );
    }

    if (activeView === 'trade') {
      return (
        <section className="mobile-panel-screen">
          <div className="mobile-panel-screen__intro">
            <span className="mobile-panel-screen__eyebrow">Execution</span>
            <h1>Trading Desk</h1>
            <p>Place orders, manage direction, and keep recent fills in one mobile-first workspace.</p>
          </div>
          <TradeDesk />
        </section>
      );
    }

    return (
      <section className="mobile-panel-screen mobile-panel-screen--chat">
        <div className="mobile-panel-screen__intro">
          <span className="mobile-panel-screen__eyebrow">Assistant</span>
          <h1>Finwise Copilot</h1>
          <p>Ask for market context, trade ideas, and portfolio guidance without leaving the terminal.</p>
        </div>
        <Suspense fallback={<ScreenLoading label="Loading copilot" />}>
          <CopilotChat />
        </Suspense>
      </section>
    );
  }, [activeView, savedUsername]);

  const shouldShowAuthGate = !isAuthenticated;

  return (
    <div className="app-shell market-app mobile-app-shell">
      <div className="market-app__backdrop market-app__backdrop--top" />
      <div className="market-app__backdrop market-app__backdrop--bottom" />

      <div className="mobile-app-frame">
        <div className="mobile-screen">
          {shouldShowAuthGate ? <SavedSessionGate username={savedUsername} onContinue={handleContinueSession} /> : activeScreen}
        </div>

        {shouldShowAuthGate ? null : (
          <nav className="glass-card mobile-bottom-nav" aria-label="Primary navigation">
            {NAV_ITEMS.map((item) => {
              const isAlerts = item.id === 'alerts';
              const isActive = item.id === activeView;

              return (
                <button
                  key={item.id}
                  className={`mobile-bottom-nav__item ${isActive ? 'mobile-bottom-nav__item--active' : ''}`}
                  type="button"
                  aria-current={isActive ? 'page' : undefined}
                  onClick={() => {
                    if (isAlerts) {
                      setShowNotifications(true);
                      return;
                    }

                    if (item.id !== 'alerts') {
                      setActiveView(item.id);
                    }
                  }}
                >
                  <span className="mobile-bottom-nav__icon">
                    {isAlerts ? <BellIcon /> : <NavIcon id={item.iconId ?? 'dashboard'} />}
                    {item.badge ? <span className="mobile-bottom-nav__badge">{item.badge}</span> : null}
                  </span>
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>

      {showNotifications && !shouldShowAuthGate ? (
        <div className="notifications-overlay" onClick={() => setShowNotifications(false)}>
          <aside className="notifications-panel glass-card" onClick={(event) => event.stopPropagation()}>
            <div className="notifications-header">
              <div>
                <span className="notifications-header__eyebrow">Inbox</span>
                <h3>Notifications</h3>
              </div>
              <button type="button" onClick={() => setShowNotifications(false)} aria-label="Close notifications">
                Close
              </button>
            </div>
            <Suspense fallback={<ScreenLoading label="Loading alerts" />}>
              <NotificationsPanel />
            </Suspense>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function ScreenLoading({ label }: { label: string }) {
  return (
    <div className="mobile-screen-loading" role="status" aria-live="polite">
      <span className="mobile-screen-loading__spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
