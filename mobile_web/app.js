const query = new URLSearchParams(window.location.search);
const MOBILE_PROXY_PREFIX = "/mobile-api";
const AUTO_SIGNAL_PERMISSION_KEY = "finwise-mobile-auto-signal-permission";
const AUTO_SIGNAL_SENT_KEY_PREFIX = "finwise-mobile-auto-signal-sent-v2";
const AUTO_SIGNAL_PERMISSION_COPY =
  "Allow Finwise to send the latest AI signal to your saved Telegram route automatically when your connection is online?";

function readStoredValue(key, fallback = "") {
  try {
    const value = localStorage.getItem(key);
    return value || fallback;
  } catch (error) {
    console.debug(error);
    return fallback;
  }
}

function writeStoredValue(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (error) {
    console.debug(error);
  }
}

function removeStoredValue(key) {
  try {
    localStorage.removeItem(key);
  } catch (error) {
    console.debug(error);
  }
}

const state = {
  page: query.get("page") || "markets",
  authPanel: query.get("auth") || "login",
  session: null,
  usage: null,
  broker: null,
  notifications: null,
  symbols: [],
  timeframes: [],
  symbol: query.get("symbol") || readStoredValue("finwise-mobile-symbol", "BTCUSDT"),
  interval: query.get("interval") || readStoredValue("finwise-mobile-interval", "5m"),
  tradeStyle: query.get("tradeStyle") || readStoredValue("finwise-mobile-trade-style", "day_trade"),
  chartIndicator: query.get("indicator") || readStoredValue("finwise-mobile-indicator", "EMA"),
  chart: null,
  candleSeries: null,
  volumeSeries: null,
  fastLineSeries: null,
  slowLineSeries: null,
  bollUpperSeries: null,
  bollMiddleSeries: null,
  bollLowerSeries: null,
  sarSeries: null,
  liveTimer: null,
  registerPending: false,
  resetPending: false,
  journalStatus: "all",
  marketView: "market-chart-section",
  homePeriod: query.get("homePeriod") || readStoredValue("finwise-mobile-home-period", "24H"),
  lastCandles: [],
  lastSignal: null,
  tickerSnapshots: {},
  autoSignalInFlight: false,
  autoSignalTimer: null,
  requestSeq: {
    home: 0,
    markets: 0,
    desk: 0,
    journal: 0,
    settings: 0,
  },
};

const els = {
  authView: document.getElementById("auth-view"),
  appView: document.getElementById("app-view"),
  authGlobalMessage: document.getElementById("auth-global-message"),
  authSwitches: [...document.querySelectorAll("[data-auth-panel]")],
  loginForm: document.getElementById("login-form"),
  registerForm: document.getElementById("register-form"),
  resetForm: document.getElementById("reset-form"),
  loginUsername: document.getElementById("login-username"),
  loginPassword: document.getElementById("login-password"),
  loginRemember: document.getElementById("login-remember"),
  registerUsername: document.getElementById("register-username"),
  registerEmail: document.getElementById("register-email"),
  registerPhone: document.getElementById("register-phone"),
  registerPassword: document.getElementById("register-password"),
  registerOtp: document.getElementById("register-otp"),
  registerOtpBlock: document.getElementById("register-otp-block"),
  registerSubmit: document.getElementById("register-submit"),
  registerRemember: document.getElementById("register-remember"),
  registerStageBanner: document.getElementById("register-stage-banner"),
  resetUsername: document.getElementById("reset-username"),
  resetEmail: document.getElementById("reset-email"),
  resetOtp: document.getElementById("reset-otp"),
  resetPassword: document.getElementById("reset-password"),
  resetOtpBlock: document.getElementById("reset-otp-block"),
  resetSubmit: document.getElementById("reset-submit"),
  resetRemember: document.getElementById("reset-remember"),
  resetStageBanner: document.getElementById("reset-stage-banner"),
  sessionUsername: document.getElementById("session-username"),
  sessionPlan: document.getElementById("session-plan"),
  sessionSignalsLeft: document.getElementById("session-signals-left"),
  sessionBrokerStatus: document.getElementById("session-broker-status"),
  headerLivePill: document.getElementById("header-live-pill"),
  navItems: [...document.querySelectorAll("[data-page-target]")],
  pages: [...document.querySelectorAll("[data-page]")],
  homeSearch: document.getElementById("home-search"),
  homeFilterButton: document.getElementById("home-filter-button"),
  homeNotificationButton: document.getElementById("home-notification-button"),
  homeProfileButton: document.getElementById("home-profile-button"),
  homeAvatarInitials: document.getElementById("home-avatar-initials"),
  homeRefresh: document.getElementById("home-refresh"),
  homeMetrics: document.getElementById("home-metrics"),
  homeBrokerCard: document.getElementById("home-broker-card"),
  homeRecentTrades: document.getElementById("home-recent-trades"),
  homeSyncTitle: document.getElementById("home-sync-title"),
  homeSyncMessage: document.getElementById("home-sync-message"),
  homeSyncPill: document.getElementById("home-sync-pill"),
  homePeriodSelect: document.getElementById("home-period-select"),
  homeProfitTotal: document.getElementById("home-profit-total"),
  homeProfitDelta: document.getElementById("home-profit-delta"),
  homeLossTotal: document.getElementById("home-loss-total"),
  homeLossDelta: document.getElementById("home-loss-delta"),
  homeNetTotal: document.getElementById("home-net-total"),
  homeWinRate: document.getElementById("home-win-rate"),
  homeWinCount: document.getElementById("home-win-count"),
  homeWinRingProgress: document.getElementById("home-win-ring-progress"),
  homeProfitSparkline: document.getElementById("home-profit-sparkline"),
  homeLossSparkline: document.getElementById("home-loss-sparkline"),
  homeHistoryList: document.getElementById("home-history-list"),
  marketSearch: document.getElementById("market-search"),
  marketSearchShell: document.getElementById("market-search-shell"),
  marketSearchToggle: document.getElementById("market-search-toggle"),
  marketSymbol: document.getElementById("market-symbol"),
  marketInterval: document.getElementById("market-interval"),
  marketTimeframePills: document.getElementById("market-timeframe-pills"),
  marketChartTimeframes: document.getElementById("market-chart-timeframes"),
  marketViewTabs: [...document.querySelectorAll(".market-view-tab")],
  marketIndicatorButtons: [...document.querySelectorAll("[data-market-indicator]")],
  marketSummarySymbol: document.getElementById("market-summary-symbol"),
  marketSummaryType: document.getElementById("market-summary-type"),
  marketSummaryLastPrice: document.getElementById("market-summary-last-price"),
  marketSummaryLastChange: document.getElementById("market-summary-last-change"),
  marketSummaryDayChange: document.getElementById("market-summary-day-change"),
  marketSummaryNotionalChange: document.getElementById("market-summary-notional-change"),
  marketSummaryVolume: document.getElementById("market-summary-volume"),
  marketSummaryVolumeAsset: document.getElementById("market-summary-volume-asset"),
  marketSummaryBars: document.getElementById("market-summary-bars"),
  marketHeadlineUsd: document.getElementById("market-headline-usd"),
  marketCompactHigh: document.getElementById("market-compact-high"),
  marketCompactLow: document.getElementById("market-compact-low"),
  marketCompactTurnover: document.getElementById("market-compact-turnover"),
  marketFeedBanner: document.getElementById("market-feed-banner"),
  marketChartTitle: document.getElementById("market-chart-title"),
  marketChartOhlc: document.getElementById("market-chart-ohlc"),
  marketLiveStatus: document.getElementById("market-live-status"),
  marketIndicatorToggle: document.getElementById("market-indicator-toggle"),
  marketIndicatorDrawer: document.getElementById("market-indicator-drawer"),
  marketIndicatorLegend: document.getElementById("market-indicator-legend"),
  marketChartRoot: document.getElementById("market-chart-root"),
  marketStats: document.getElementById("market-stats"),
  marketBidRatioLabel: document.getElementById("market-bid-ratio-label"),
  marketBidRatioBar: document.getElementById("market-bid-ratio-bar"),
  marketAskRatioLabel: document.getElementById("market-ask-ratio-label"),
  marketAskRatioBar: document.getElementById("market-ask-ratio-bar"),
  marketMidPriceMain: document.getElementById("market-mid-price-main"),
  marketSpread: document.getElementById("market-spread"),
  marketMid: document.getElementById("market-mid"),
  marketDepthTable: document.getElementById("market-depth-table"),
  marketSignalUsage: document.getElementById("market-signal-usage"),
  marketSignalSide: document.getElementById("market-signal-side"),
  marketSignalConfidence: document.getElementById("market-signal-confidence"),
  marketSignalConfidenceBar: document.getElementById("market-signal-confidence-bar"),
  marketSignalAnalysis: document.getElementById("market-signal-analysis"),
  marketSignalLevels: document.getElementById("market-signal-levels"),
  marketSignalSupport: document.getElementById("market-signal-support"),
  marketSignalResistance: document.getElementById("market-signal-resistance"),
  marketSignalButton: document.getElementById("market-signal-button"),
  marketTickerRail: document.getElementById("market-ticker-rail"),
  marketBuyPrice: document.getElementById("market-buy-price"),
  marketSellPrice: document.getElementById("market-sell-price"),
  marketTradeCenterTitle: document.getElementById("market-trade-center-title"),
  marketTradeCenterBase: document.getElementById("market-trade-center-base"),
  deskRefresh: document.getElementById("desk-refresh"),
  deskSummary: document.getElementById("desk-summary"),
  deskBalance: document.getElementById("desk-balance"),
  deskTradeStyle: document.getElementById("desk-trade-style"),
  deskSignalButton: document.getElementById("desk-signal-button"),
  deskBrokerCard: document.getElementById("desk-broker-card"),
  deskSignalEmpty: document.getElementById("desk-signal-empty"),
  deskSignalCard: document.getElementById("desk-signal-card"),
  journalFilters: [...document.querySelectorAll("[data-journal-status]")],
  journalMetrics: document.getElementById("journal-metrics"),
  journalList: document.getElementById("journal-list"),
  settingsAccount: document.getElementById("settings-account"),
  settingsNotificationForm: document.getElementById("settings-notification-form"),
  settingsPhone: document.getElementById("settings-phone"),
  settingsTelegramCard: document.getElementById("settings-telegram-card"),
  settingsTelegramCopy: document.getElementById("settings-telegram-copy"),
  settingsTelegramStatus: document.getElementById("settings-telegram-status"),
  settingsTelegramOpen: document.getElementById("settings-telegram-open"),
  settingsTelegramFinish: document.getElementById("settings-telegram-finish"),
  settingsTelegramChatId: document.getElementById("settings-telegram-chat-id"),
  settingsWhatsappEnabled: document.getElementById("settings-whatsapp-enabled"),
  settingsTelegramEnabled: document.getElementById("settings-telegram-enabled"),
  settingsPreferencesForm: document.getElementById("settings-preferences-form"),
  prefBuySignals: document.getElementById("pref-buy-signals"),
  prefSellSignals: document.getElementById("pref-sell-signals"),
  prefSignalUpdates: document.getElementById("pref-signal-updates"),
  prefHighConfidence: document.getElementById("pref-high-confidence"),
  prefMarketDigest: document.getElementById("pref-market-digest"),
  prefAuthenticator: document.getElementById("pref-authenticator"),
  prefSmsVerification: document.getElementById("pref-sms-verification"),
  prefLoginAlerts: document.getElementById("pref-login-alerts"),
  settingsPasswordForm: document.getElementById("settings-password-form"),
  settingsCurrentPassword: document.getElementById("settings-current-password"),
  settingsNewPassword: document.getElementById("settings-new-password"),
  settingsConfirmPassword: document.getElementById("settings-confirm-password"),
  settingsSecurity: document.getElementById("settings-security"),
  logoutButton: document.getElementById("logout-button"),
  toast: document.getElementById("toast"),
};

function setHidden(element, hidden) {
  element.classList.toggle("hidden", hidden);
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const numeric = Number(value) * (Math.abs(Number(value)) <= 1 ? 100 : 1);
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(2)}%`;
}

function formatConfidence(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(0)}%`;
}

function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatSignedNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const numeric = Number(value);
  return `${numeric >= 0 ? "+" : ""}${formatNumber(numeric, digits)}`;
}

function formatRate(value, digits = 4) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const numeric = Math.abs(Number(value)) <= 1 ? Number(value) * 100 : Number(value);
  return `${numeric >= 0 ? "+" : ""}${numeric.toFixed(digits)}%`;
}

const customSelectRegistry = new Map();

function closeCustomSelects(exceptId = "") {
  customSelectRegistry.forEach((entry, selectId) => {
    if (selectId === exceptId) return;
    entry.host.classList.remove("is-open");
    entry.control.setAttribute("aria-expanded", "false");
    entry.menu.hidden = true;
  });
}

function refreshCustomSelect(select) {
  if (!select) return;
  const entry = customSelectRegistry.get(select.id);
  if (entry) {
    entry.refresh();
  }
}

function enhanceCustomSelect(select) {
  if (!select || !select.id) return;
  if (customSelectRegistry.has(select.id)) {
    refreshCustomSelect(select);
    return;
  }

  const host = select.parentElement;
  if (!host) return;

  host.classList.add("custom-select-host", "is-enhanced");
  select.classList.add("custom-select-native");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const control = document.createElement("button");
  control.type = "button";
  control.className = "custom-select-control";
  control.setAttribute("aria-haspopup", "listbox");
  control.setAttribute("aria-expanded", "false");
  control.innerHTML = `
    <span class="custom-select-control__label"></span>
    <span class="custom-select-control__icon" aria-hidden="true"></span>
  `;

  const menu = document.createElement("div");
  menu.className = "custom-select-menu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;

  host.append(control, menu);

  const refresh = () => {
    const options = [...select.options].map((option) => ({
      value: option.value,
      label: option.textContent || option.value,
      selected: option.selected,
      disabled: option.disabled,
    }));
    const selectedOption =
      options.find((option) => option.value === select.value)
      || options.find((option) => option.selected)
      || options[0]
      || null;
    const label = control.querySelector(".custom-select-control__label");

    if (label) {
      label.textContent = selectedOption?.label || select.dataset.placeholder || "Select an option";
    }

    if (!selectedOption) {
      menu.innerHTML = `<div class="custom-select-empty">No options available yet.</div>`;
      control.disabled = true;
      host.classList.add("is-disabled");
      return;
    }

    if (select.value !== selectedOption.value) {
      select.value = selectedOption.value;
    }

    control.disabled = Boolean(select.disabled);
    host.classList.toggle("is-disabled", Boolean(select.disabled));
    menu.innerHTML = options
      .map(
        (option) => `
          <button
            type="button"
            class="custom-select-option ${option.value === selectedOption.value ? "is-selected" : ""}"
            data-custom-select-value="${escapeHtml(option.value)}"
            role="option"
            aria-selected="${option.value === selectedOption.value ? "true" : "false"}"
            ${option.disabled ? "disabled" : ""}
          >
            ${escapeHtml(option.label)}
          </button>
        `,
      )
      .join("");
  };

  control.addEventListener("click", () => {
    if (control.disabled) return;
    const willOpen = !host.classList.contains("is-open");
    closeCustomSelects(willOpen ? select.id : "");
    host.classList.toggle("is-open", willOpen);
    control.setAttribute("aria-expanded", willOpen ? "true" : "false");
    menu.hidden = !willOpen;
  });

  menu.addEventListener("click", (event) => {
    const clickTarget = event.target instanceof Element ? event.target : null;
    const optionButton = clickTarget ? clickTarget.closest("[data-custom-select-value]") : null;
    if (!optionButton || optionButton.hasAttribute("disabled")) return;
    const nextValue = optionButton.getAttribute("data-custom-select-value") || "";
    const hasChanged = select.value !== nextValue;
    select.value = nextValue;
    refresh();
    closeCustomSelects();
    if (hasChanged) {
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });

  select.addEventListener("change", refresh);

  const observer = new MutationObserver(() => {
    refresh();
  });
  observer.observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "label", "selected"] });

  customSelectRegistry.set(select.id, { host, control, menu, refresh, observer });
  refresh();
}

function initializeCustomSelects() {
  document.querySelectorAll("select[data-custom-select]").forEach((select) => {
    enhanceCustomSelect(select);
  });
}

function fallbackTradeStyleLabel(style) {
  const labels = {
    scalp: "Scalp",
    day_trade: "Day Trade",
    swing: "Swing",
    position_hold: "Position Hold",
  };
  return labels[String(style || "").trim()] || "Day Trade";
}

function normalizePercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.abs(Number(value)) <= 1 ? Number(value) * 100 : Number(value);
}

function percentToDecimal(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return Math.abs(Number(value)) <= 1 ? Number(value) : Number(value) / 100;
}

function baseAssetFromSymbol(symbol) {
  const normalized = String(symbol || "").toUpperCase();
  return normalized.replace(/(USDT|USDC|USD|PERP)$/g, "") || normalized || "BTC";
}

function usernameInitials(value) {
  const cleaned = String(value || "").trim();
  if (!cleaned) return "AK";
  const parts = cleaned.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
}

function formatDateStamp(value) {
  if (!value) return "Awaiting timestamp";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatHistoryDate(value) {
  if (!value) return "Awaiting timestamp";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function signalsLeftLabel(usage) {
  if (!usage) return "--";
  return usage.is_unlimited ? "Unlimited" : String(usage.signals_left ?? 0);
}

function lastSignalMatchesSelection(payload = state.lastSignal) {
  if (!payload?.signal) return false;
  const payloadSymbol = String(payload.symbol || state.symbol || "").toUpperCase();
  const payloadInterval = String(payload.interval || state.interval || "");
  const payloadTradeStyle = String(payload.trade_style || payload.signal?.style_profile?.key || state.tradeStyle || "");
  return (
    payloadSymbol === String(state.symbol || "").toUpperCase() &&
    payloadInterval === String(state.interval || "") &&
    payloadTradeStyle === String(state.tradeStyle || "")
  );
}

function displaySignalSide(payload = {}) {
  const regularSide = String(payload?.signal?.signal || "HOLD").toUpperCase();
  const instantSide = String(payload?.instant_signal?.side || "").toUpperCase();
  if (regularSide === "HOLD" && ["BUY", "SELL"].includes(instantSide)) return instantSide;
  return regularSide;
}

function payloadHasActionableSignal(payload = {}) {
  return ["BUY", "SELL"].includes(displaySignalSide(payload));
}

function signalCapturedAtMs(payload = {}) {
  const parsed = new Date(payload?.captured_at || 0).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function storedSignalIsFresh(payload = {}) {
  const capturedAt = signalCapturedAtMs(payload);
  if (!capturedAt) return false;
  const ageMs = Date.now() - capturedAt;
  const regularSide = String(payload?.signal?.signal || "HOLD").toUpperCase();
  const maxAgeMs = regularSide === "HOLD" ? 5 * 60 * 1000 : 6 * 60 * 60 * 1000;
  return ageMs >= 0 && ageMs <= maxAgeMs;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function applySignedTone(element, numericValue) {
  if (!element) return;
  element.classList.remove("positive", "negative", "neutral");
  if (numericValue === null || numericValue === undefined || Number.isNaN(Number(numericValue))) {
    element.classList.add("neutral");
    return;
  }
  if (Number(numericValue) > 0) {
    element.classList.add("positive");
  } else if (Number(numericValue) < 0) {
    element.classList.add("negative");
  } else {
    element.classList.add("neutral");
  }
}

function normalizeSymbolToken(value) {
  return String(value || "")
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
}

function tradeTimestampValue(trade) {
  const raw = trade?.closed_at || trade?.opened_at || trade?.created_at || "";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

function viewportMetrics() {
  return {
    width: Math.max(window.innerWidth || 0, document.documentElement?.clientWidth || 0),
    height: Math.max(window.innerHeight || 0, document.documentElement?.clientHeight || 0),
  };
}

function updateResponsiveDensity() {
  const { width, height } = viewportMetrics();
  const compactHome = width <= 480 && height <= 900;
  const tightCompactHome = width <= 430 && height <= 780;
  document.body.classList.toggle("compact-home", compactHome);
  document.body.classList.toggle("compact-home-tight", tightCompactHome);
}

function nextRequestTicket(scope) {
  state.requestSeq[scope] = Number(state.requestSeq?.[scope] || 0) + 1;
  return state.requestSeq[scope];
}

function isActiveRequestTicket(scope, ticket) {
  return Number(state.requestSeq?.[scope] || 0) === Number(ticket || 0);
}

function pageElement(page) {
  return els.pages.find((section) => section.dataset.page === page) || null;
}

function setPageLoading(page, loading, label = "Refreshing...") {
  const section = pageElement(page);
  if (!section) return;
  section.dataset.loading = loading ? "true" : "false";
  section.dataset.loadingLabel = loading ? label : "";
}

function pageLoadingLabel(page) {
  if (page === "home") return "Refreshing dashboard...";
  if (page === "markets") return "Refreshing market...";
  if (page === "desk") return "Refreshing desk...";
  if (page === "journal") return "Refreshing journal...";
  if (page === "settings") return "Refreshing settings...";
  return "Refreshing...";
}

function renderInlineEmpty(message) {
  return `<div class="empty-state card">${escapeHtml(message)}</div>`;
}

function closedTrades(trades = []) {
  return (trades || [])
    .filter((trade) => String(trade?.status || "").toLowerCase() === "closed" || Number(trade?.pnl_usd || 0) !== 0)
    .slice()
    .sort((left, right) => tradeTimestampValue(right) - tradeTimestampValue(left));
}

function homePeriodMs(period) {
  if (period === "7D") return 7 * 24 * 60 * 60 * 1000;
  if (period === "30D") return 30 * 24 * 60 * 60 * 1000;
  return 24 * 60 * 60 * 1000;
}

function comparePeriodChange(currentValue, previousValue) {
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  if (!previous) {
    return current === 0 ? 0 : 100;
  }
  return ((current - previous) / Math.abs(previous)) * 100;
}

function buildSparklineSvg(values, tone = "profit") {
  const points = (values || []).map((value) => Number(value || 0));
  const rows = points.length >= 2 ? points : [0, 0, ...(points.length ? points : [])].slice(-2);
  const min = Math.min(...rows);
  const max = Math.max(...rows);
  const span = Math.max(max - min, 1);
  const width = 320;
  const height = 116;
  const step = rows.length > 1 ? width / (rows.length - 1) : width;
  const coordinates = rows.map((value, index) => {
    const x = Number((index * step).toFixed(2));
    const y = Number((height - ((value - min) / span) * (height - 12) - 6).toFixed(2));
    return { x, y };
  });
  const linePoints = coordinates.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPoints = `0,${height} ${linePoints} ${width},${height}`;
  const accent = tone === "loss" ? "#ff5a68" : "#2bf0b8";
  const fill = tone === "loss" ? "rgba(255, 90, 104, 0.18)" : "rgba(43, 240, 184, 0.18)";
  return `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      <polygon points="${areaPoints}" fill="${fill}"></polygon>
      <polyline points="${linePoints}" fill="none" stroke="${accent}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
  `;
}

function homeAssetTone(symbol) {
  const base = baseAssetFromSymbol(symbol);
  if (base === "BTC") return "btc";
  if (base === "ETH") return "eth";
  if (base === "SOL") return "sol";
  if (base === "XRP") return "xrp";
  return "generic";
}

function renderHomeTradeHistory(trades = []) {
  if (!trades.length) {
    return `<div class="empty-state card">No recent closed trades are available yet.</div>`;
  }
  return trades
    .slice(0, 4)
    .map((trade) => {
      const symbol = trade.symbol || state.symbol || "BTCUSDT";
      const base = baseAssetFromSymbol(symbol);
      const side = String(trade.side || "Buy").toUpperCase();
      const pnl = Number(trade.pnl_usd || 0);
      const quantity = Number(trade.quantity || 0);
      const quantitySign = side === "SELL" ? "-" : "+";
      const quantityText = quantity
        ? `${quantitySign}${formatNumber(Math.abs(quantity), quantity >= 10 ? 2 : 3)} ${base}`
        : `${pnl >= 0 ? "+" : "-"}${formatNumber(Math.abs(pnl), 2)} USDT`;
      const usdText = `${pnl >= 0 ? "+" : "-"}${formatNumber(Math.abs(pnl), 2)} USDT`;
      const pnlClass = pnl >= 0 ? "positive" : "negative";
      return `
        <button
          type="button"
          class="home-history-item"
          data-trade-open="markets"
          data-symbol="${escapeHtml(symbol)}"
          data-interval="${escapeHtml(trade.timeframe || state.interval || "1m")}"
        >
          <div class="home-history-left">
            <div class="home-asset-badge home-asset-badge--${homeAssetTone(symbol)}">${escapeHtml(base.slice(0, 1))}</div>
            <div class="home-history-copy">
              <div class="home-history-title-row">
                <strong>${escapeHtml(symbol.replace("USDT", "/USDT"))}</strong>
                <span class="home-history-side ${side === "SELL" ? "sell" : "buy"}">${escapeHtml(side === "SELL" ? "Sell" : "Buy")}</span>
              </div>
              <div class="home-history-meta">${escapeHtml(formatHistoryDate(trade.closed_at || trade.opened_at || trade.created_at))}</div>
            </div>
          </div>
          <div class="home-history-right">
            <div class="home-history-qty ${pnlClass}">${escapeHtml(quantityText)}</div>
            <div class="home-history-usd">${escapeHtml(usdText)}</div>
          </div>
          <div class="home-history-chevron">&#8250;</div>
        </button>
      `;
    })
    .join("");
}

function renderHomeDashboardPayload({ dashboard, journal, marketPayload }) {
  const trades = closedTrades(journal?.trades || dashboard?.recent_trades || []);
  const windowMs = homePeriodMs(state.homePeriod);
  const now = Date.now();
  const currentTrades = trades.filter((trade) => tradeTimestampValue(trade) >= now - windowMs);
  const previousTrades = trades.filter((trade) => {
    const timestamp = tradeTimestampValue(trade);
    return timestamp < now - windowMs && timestamp >= now - windowMs * 2;
  });
  const activeTrades = currentTrades.length ? currentTrades : trades;

  const totalProfit = activeTrades.reduce((sum, trade) => sum + Math.max(Number(trade.pnl_usd || 0), 0), 0);
  const totalLoss = Math.abs(activeTrades.reduce((sum, trade) => sum + Math.min(Number(trade.pnl_usd || 0), 0), 0));
  const netPnl = activeTrades.reduce((sum, trade) => sum + Number(trade.pnl_usd || 0), 0);
  const wins = activeTrades.filter((trade) => Number(trade.pnl_usd || 0) > 0).length;
  const totalClosed = activeTrades.length;
  const winRate = totalClosed ? (wins / totalClosed) * 100 : Number(dashboard?.metrics?.win_rate || 0);

  const prevProfit = previousTrades.reduce((sum, trade) => sum + Math.max(Number(trade.pnl_usd || 0), 0), 0);
  const prevLoss = Math.abs(previousTrades.reduce((sum, trade) => sum + Math.min(Number(trade.pnl_usd || 0), 0), 0));
  const profitDelta = comparePeriodChange(totalProfit, prevProfit);
  const lossDelta = comparePeriodChange(totalLoss, prevLoss);

  const profitSeries = activeTrades
    .slice()
    .reverse()
    .reduce((rows, trade) => {
      const previous = rows.length ? rows[rows.length - 1] : 0;
      rows.push(previous + Math.max(Number(trade.pnl_usd || 0), 0));
      return rows;
    }, []);
  const lossSeries = activeTrades
    .slice()
    .reverse()
    .reduce((rows, trade) => {
      const previous = rows.length ? rows[rows.length - 1] : 0;
      rows.push(previous + Math.abs(Math.min(Number(trade.pnl_usd || 0), 0)));
      return rows;
    }, []);

  const marketStatus = marketPayload?.engine_status || {};
  const statusReady = Boolean(marketStatus.ready);
  const statusMessage = marketStatus.message || "Real-time market data is being updated...";
  const statusTitle = statusReady ? "Engine Syncing" : "Engine Warming";

  els.homeSyncTitle.textContent = statusTitle;
  els.homeSyncMessage.textContent = statusMessage;
  els.homeSyncPill.textContent = statusReady ? "Live" : "Syncing";
  els.homeSyncPill.classList.toggle("warm", !statusReady);

  els.homePeriodSelect.value = state.homePeriod;
  refreshCustomSelect(els.homePeriodSelect);
  els.homeProfitTotal.textContent = formatNumber(totalProfit, 2);
  els.homeLossTotal.textContent = `-${formatNumber(totalLoss, 2)}`;
  els.homeNetTotal.textContent = `${netPnl >= 0 ? "+" : "-"}${formatNumber(Math.abs(netPnl), 2)}`;
  els.homeWinRate.textContent = `${Math.round(winRate)}%`;
  els.homeWinCount.textContent = `${wins} of ${totalClosed || 0}`;
  els.homeProfitDelta.textContent = `${profitDelta >= 0 ? "\u2191" : "\u2193"} ${formatNumber(Math.abs(profitDelta), 2)}%`;
  els.homeLossDelta.textContent = `${lossDelta >= 0 ? "\u2191" : "\u2193"} ${formatNumber(Math.abs(lossDelta), 2)}%`;
  applySignedTone(els.homeProfitTotal, totalProfit);
  applySignedTone(els.homeLossTotal, -totalLoss);
  applySignedTone(els.homeNetTotal, netPnl);
  applySignedTone(els.homeProfitDelta, profitDelta);
  els.homeLossDelta.classList.remove("positive", "negative", "neutral");
  els.homeLossDelta.classList.add("negative");
  els.homeProfitSparkline.innerHTML = buildSparklineSvg(profitSeries, "profit");
  els.homeLossSparkline.innerHTML = buildSparklineSvg(lossSeries, "loss");
  els.homeHistoryList.innerHTML = renderHomeTradeHistory((dashboard?.recent_trades || trades).slice(0, 4));

  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (Math.min(Math.max(winRate, 0), 100) / 100) * circumference;
  if (els.homeWinRingProgress) {
    els.homeWinRingProgress.style.strokeDasharray = `${circumference}`;
    els.homeWinRingProgress.style.strokeDashoffset = `${dashOffset}`;
  }

  if (els.homeAvatarInitials) {
    els.homeAvatarInitials.textContent = usernameInitials(dashboard?.user?.username || state.session?.username);
  }
}

function buildMovingAverage(candles, period) {
  const rows = [];
  let runningTotal = 0;
  for (let index = 0; index < candles.length; index += 1) {
    runningTotal += Number(candles[index]?.close || 0);
    if (index >= period) {
      runningTotal -= Number(candles[index - period]?.close || 0);
    }
    if (index >= period - 1) {
      rows.push({
        time: candles[index].time,
        value: runningTotal / period,
      });
    }
  }
  return rows;
}

function buildExponentialMovingAverage(candles, period) {
  const rows = [];
  const multiplier = 2 / (period + 1);
  let ema = null;
  for (let index = 0; index < candles.length; index += 1) {
    const close = Number(candles[index]?.close || 0);
    ema = ema === null ? close : close * multiplier + ema * (1 - multiplier);
    if (index >= period - 1) {
      rows.push({
        time: candles[index].time,
        value: ema,
      });
    }
  }
  return rows;
}

function buildBollingerBands(candles, period = 20, multiplier = 2) {
  const upper = [];
  const middle = [];
  const lower = [];
  const window = [];
  for (let index = 0; index < candles.length; index += 1) {
    const close = Number(candles[index]?.close || 0);
    window.push(close);
    if (window.length > period) window.shift();
    if (window.length < period) continue;
    const mean = window.reduce((sum, value) => sum + value, 0) / period;
    const variance = window.reduce((sum, value) => sum + (value - mean) ** 2, 0) / period;
    const deviation = Math.sqrt(variance);
    upper.push({ time: candles[index].time, value: mean + multiplier * deviation });
    middle.push({ time: candles[index].time, value: mean });
    lower.push({ time: candles[index].time, value: mean - multiplier * deviation });
  }
  return { upper, middle, lower };
}

function buildParabolicSar(candles, step = 0.02, maxStep = 0.2) {
  if (!candles || candles.length < 2) return [];
  const rows = [];
  let rising = Number(candles[1]?.close || 0) >= Number(candles[0]?.close || 0);
  let acceleration = step;
  let extremePoint = rising
    ? Math.max(Number(candles[0]?.high || 0), Number(candles[1]?.high || 0))
    : Math.min(Number(candles[0]?.low || 0), Number(candles[1]?.low || 0));
  let sar = rising
    ? Math.min(Number(candles[0]?.low || 0), Number(candles[1]?.low || 0))
    : Math.max(Number(candles[0]?.high || 0), Number(candles[1]?.high || 0));
  rows.push({ time: candles[0].time, value: sar });

  for (let index = 1; index < candles.length; index += 1) {
    const current = candles[index];
    const previous = candles[Math.max(index - 1, 0)];
    const previousTwo = candles[Math.max(index - 2, 0)];
    sar += acceleration * (extremePoint - sar);

    if (rising) {
      sar = Math.min(sar, Number(previous?.low || sar), Number(previousTwo?.low || sar));
      if (Number(current?.low || 0) < sar) {
        rising = false;
        sar = extremePoint;
        extremePoint = Number(current?.low || 0);
        acceleration = step;
      } else if (Number(current?.high || 0) > extremePoint) {
        extremePoint = Number(current.high || 0);
        acceleration = Math.min(acceleration + step, maxStep);
      }
    } else {
      sar = Math.max(sar, Number(previous?.high || sar), Number(previousTwo?.high || sar));
      if (Number(current?.high || 0) > sar) {
        rising = true;
        sar = extremePoint;
        extremePoint = Number(current?.high || 0);
        acceleration = step;
      } else if (Number(current?.low || 0) < extremePoint) {
        extremePoint = Number(current.low || 0);
        acceleration = Math.min(acceleration + step, maxStep);
      }
    }

    rows.push({ time: current.time, value: sar });
  }

  return rows;
}

let toastTimer = null;
function showToast(message, tone = "info") {
  if (!message) return;
  els.toast.textContent = message;
  els.toast.className = `toast ${tone}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.toast.className = "toast hidden";
    els.toast.textContent = "";
  }, 3200);
}

function setAuthMessage(message, tone = "info") {
  if (!message) {
    els.authGlobalMessage.className = "banner hidden";
    els.authGlobalMessage.textContent = "";
    return;
  }
  els.authGlobalMessage.className = `banner ${tone === "error" ? "error" : ""}`;
  els.authGlobalMessage.textContent = message;
}

function setStageBanner(element, message) {
  if (!message) {
    element.className = "banner subtle hidden";
    element.textContent = "";
    return;
  }
  element.className = "banner subtle";
  element.textContent = message;
}

function persistWorkspaceSelection() {
  try {
    localStorage.setItem("finwise-mobile-symbol", state.symbol);
    localStorage.setItem("finwise-mobile-interval", state.interval);
    localStorage.setItem("finwise-mobile-trade-style", state.tradeStyle);
    localStorage.setItem("finwise-mobile-indicator", state.chartIndicator);
    localStorage.setItem("finwise-mobile-home-period", state.homePeriod);
  } catch (error) {
    console.debug(error);
  }
}

function telegramNotificationsReady() {
  const notifications = state.notifications || {};
  return Boolean(
    notifications.telegram_enabled &&
      (notifications.telegram_connected || String(notifications.telegram_chat_id || "").trim()),
  );
}

function onlineConnectionAvailable() {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

function signalAllowanceAvailable() {
  if (!state.usage) return true;
  if (state.usage.is_unlimited) return true;
  return Number(state.usage.signals_left ?? 0) > 0;
}

function localDateStamp() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function autoSignalStorageKey() {
  const username = String(state.session?.username || "guest").trim().toLowerCase() || "guest";
  const symbol = normalizeSymbolToken(state.symbol || "BTCUSDT") || "BTCUSDT";
  const interval = String(state.interval || "5m").replace(/[^a-zA-Z0-9_-]/g, "") || "5m";
  const tradeStyle = String(state.tradeStyle || "day_trade").replace(/[^a-zA-Z0-9_-]/g, "") || "day_trade";
  const today = localDateStamp();
  return `${AUTO_SIGNAL_SENT_KEY_PREFIX}:${username}:${symbol}:${interval}:${tradeStyle}:${today}`;
}

function automaticSignalAlreadySent() {
  return Boolean(readStoredValue(autoSignalStorageKey(), ""));
}

function markAutomaticSignalSent(payload = {}) {
  if (!payloadHasActionableSignal(payload)) {
    removeStoredValue(autoSignalStorageKey());
    return false;
  }
  writeStoredValue(autoSignalStorageKey(), payload.captured_at || new Date().toISOString());
  return true;
}

function automaticSignalCanRun({ ignoreAlreadySent = false } = {}) {
  if (!state.session) return false;
  if (state.autoSignalInFlight) return false;
  if (!onlineConnectionAvailable()) return false;
  if (!telegramNotificationsReady()) return false;
  if (!signalAllowanceAvailable()) return false;
  if (!ignoreAlreadySent && automaticSignalAlreadySent()) return false;
  return true;
}

async function ensureAutomaticSignalPermission({ forcePrompt = false } = {}) {
  const storedPermission = readStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "");
  const nativeNotificationsSupported = "Notification" in window;

  if (!forcePrompt && storedPermission === "granted") return true;
  if (!forcePrompt && storedPermission === "denied") return false;

  if (nativeNotificationsSupported) {
    if (Notification.permission === "granted") {
      writeStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "granted");
      return true;
    }
    if (Notification.permission === "denied") {
      writeStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "denied");
      return false;
    }
  }

  const allowedByUser = window.confirm(AUTO_SIGNAL_PERMISSION_COPY);
  if (!allowedByUser) {
    writeStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "denied");
    return false;
  }

  if (nativeNotificationsSupported && Notification.permission === "default") {
    try {
      const browserPermission = await Notification.requestPermission();
      if (browserPermission === "denied") {
        writeStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "denied");
        return false;
      }
    } catch (error) {
      console.debug(error);
    }
  }

  writeStoredValue(AUTO_SIGNAL_PERMISSION_KEY, "granted");
  return true;
}

function showLocalSignalNotification(payload = {}) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const signal = payload.signal || {};
  const instantSignal = payload.instant_signal || {};
  const signalLabel = displaySignalSide(payload);
  const title = `Finwise ${signalLabel} ${payload.symbol || state.symbol}`;
  const confidence = signalLabel === String(instantSignal.side || "").toUpperCase() ? instantSignal.confidence : signal.confidence;
  const body = `Confidence ${formatConfidence(confidence)}. Sent to Telegram.`;
  try {
    new Notification(title, {
      body,
      tag: `finwise-${payload.symbol || state.symbol}-${payload.interval || state.interval}`,
    });
  } catch (error) {
    console.debug(error);
  }
}

async function maybeSendAutomaticTelegramSignal({ forcePermissionPrompt = false, showToasts = false } = {}) {
  if (!automaticSignalCanRun()) {
    if (showToasts) {
      if (!telegramNotificationsReady()) {
        showToast("Connect and enable Telegram alerts before automatic signals can be sent.", "error");
      } else if (!signalAllowanceAvailable()) {
        showToast("Daily signal limit reached for your current plan.", "error");
      } else if (automaticSignalAlreadySent()) {
        showToast("Today's automatic Telegram signal has already been sent.");
      }
    }
    return false;
  }

  const allowed = await ensureAutomaticSignalPermission({ forcePrompt: forcePermissionPrompt });
  if (!allowed) {
    if (showToasts) showToast("Automatic Telegram signal notifications are off.");
    return false;
  }

  if (!automaticSignalCanRun()) return false;

  state.autoSignalInFlight = true;
  try {
    const payload = await requestSignal(null, {
      automatic: true,
      rethrow: true,
      showErrorToast: false,
      showReadyToast: false,
    });
    if (!payload) return false;
    const markedAsSent = markAutomaticSignalSent(payload);
    if (markedAsSent) {
      showLocalSignalNotification(payload);
      showToast("AI signal sent to Telegram.");
    } else if (showToasts) {
      showToast("Market checked. Waiting for a tradable crypto signal.");
    }
    return markedAsSent;
  } catch (error) {
    if (showToasts) {
      showToast(error.message || "Automatic Telegram signal could not be sent.", "error");
    } else {
      console.debug(error);
    }
    return false;
  } finally {
    state.autoSignalInFlight = false;
  }
}

function scheduleAutomaticTelegramSignal(options = {}) {
  clearTimeout(state.autoSignalTimer);
  if (!state.session) return;
  const delayMs = Number(options.delayMs ?? 800);
  state.autoSignalTimer = window.setTimeout(() => {
    maybeSendAutomaticTelegramSignal(options).catch((error) => console.debug(error));
  }, Math.max(0, delayMs));
}

function syncUrl() {
  const nextUrl = new URL(window.location.href);
  nextUrl.searchParams.set("page", state.page);
  nextUrl.searchParams.set("symbol", state.symbol);
  nextUrl.searchParams.set("interval", state.interval);
  nextUrl.searchParams.set("tradeStyle", state.tradeStyle);
  nextUrl.searchParams.set("indicator", state.chartIndicator);
  nextUrl.searchParams.set("homePeriod", state.homePeriod);
  if (state.session) {
    nextUrl.searchParams.delete("auth");
  } else {
    nextUrl.searchParams.set("auth", state.authPanel);
  }
  window.history.replaceState({}, "", nextUrl.toString());
}

function switchAuthPanel(panel) {
  state.authPanel = ["login", "register", "reset"].includes(panel) ? panel : "login";
  els.authSwitches.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.authPanel === state.authPanel);
  });
  setHidden(els.loginForm, state.authPanel !== "login");
  setHidden(els.registerForm, state.authPanel !== "register");
  setHidden(els.resetForm, state.authPanel !== "reset");
  syncUrl();
}

function resetAuthStages() {
  state.registerPending = false;
  state.resetPending = false;
  setHidden(els.registerOtpBlock, true);
  setHidden(els.resetOtpBlock, true);
  els.registerSubmit.textContent = "Send Verification Code";
  els.resetSubmit.textContent = "Send Reset Code";
  setStageBanner(els.registerStageBanner, "");
  setStageBanner(els.resetStageBanner, "");
}

function applyLoggedOut(data = {}) {
  state.session = null;
  state.usage = null;
  state.broker = null;
  state.notifications = null;
  state.autoSignalInFlight = false;
  clearTimeout(state.autoSignalTimer);
  state.autoSignalTimer = null;
  clearInterval(state.liveTimer);
  state.liveTimer = null;
  els.pages.forEach((section) => {
    section.dataset.loading = "false";
    section.dataset.loadingLabel = "";
  });
  setHidden(els.appView, true);
  setHidden(els.authView, false);
  resetAuthStages();
  if (data.email_auth && !data.email_auth.enabled) {
    setAuthMessage(data.email_auth.message, "info");
  }
  switchAuthPanel(state.authPanel || "login");
}

async function api(path, options = {}) {
  const resolvedPath =
    typeof path === "string" && (path.startsWith("/api/mobile/") || path === "/api/mobile")
      ? `${MOBILE_PROXY_PREFIX}${path.slice("/api/mobile".length)}`
      : path;
  const controller = new AbortController();
  const timeoutMs = Number(options.timeoutMs || 14000);
  const timeoutHandle = window.setTimeout(() => controller.abort(), timeoutMs);
  const fetchOptions = {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
    },
    credentials: "same-origin",
    signal: controller.signal,
  };
  if (options.body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(options.body);
  }
  let response;
  let data = {};
  try {
    response = await fetch(resolvedPath, fetchOptions);
    data = await response.json().catch(() => ({}));
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("The request timed out. Please try again.");
    }
    throw new Error("Unable to reach Finwise right now. Check your connection and retry.");
  } finally {
    window.clearTimeout(timeoutHandle);
  }
  if (response.status === 401) {
    applyLoggedOut(data);
    throw new Error(data.error || "Sign in required.");
  }
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

function updateTopSummary(user, usage, broker) {
  els.sessionUsername.textContent = user?.username || "Workspace";
  els.sessionPlan.textContent = user?.premium ? "Premium" : "Free";
  els.sessionSignalsLeft.textContent = signalsLeftLabel(usage);
  els.sessionBrokerStatus.textContent = "Live Feed";
  if (els.homeAvatarInitials) {
    els.homeAvatarInitials.textContent = usernameInitials(user?.username);
  }
  if (els.headerLivePill) {
    els.headerLivePill.classList.toggle("is-offline", !state.session);
  }
  state.usage = usage || state.usage;
  state.broker = broker || state.broker;
}

function renderStatusChip(text, tone = "") {
  const className = ["status-chip", tone].filter(Boolean).join(" ");
  return `<span class="${className}">${escapeHtml(text)}</span>`;
}

function renderInfoCard(title, copy, rows = [], chips = []) {
  const rowMarkup = rows
    .map(
      (row) => `
        <div class="summary-pill">
          <span>${escapeHtml(row.label)}</span>
          <strong>${escapeHtml(row.value)}</strong>
        </div>
      `,
    )
    .join("");
  const chipMarkup = chips.length ? `<div class="info-chip-row">${chips.join("")}</div>` : "";
  return `
    <div class="info-title">${escapeHtml(title)}</div>
    <div class="info-copy">${copy}</div>
    ${rowMarkup ? `<div class="info-row">${rowMarkup}</div>` : ""}
    ${chipMarkup}
  `;
}

function syncTelegramConnectUi(notifications = {}) {
  const connected = Boolean(notifications.telegram_connected || notifications.telegram_chat_id);
  const destinationLabel = notifications.telegram_destination_label || "your Telegram chat";
  const botHandle = notifications.telegram_bot_username ? `@${notifications.telegram_bot_username}` : "the Finwise bot";
  const connectUrl = notifications.telegram_connect_url || "";

  if (els.settingsTelegramStatus) {
    els.settingsTelegramStatus.textContent = connected
      ? `Connected to ${destinationLabel}.`
      : `Bot ready: ${botHandle}.`;
  }
  if (els.settingsTelegramCopy) {
    els.settingsTelegramCopy.textContent = connected
      ? `Signals can now flow into ${destinationLabel}. Open the bot again any time if you want to refresh this route.`
      : `Open ${botHandle}, tap Start once, then come back here and finish the link. No chat ID hunting.`;
  }
  if (els.settingsTelegramOpen) {
    els.settingsTelegramOpen.href = connectUrl || "#";
    els.settingsTelegramOpen.classList.toggle("is-disabled", !connectUrl);
    els.settingsTelegramOpen.setAttribute("aria-disabled", connectUrl ? "false" : "true");
    els.settingsTelegramOpen.tabIndex = connectUrl ? 0 : -1;
  }
  if (els.settingsTelegramFinish) {
    els.settingsTelegramFinish.textContent = connected ? "Refresh Connect" : "Finish Connect";
  }
  if (els.settingsTelegramCard) {
    els.settingsTelegramCard.classList.toggle("is-connected", connected);
  }
}

function syncTradeStyleControl(tradeStylePayload = {}) {
  const options = Array.isArray(tradeStylePayload.options) ? tradeStylePayload.options : [];
  const selectedStyle = tradeStylePayload.selected || state.tradeStyle || "day_trade";
  state.tradeStyle = selectedStyle;

  if (!els.deskTradeStyle) return;

  if (options.length) {
    els.deskTradeStyle.innerHTML = options
      .map(
        (option) =>
          `<option value="${escapeHtml(option.value)}"${option.value === selectedStyle ? " selected" : ""}>${escapeHtml(option.label || fallbackTradeStyleLabel(option.value))}</option>`,
      )
      .join("");
  } else if (!els.deskTradeStyle.options.length) {
    [
      { value: "scalp", label: "Scalp" },
      { value: "day_trade", label: "Day Trade" },
      { value: "swing", label: "Swing" },
      { value: "position_hold", label: "Position Hold" },
    ].forEach((option) => {
      const nextOption = document.createElement("option");
      nextOption.value = option.value;
      nextOption.textContent = option.label;
      els.deskTradeStyle.appendChild(nextOption);
    });
  }

  els.deskTradeStyle.value = selectedStyle;
  refreshCustomSelect(els.deskTradeStyle);
}

function renderTradeCards(trades) {
  if (!trades || !trades.length) {
    return `<div class="empty-state card">No trades are tracked here yet.</div>`;
  }
  return trades
    .map((trade) => {
      const pnl = Number(trade.pnl_usd || 0);
      const pnlClass = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "";
      const tradeSymbol = trade.symbol || state.symbol || "BTCUSDT";
      const tradeInterval = trade.timeframe || state.interval || "1m";
      return `
        <article class="trade-card">
          <div class="trade-topline">
            <div>
              <div class="trade-symbol">${escapeHtml(trade.symbol || "Unknown")}</div>
              <div class="trade-time">${escapeHtml(formatDateStamp(trade.closed_at || trade.opened_at || trade.created_at))}</div>
            </div>
            <div class="trade-pnl ${pnlClass}">${pnl === 0 ? "--" : `${pnl > 0 ? "+" : ""}$${formatNumber(pnl, 2)}`}</div>
          </div>
          <div class="trade-meta">
            <span>${escapeHtml((trade.side || "tracked").toUpperCase())}</span>
            <span>${escapeHtml((trade.status || "tracked").toUpperCase())}</span>
            <span>${escapeHtml(trade.timeframe || "--")}</span>
            <span>${escapeHtml(trade.source || "manual")}</span>
          </div>
          <div class="trade-actions">
            <button
              type="button"
              class="trade-action"
              data-trade-open="markets"
              data-symbol="${escapeHtml(tradeSymbol)}"
              data-interval="${escapeHtml(tradeInterval)}"
            >
              Open Market
            </button>
            <button
              type="button"
              class="trade-action"
              data-trade-open="desk"
              data-symbol="${escapeHtml(tradeSymbol)}"
              data-interval="${escapeHtml(tradeInterval)}"
            >
              Open Desk
            </button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderMetricGrid(metrics) {
  const cards = [
    { label: "Today Trades", value: metrics.today_trades ?? 0 },
    { label: "Today Net", value: `$${formatNumber(metrics.today_net, 2)}` },
    { label: "Win Rate", value: formatPercent((metrics.win_rate || 0) / 100) },
    { label: "Lifetime Net", value: `$${formatNumber(metrics.lifetime_net, 2)}` },
  ];
  return cards
    .map(
      (card) => `
        <div class="metric-card">
          <span>${escapeHtml(card.label)}</span>
          <strong>${escapeHtml(card.value)}</strong>
        </div>
      `,
    )
    .join("");
}

function filteredSymbols(queryText = "") {
  const normalized = normalizeSymbolToken(queryText);
  if (!normalized) return [...state.symbols];
  return state.symbols.filter((symbol) => normalizeSymbolToken(symbol).includes(normalized));
}

function renderSymbolOptions(symbols) {
  const nextSymbols = symbols && symbols.length ? symbols : [...state.symbols];
  const selected = nextSymbols.includes(state.symbol) ? state.symbol : nextSymbols[0] || state.symbol || "BTCUSDT";
  els.marketSymbol.innerHTML = nextSymbols
    .map((symbol) => `<option value="${escapeHtml(symbol)}">${escapeHtml(symbol)}</option>`)
    .join("");
  els.marketSymbol.value = selected;
  refreshCustomSelect(els.marketSymbol);
}

function displayedTimeframes() {
  const preferred = ["1m", "3m", "5m", "15m", "1h", "4h"];
  const available = state.timeframes.length ? state.timeframes : preferred;
  const ordered = preferred.filter((interval) => available.includes(interval));
  return ordered.length ? ordered : available.slice(0, 6);
}

function timeframeSet(preferred) {
  const available = displayedTimeframes();
  const picked = preferred.filter((interval) => available.includes(interval));
  if (state.interval && !picked.includes(state.interval) && available.includes(state.interval)) {
    picked.push(state.interval);
  }
  return picked.length ? picked : available;
}

function renderTimeframePills() {
  const renderMarkup = (intervals) =>
    intervals
      .map(
        (interval) => `
          <button
            type="button"
            class="timeframe-pill ${interval === state.interval ? "is-active" : ""}"
            data-timeframe-target="${escapeHtml(interval)}"
          >
            ${escapeHtml(interval)}
          </button>
        `,
      )
      .join("");

  els.marketTimeframePills.innerHTML = renderMarkup(timeframeSet(["1m", "3m", "15m", "1h"]));
  els.marketChartTimeframes.innerHTML = renderMarkup(timeframeSet(["1m", "3m", "5m", "15m", "1h", "4h"]));
}

function renderIndicatorButtons() {
  els.marketIndicatorButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.marketIndicator === state.chartIndicator);
  });
}

function toggleIndicatorDrawer(force) {
  if (!els.marketIndicatorDrawer || !els.marketIndicatorToggle) return;
  const shouldOpen = typeof force === "boolean" ? force : els.marketIndicatorDrawer.classList.contains("hidden");
  setHidden(els.marketIndicatorDrawer, !shouldOpen);
  els.marketIndicatorToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function setActiveIndicator(indicator, { sync = true } = {}) {
  const allowed = ["MA", "EMA", "BOLL", "SAR", "MAVOL", "MACD"];
  state.chartIndicator = allowed.includes(String(indicator || "").toUpperCase())
    ? String(indicator).toUpperCase()
    : "EMA";
  renderIndicatorButtons();
  if (state.lastCandles.length) {
    applyIndicatorSeries(state.lastCandles);
    renderIndicatorLegend(state.lastCandles);
  }
  if (sync) {
    persistWorkspaceSelection();
    syncUrl();
  }
  toggleIndicatorDrawer(false);
}

function setActiveMarketView(targetId = "market-chart-section") {
  state.marketView = targetId;
  els.marketViewTabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.marketScroll === targetId);
  });
}

function scrollToMarketSection(targetId) {
  const section = document.getElementById(targetId);
  if (!section) return;
  setActiveMarketView(targetId);
  section.scrollIntoView({ behavior: "smooth", block: "start" });
}

function ensureControls(data) {
  const symbols = data.symbols || state.symbols;
  const timeframes = data.timeframes || state.timeframes;
  state.symbols = symbols;
  state.timeframes = timeframes;
  if (!symbols.includes(state.symbol)) state.symbol = data.defaults?.symbol || symbols[0] || "BTCUSDT";
  if (!timeframes.includes(state.interval)) state.interval = data.defaults?.interval || timeframes[0] || "5m";

  els.marketInterval.innerHTML = timeframes
    .map((interval) => `<option value="${escapeHtml(interval)}">${escapeHtml(interval)}</option>`)
    .join("");
  els.marketInterval.value = state.interval;
  renderTimeframePills();
  renderIndicatorButtons();
  renderSymbolOptions(filteredSymbols(els.marketSearch?.value));
  if (els.marketSearch && symbols.length) {
    els.marketSearch.placeholder = `Search ${symbols.length} pairs (${symbols.slice(0, 3).join(", ")}...)`;
  }
  persistWorkspaceSelection();
}

function buildChart() {
  if (state.chart || !window.LightweightCharts) return;
  state.chart = window.LightweightCharts.createChart(els.marketChartRoot, {
    layout: {
      background: { color: "#071420" },
      textColor: "#8ea6b8",
    },
    width: els.marketChartRoot.clientWidth,
    height: els.marketChartRoot.clientHeight,
    grid: {
      vertLines: { color: "rgba(112, 138, 164, 0.08)" },
      horzLines: { color: "rgba(112, 138, 164, 0.08)" },
    },
    rightPriceScale: {
      borderColor: "rgba(120, 144, 166, 0.14)",
      scaleMargins: { top: 0.08, bottom: 0.28 },
    },
    timeScale: {
      borderColor: "rgba(120, 144, 166, 0.14)",
      timeVisible: true,
      secondsVisible: false,
    },
    crosshair: { mode: 1 },
  });

  state.candleSeries = state.chart.addCandlestickSeries({
    upColor: "#52d6a2",
    downColor: "#ff7d8f",
    wickUpColor: "#52d6a2",
    wickDownColor: "#ff7d8f",
    borderVisible: false,
  });

  state.volumeSeries = state.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
    color: "rgba(22, 206, 196, 0.32)",
  });

  state.fastLineSeries = state.chart.addLineSeries({
    color: "#d0912b",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.slowLineSeries = state.chart.addLineSeries({
    color: "#58a8f2",
    lineWidth: 2,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.bollUpperSeries = state.chart.addLineSeries({
    color: "rgba(111, 188, 255, 0.92)",
    lineWidth: 1,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.bollMiddleSeries = state.chart.addLineSeries({
    color: "rgba(246, 191, 70, 0.88)",
    lineWidth: 1,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.bollLowerSeries = state.chart.addLineSeries({
    color: "rgba(111, 188, 255, 0.92)",
    lineWidth: 1,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.sarSeries = state.chart.addLineSeries({
    color: "rgba(92, 182, 255, 0.92)",
    lineWidth: 1,
    crosshairMarkerVisible: false,
    lastValueVisible: false,
    priceLineVisible: false,
  });

  state.volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  });

  const resizeChart = () => {
    if (!state.chart) return;
    state.chart.applyOptions({
      width: els.marketChartRoot.clientWidth,
      height: els.marketChartRoot.clientHeight,
    });
  };

  window.addEventListener("resize", resizeChart);
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(resizeChart);
    observer.observe(els.marketChartRoot);
  }
}

function applyIndicatorSeries(candles) {
  if (!state.fastLineSeries || !state.slowLineSeries || !state.bollUpperSeries || !state.sarSeries) return;

  state.fastLineSeries.setData([]);
  state.slowLineSeries.setData([]);
  state.bollUpperSeries.setData([]);
  state.bollMiddleSeries.setData([]);
  state.bollLowerSeries.setData([]);
  state.sarSeries.setData([]);

  if (!candles?.length) return;

  if (state.chartIndicator === "MA") {
    state.fastLineSeries.setData(buildMovingAverage(candles, 7));
    state.slowLineSeries.setData(buildMovingAverage(candles, 14));
    return;
  }

  if (state.chartIndicator === "EMA") {
    state.fastLineSeries.setData(buildExponentialMovingAverage(candles, 7));
    state.slowLineSeries.setData(buildExponentialMovingAverage(candles, 14));
    return;
  }

  if (state.chartIndicator === "BOLL") {
    const bands = buildBollingerBands(candles, 20, 2);
    state.bollUpperSeries.setData(bands.upper);
    state.bollMiddleSeries.setData(bands.middle);
    state.bollLowerSeries.setData(bands.lower);
    return;
  }

  if (state.chartIndicator === "SAR") {
    state.sarSeries.setData(buildParabolicSar(candles));
    return;
  }

  if (state.chartIndicator === "MACD") {
    state.fastLineSeries.setData(buildExponentialMovingAverage(candles, 12));
    state.slowLineSeries.setData(buildExponentialMovingAverage(candles, 26));
  }
}

function setChartData(candles) {
  buildChart();
  if (!state.candleSeries || !state.volumeSeries) return;
  state.lastCandles = candles || [];
  state.candleSeries.setData(candles || []);
  const volumeData = (candles || []).map((candle) => ({
    time: candle.time,
    value: candle.volume,
    color: candle.close >= candle.open ? "rgba(82, 214, 162, 0.34)" : "rgba(255, 125, 143, 0.34)",
  }));
  state.volumeSeries.setData(volumeData);
  applyIndicatorSeries(candles || []);
  try {
    state.chart.timeScale().fitContent();
  } catch (error) {
    console.debug(error);
  }
}

function renderSummaryBars(candles) {
  const recentVolumes = (candles || []).slice(-10).map((candle) => Number(candle.volume || 0));
  const maxVolume = Math.max(...recentVolumes, 1);
  els.marketSummaryBars.innerHTML = recentVolumes.length
    ? recentVolumes
        .map((volume) => {
          const height = Math.max(22, Math.round((volume / maxVolume) * 100));
          return `<span style="height:${height}%"></span>`;
        })
        .join("")
    : `<span style="height:32%"></span><span style="height:54%"></span><span style="height:44%"></span><span style="height:72%"></span>`;
}

function renderIndicatorLegend(candles) {
  const latest = candles?.[candles.length - 1] || {};
  const rangeValue =
    latest.high === undefined || latest.low === undefined ? null : Number(latest.high) - Number(latest.low);

  if (state.chartIndicator === "MA") {
    const fastRows = buildMovingAverage(candles || [], 7);
    const slowRows = buildMovingAverage(candles || [], 14);
    const fastValue = fastRows.length ? fastRows[fastRows.length - 1].value : null;
    const slowValue = slowRows.length ? slowRows[slowRows.length - 1].value : null;
    els.marketIndicatorLegend.innerHTML = [
      `<span class="indicator-token indicator-token--amber">MA(7) ${escapeHtml(formatNumber(fastValue, 2))}</span>`,
      `<span class="indicator-token indicator-token--violet">MA(14) ${escapeHtml(formatNumber(slowValue, 2))}</span>`,
      `<span class="indicator-token indicator-token--blue">RANGE ${escapeHtml(formatNumber(rangeValue, 2))}</span>`,
    ].join("");
    return;
  }

  if (state.chartIndicator === "EMA") {
    const fastRows = buildExponentialMovingAverage(candles || [], 7);
    const slowRows = buildExponentialMovingAverage(candles || [], 14);
    const fastValue = fastRows.length ? fastRows[fastRows.length - 1].value : null;
    const slowValue = slowRows.length ? slowRows[slowRows.length - 1].value : null;
    els.marketIndicatorLegend.innerHTML = [
      `<span class="indicator-token indicator-token--amber">EMA(7) ${escapeHtml(formatNumber(fastValue, 2))}</span>`,
      `<span class="indicator-token indicator-token--violet">EMA(14) ${escapeHtml(formatNumber(slowValue, 2))}</span>`,
      `<span class="indicator-token indicator-token--blue">RANGE ${escapeHtml(formatNumber(rangeValue, 2))}</span>`,
    ].join("");
    return;
  }

  if (state.chartIndicator === "BOLL") {
    const bands = buildBollingerBands(candles || [], 20, 2);
    const upper = bands.upper.length ? bands.upper[bands.upper.length - 1].value : null;
    const middle = bands.middle.length ? bands.middle[bands.middle.length - 1].value : null;
    const lower = bands.lower.length ? bands.lower[bands.lower.length - 1].value : null;
    els.marketIndicatorLegend.innerHTML = [
      `<span class="indicator-token indicator-token--blue">BOLL U ${escapeHtml(formatNumber(upper, 2))}</span>`,
      `<span class="indicator-token indicator-token--amber">MID ${escapeHtml(formatNumber(middle, 2))}</span>`,
      `<span class="indicator-token indicator-token--blue">LOW ${escapeHtml(formatNumber(lower, 2))}</span>`,
    ].join("");
    return;
  }

  if (state.chartIndicator === "SAR") {
    const sarRows = buildParabolicSar(candles || []);
    const sarValue = sarRows.length ? sarRows[sarRows.length - 1].value : null;
    els.marketIndicatorLegend.innerHTML = [
      `<span class="indicator-token indicator-token--blue">SAR ${escapeHtml(formatNumber(sarValue, 2))}</span>`,
      `<span class="indicator-token indicator-token--amber">24H High ${escapeHtml(formatNumber(latest.high, 2))}</span>`,
      `<span class="indicator-token indicator-token--violet">24H Low ${escapeHtml(formatNumber(latest.low, 2))}</span>`,
    ].join("");
    return;
  }

  if (state.chartIndicator === "MAVOL") {
    const recentVolumes = (candles || []).slice(-10).map((candle) => Number(candle.volume || 0));
    const volumeNow = recentVolumes.length ? recentVolumes[recentVolumes.length - 1] : null;
    const volumeAverage = recentVolumes.length
      ? recentVolumes.reduce((sum, value) => sum + value, 0) / recentVolumes.length
      : null;
    els.marketIndicatorLegend.innerHTML = [
      `<span class="indicator-token indicator-token--amber">VOL ${escapeHtml(formatCompact(volumeNow))}</span>`,
      `<span class="indicator-token indicator-token--violet">VMA(10) ${escapeHtml(formatCompact(volumeAverage))}</span>`,
      `<span class="indicator-token indicator-token--blue">${escapeHtml(baseAssetFromSymbol(state.symbol))} FLOW</span>`,
    ].join("");
    return;
  }

  const fastRows = buildExponentialMovingAverage(candles || [], 12);
  const slowRows = buildExponentialMovingAverage(candles || [], 26);
  const fastValue = fastRows.length ? fastRows[fastRows.length - 1].value : null;
  const slowValue = slowRows.length ? slowRows[slowRows.length - 1].value : null;
  els.marketIndicatorLegend.innerHTML = [
    `<span class="indicator-token indicator-token--amber">MACD FAST ${escapeHtml(formatNumber(fastValue, 2))}</span>`,
    `<span class="indicator-token indicator-token--violet">MACD SLOW ${escapeHtml(formatNumber(slowValue, 2))}</span>`,
    `<span class="indicator-token indicator-token--blue">TREND VIEW</span>`,
  ].join("");
}

function renderOverviewGrid(snapshot, candles) {
  const latest = candles?.[candles.length - 1] || {};
  const cards = [
    { label: "Open", value: formatNumber(snapshot.candle_open ?? latest.open, 2), tone: null },
    { label: "High", value: formatNumber(snapshot.candle_high ?? latest.high, 2), tone: null },
    { label: "Low", value: formatNumber(snapshot.candle_low ?? latest.low, 2), tone: null },
    { label: "Close", value: formatNumber(snapshot.last_price ?? latest.close, 2), tone: null },
    { label: "24H Change", value: formatPercent(snapshot.price_24h_pcnt), tone: percentToDecimal(snapshot.price_24h_pcnt) },
    { label: "24H High", value: formatNumber(snapshot.high_24h, 2), tone: null },
    { label: "24H Low", value: formatNumber(snapshot.low_24h, 2), tone: null },
    { label: "24H Volume", value: `${formatCompact(snapshot.volume_24h)} ${baseAssetFromSymbol(state.symbol)}`, tone: null },
    { label: "Open Interest", value: formatCompact(snapshot.open_interest), tone: null },
    { label: "Funding / 8h", value: formatRate(snapshot.funding_rate, 4), tone: snapshot.funding_rate },
  ];

  els.marketStats.innerHTML = cards
    .map(
      (card) => `
        <div class="stat-card stat-card--tight ${card.tone > 0 ? "positive" : card.tone < 0 ? "negative" : ""}">
          <span>${escapeHtml(card.label)}</span>
          <strong>${escapeHtml(card.value)}</strong>
        </div>
      `,
    )
    .join("");
}

function renderOrderBook(orderbook) {
  const asks = [...(orderbook?.asks || [])].slice(0, 5).reverse();
  const bids = [...(orderbook?.bids || [])].slice(0, 5);
  const bidSize = bids.reduce((sum, row) => sum + Number(row.size || 0), 0);
  const askSize = asks.reduce((sum, row) => sum + Number(row.size || 0), 0);
  const totalDepth = Math.max(bidSize + askSize, 1);
  const bidPercent = (bidSize / totalDepth) * 100;
  const askPercent = (askSize / totalDepth) * 100;

  els.marketBidRatioLabel.textContent = `Bids ${bidPercent.toFixed(1)}%`;
  els.marketAskRatioLabel.textContent = `Asks ${askPercent.toFixed(1)}%`;
  els.marketBidRatioBar.style.width = `${bidPercent}%`;
  els.marketAskRatioBar.style.width = `${askPercent}%`;

  els.marketMidPriceMain.textContent = formatNumber(orderbook?.mid_price, 2);
  els.marketMid.textContent = formatNumber(orderbook?.mid_price, 2);
  els.marketSpread.textContent =
    orderbook?.spread === null || orderbook?.spread === undefined
      ? "--"
      : `${formatNumber(orderbook.spread, 2)}${orderbook?.mid_price ? ` (${formatPercent(orderbook.spread / orderbook.mid_price)})` : ""}`;

  const rows = [];
  let askRunning = 0;
  let bidRunning = 0;
  asks.forEach((row) => {
    askRunning += Number(row.size || 0);
    rows.push({
      side: "ask",
      price: formatNumber(row.price, 2),
      size: formatNumber(row.size, 3),
      total: formatNumber(askRunning, 3),
    });
  });
  bids.forEach((row) => {
    bidRunning += Number(row.size || 0);
    rows.push({
      side: "bid",
      price: formatNumber(row.price, 2),
      size: formatNumber(row.size, 3),
      total: formatNumber(bidRunning, 3),
    });
  });

  els.marketDepthTable.innerHTML = rows.length
    ? rows
        .map(
          (row) => `
            <div class="depth-table-row ${row.side}">
              <span class="depth-table-price">${row.price}</span>
              <span class="depth-table-size">${row.size}</span>
              <span class="depth-table-total">${row.total}</span>
            </div>
          `,
        )
        .join("")
    : `<div class="depth-table-row empty"><span>Waiting for order book...</span><span>--</span><span>--</span></div>`;
}

function renderTradeBar(snapshot, orderbook, candles) {
  const latest = candles?.[candles.length - 1] || {};
  const fallbackPrice = snapshot.last_price ?? latest.close ?? null;
  const bestBid = orderbook?.bids?.[0]?.price ?? fallbackPrice;
  const bestAsk = orderbook?.asks?.[0]?.price ?? fallbackPrice;
  els.marketBuyPrice.textContent = formatNumber(bestAsk, 1);
  els.marketSellPrice.textContent = formatNumber(bestBid, 1);
  els.marketTradeCenterTitle.textContent = `${String(state.interval || "1m").toUpperCase()} setup`;
  els.marketTradeCenterBase.textContent = baseAssetFromSymbol(state.symbol);
}

function signalUsageText() {
  if (!state.usage) return "-- used today";
  if (state.usage.is_unlimited) return `${state.usage.used || 0} used today`;
  return `${state.usage.used || 0}/${state.usage.limit || 0} used today`;
}

function applyMarketSignalState(payload = null) {
  const signal = payload?.signal || {};
  const instantSignal = payload?.instant_signal || {};
  const instantSide = String(instantSignal.side || "").toUpperCase();
  const useInstantSide = String(signal.signal || "HOLD").toUpperCase() === "HOLD" && ["BUY", "SELL"].includes(instantSide);
  const entryExit = useInstantSide ? {
    entry_price: instantSignal.entry_price,
    stop_loss: instantSignal.stop_loss,
    take_profit: instantSignal.take_profit,
    risk_reward_ratio: instantSignal.risk_reward_ratio,
  } : signal.entry_exit || {};
  const fallbackMarket = state.tickerSnapshots[state.symbol] || {};
  const confidence = Number((useInstantSide ? instantSignal.confidence : signal.confidence) ?? 62);
  const signalText = payload ? displaySignalSide(payload) : "NEUTRAL";
  const signalTone =
    signalText === "BUY" ? "buy" : signalText === "SELL" ? "sell" : signalText === "HOLD" ? "hold" : "hold";
  const supportValue = entryExit.stop_loss ?? entryExit.support ?? fallbackMarket.low_24h ?? fallbackMarket.candle_low ?? null;
  const resistanceValue = entryExit.take_profit ?? entryExit.resistance ?? fallbackMarket.high_24h ?? fallbackMarket.candle_high ?? null;
  const analysis =
    (useInstantSide
      ? `${instantSignal.status || "WAIT"} ${instantSide}. ${(instantSignal.failures || []).slice(0, 2).join(" | ") || instantSignal.reason || "Live crypto side is active."}`
      : "") ||
    signal.reason ||
    "Price is consolidating near key levels. Wait for breakout confirmation.";
  const levelSummary = useInstantSide
    ? `Live crypto ${instantSignal.status || "WAIT"} | ${formatNumber(instantSignal.risk_reward_ratio, 2)}x R/R`
    : signal.adaptive_profile?.suggestion || signal.summary?.setup_quality || `Watch ${state.symbol} reaction`;

  els.marketSignalUsage.textContent = signalUsageText();
  els.marketSignalSide.textContent = signalText === "HOLD" ? "NEUTRAL" : signalText;
  els.marketSignalSide.className = `signal-verdict ${signalTone}`;
  els.marketSignalConfidence.textContent = formatConfidence(confidence);
  els.marketSignalConfidenceBar.style.width = `${Math.min(Math.max(confidence, 8), 100)}%`;
  els.marketSignalAnalysis.textContent = analysis;
  els.marketSignalLevels.textContent = levelSummary;
  els.marketSignalSupport.textContent = formatNumber(supportValue, 2);
  els.marketSignalResistance.textContent = formatNumber(resistanceValue, 2);
}

function renderTickerRail() {
  const featuredSymbols = [state.symbol, ...state.symbols.filter((symbol) => symbol !== state.symbol)].slice(0, 4);
  els.marketTickerRail.innerHTML = featuredSymbols
    .map((symbol) => {
      const snapshot = state.tickerSnapshots[symbol] || {};
      const change = normalizePercent(snapshot.price_24h_pcnt);
      return `
        <button type="button" class="ticker-pill" data-trade-open="markets" data-symbol="${escapeHtml(symbol)}" data-interval="${escapeHtml(state.interval)}">
          <span class="ticker-pill-symbol">${escapeHtml(symbol)}</span>
          <strong class="${change > 0 ? "positive" : change < 0 ? "negative" : ""}">${escapeHtml(formatPercent(snapshot.price_24h_pcnt))}</strong>
          <em>${escapeHtml(formatNumber(snapshot.last_price, 2))}</em>
        </button>
      `;
    })
    .join("");
}

async function refreshTickerRail() {
  const featuredSymbols = [state.symbol, ...state.symbols.filter((symbol) => symbol !== state.symbol)].slice(0, 4);
  if (!featuredSymbols.length) return;
  const results = await Promise.all(
    featuredSymbols.map(async (symbol) => {
      if (symbol === state.symbol && state.tickerSnapshots[symbol]) {
        return [symbol, state.tickerSnapshots[symbol]];
      }
      try {
        const payload = await api(`/api/mobile/market?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(state.interval)}`);
        return [symbol, payload.market || {}];
      } catch (error) {
        console.debug(error);
        return [symbol, state.tickerSnapshots[symbol] || {}];
      }
    }),
  );
  results.forEach(([symbol, snapshot]) => {
    state.tickerSnapshots[symbol] = snapshot;
  });
  renderTickerRail();
}

function renderMarketStats(snapshot, orderbook, candles) {
  const latest = candles?.[candles.length - 1] || {};
  const dayChangeDecimal = percentToDecimal(snapshot.price_24h_pcnt);
  const dayChangeValue = normalizePercent(snapshot.price_24h_pcnt);
  const notionalChange =
    snapshot.last_price === null || snapshot.last_price === undefined || dayChangeDecimal === null
      ? null
      : Number(snapshot.last_price) * Number(dayChangeDecimal);
  const candleDeltaValue =
    snapshot.candle_change ?? ((latest.close ?? 0) - (latest.open ?? latest.close ?? 0));
  const candleDeltaPercent =
    snapshot.candle_change_pct ??
    ((latest.open || latest.close) ? ((Number(latest.close || 0) - Number(latest.open || latest.close || 0)) / Number(latest.open || latest.close || 1)) : null);
  const headlinePrice = snapshot.last_price ?? latest.close;
  const quoteTurnover =
    snapshot.volume_24h === null || snapshot.volume_24h === undefined || headlinePrice === null || headlinePrice === undefined
      ? null
      : Number(snapshot.volume_24h) * Number(headlinePrice);

  els.marketSummarySymbol.textContent = state.symbol;
  els.marketSummaryType.textContent = "Perpetual";
  els.marketSummaryLastPrice.textContent = formatNumber(headlinePrice, 2);
  els.marketSummaryLastChange.textContent = formatPercent(candleDeltaPercent);
  els.marketSummaryDayChange.textContent = formatPercent(snapshot.price_24h_pcnt);
  els.marketSummaryNotionalChange.textContent = formatSignedNumber(notionalChange, 2);
  els.marketSummaryVolume.textContent = formatCompact(snapshot.volume_24h ?? latest.volume);
  els.marketSummaryVolumeAsset.textContent = baseAssetFromSymbol(state.symbol);
  els.marketHeadlineUsd.textContent = headlinePrice === null || headlinePrice === undefined ? "~ -- USD" : `~ ${formatNumber(headlinePrice, 2)} USD`;
  els.marketCompactHigh.textContent = formatNumber(snapshot.high_24h ?? latest.high, 2);
  els.marketCompactLow.textContent = formatNumber(snapshot.low_24h ?? latest.low, 2);
  els.marketCompactTurnover.textContent = quoteTurnover === null ? "--" : formatCompact(quoteTurnover);

  applySignedTone(els.marketSummaryLastChange, candleDeltaValue);
  applySignedTone(els.marketSummaryDayChange, dayChangeValue);
  applySignedTone(els.marketSummaryNotionalChange, notionalChange);

  renderSummaryBars(candles);
  renderIndicatorLegend(candles);
  renderOverviewGrid(snapshot, candles);
  renderOrderBook(orderbook);
  renderTradeBar(snapshot, orderbook, candles);
}

function renderSignalCard(payload) {
  const result = payload?.signal || {};
  const instantSignal = payload?.instant_signal || {};
  const instantSide = String(instantSignal.side || "").toUpperCase();
  const useInstantSide = String(result.signal || "HOLD").toUpperCase() === "HOLD" && ["BUY", "SELL"].includes(instantSide);
  const entryExit = useInstantSide ? {
    entry_price: instantSignal.entry_price,
    stop_loss: instantSignal.stop_loss,
    take_profit: instantSignal.take_profit,
    risk_reward_ratio: instantSignal.risk_reward_ratio,
  } : result.entry_exit || {};
  const signalLabel = displaySignalSide(payload);
  const signalSide = signalLabel.toLowerCase();
  const capturedAt = payload?.captured_at || new Date().toISOString();
  const tags = [];
  if (result.trade_style) tags.push(result.trade_style);
  if (useInstantSide) tags.push(`Live crypto ${instantSignal.status || "WAIT"}`);
  if (result.adaptive_profile?.suggestion) tags.push(result.adaptive_profile.suggestion);
  if (result.summary?.setup_quality) tags.push(`Setup ${result.summary.setup_quality}`);
  if (entryExit.adaptive_min_rr_ratio) tags.push(`Min RR ${Number(entryExit.adaptive_min_rr_ratio).toFixed(2)}x`);
  if (payload?.broker?.connected) tags.push(`${payload.broker.broker_name || "Broker"} linked`);
  if (payload?.usage) tags.push(`${signalUsageText()}`);
  const signalCallout = useInstantSide
    ? `${instantSignal.status || "WAIT"} ${instantSide}. ${(instantSignal.failures || []).slice(0, 3).join(" | ") || instantSignal.reason || result.reason || "Live crypto side is active."}`
    : result.reason || "Finwise AI is waiting for a stronger setup.";

  els.deskSignalCard.innerHTML = `
    <div class="desk-signal-head">
      <div>
        <div class="desk-signal-kicker">AI Signal Ready</div>
        <div class="desk-signal-title-row">
          <div class="signal-side ${signalSide}">${escapeHtml(signalLabel)}</div>
          <span class="desk-signal-market">${escapeHtml(payload?.symbol || state.symbol)} | ${escapeHtml(payload?.interval || state.interval)}</span>
        </div>
        <div class="desk-signal-time">${escapeHtml(formatHistoryDate(capturedAt))}</div>
      </div>
      <div class="metric-card">
        <span>Confidence</span>
        <strong>${escapeHtml(formatConfidence(useInstantSide ? instantSignal.confidence : result.confidence))}</strong>
      </div>
    </div>
    <div class="desk-signal-callout">${escapeHtml(signalCallout)}</div>
    <div class="signal-grid">
      <div class="signal-metric">
        <span>Entry</span>
        <strong>${escapeHtml(formatNumber(entryExit.entry_price, 4))}</strong>
      </div>
      <div class="signal-metric">
        <span>Target</span>
        <strong>${escapeHtml(formatNumber(entryExit.take_profit, 4))}</strong>
      </div>
      <div class="signal-metric">
        <span>Stop</span>
        <strong>${escapeHtml(formatNumber(entryExit.stop_loss, 4))}</strong>
      </div>
      <div class="signal-metric">
        <span>Risk / Reward</span>
        <strong>${escapeHtml(formatNumber(entryExit.risk_reward_ratio, 2))}x</strong>
      </div>
    </div>
    <div class="signal-tags">${tags.map((tag) => `<span class="signal-tag">${escapeHtml(tag)}</span>`).join("")}</div>
    <div class="desk-signal-actions">
      <button
        type="button"
        class="trade-action desk-action"
        data-trade-open="markets"
        data-symbol="${escapeHtml(payload?.symbol || state.symbol)}"
        data-interval="${escapeHtml(payload?.interval || state.interval)}"
      >
        Back To Market
      </button>
      <button type="button" class="trade-action desk-action" data-trade-open="settings">Open Routes</button>
    </div>
  `;
  setHidden(els.deskSignalCard, false);
  setHidden(els.deskSignalEmpty, true);
  applyMarketSignalState(payload);
}

function storeSignal(payload) {
  const enrichedPayload = {
    ...payload,
    symbol: payload?.symbol || state.symbol,
    interval: payload?.interval || state.interval,
    captured_at: payload?.captured_at || new Date().toISOString(),
  };
  state.lastSignal = enrichedPayload;
  try {
    localStorage.setItem("finwise-mobile-last-signal", JSON.stringify(enrichedPayload));
  } catch (error) {
    console.debug(error);
  }
}

function clearStoredSignal(message = "") {
  state.lastSignal = null;
  try {
    localStorage.removeItem("finwise-mobile-last-signal");
  } catch (error) {
    console.debug(error);
  }
  applyMarketSignalState();
  if (els.deskSignalCard) setHidden(els.deskSignalCard, true);
  if (els.deskSignalEmpty) {
    setHidden(els.deskSignalEmpty, false);
    els.deskSignalEmpty.innerHTML = renderDeskEmptyState(message);
  }
}

function loadStoredSignal() {
  try {
    const raw = localStorage.getItem("finwise-mobile-last-signal");
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed?.signal) {
      if (!storedSignalIsFresh(parsed)) {
        localStorage.removeItem("finwise-mobile-last-signal");
        applyMarketSignalState();
        return;
      }
      state.lastSignal = parsed;
      if (lastSignalMatchesSelection(parsed)) {
        renderSignalCard(parsed);
      } else {
        applyMarketSignalState();
      }
      return;
    }
  } catch (error) {
    console.debug(error);
  }
  applyMarketSignalState();
}

function renderDeskSummaryCard(data) {
  const snapshot = data.market?.snapshot || {};
  const selectedSymbol = data.market?.symbol || state.symbol;
  const selectedInterval = data.market?.interval || state.interval;
  const engineReady = Boolean(data.market?.engine_status?.ready);
  const dayChange = normalizePercent(snapshot.price_24h_pcnt);
  const tradeStyleLabel = data.trade_style?.label || fallbackTradeStyleLabel(data.trade_style?.selected || state.tradeStyle);
  const signalLabel = lastSignalMatchesSelection() ? displaySignalSide(state.lastSignal) : "Awaiting";
  const signalChipLabel = signalLabel === "Awaiting" ? "Awaiting signal" : `${signalLabel} loaded`;

  return `
    <div class="desk-hero-shell">
      <div class="desk-hero-top">
        <div>
          <div class="desk-kicker">Trade Desk</div>
          <div class="desk-title">${escapeHtml(selectedSymbol)} | ${escapeHtml(selectedInterval)}</div>
          <div class="desk-copy">Finwise sends the AI signal automatically when your connection is online and Telegram notifications are allowed. Manual refresh stays here as a fallback.</div>
        </div>
        <div class="info-chip-row">
          ${renderStatusChip(engineReady ? "Feed ready" : "Feed warming", engineReady ? "" : "warm")}
          ${renderStatusChip(signalsLeftLabel(data.usage))}
          ${renderStatusChip(signalChipLabel, signalLabel === "BUY" ? "" : signalLabel === "SELL" ? "offline" : "warm")}
        </div>
      </div>
      <div class="desk-context-grid">
        <div class="desk-context-card">
          <span>Last Price</span>
          <strong>${escapeHtml(formatNumber(snapshot.last_price, 2))}</strong>
        </div>
        <div class="desk-context-card">
          <span>24h Change</span>
          <strong class="${dayChange > 0 ? "positive" : dayChange < 0 ? "negative" : ""}">${escapeHtml(formatPercent(snapshot.price_24h_pcnt))}</strong>
        </div>
        <div class="desk-context-card">
          <span>Balance Basis</span>
          <strong>$${escapeHtml(formatNumber(els.deskBalance?.value || 10000, 0))}</strong>
        </div>
        <div class="desk-context-card">
          <span>Style</span>
          <strong>${escapeHtml(tradeStyleLabel)}</strong>
        </div>
      </div>
      <div class="desk-action-row">
        <button
          type="button"
          class="trade-action desk-action"
          data-trade-open="markets"
          data-symbol="${escapeHtml(selectedSymbol)}"
          data-interval="${escapeHtml(selectedInterval)}"
        >
          Review Market
        </button>
        <button type="button" class="trade-action desk-action" data-trade-open="settings">Open Routes</button>
      </div>
    </div>
  `;
}

function renderDeskBrokerSnapshot(data) {
  const broker = data.broker || {};
  return `
    <div class="desk-broker-shell">
      <div class="desk-kicker">Broker Context</div>
      <div class="desk-title">${escapeHtml(broker.connected ? `${broker.broker_name} linked` : "Broker handoff")}</div>
      <div class="desk-copy">
        ${escapeHtml(
          broker.connected
            ? "Saved broker context is attached here so you can move from AI read to execution routing with less friction."
            : "Connect or refresh a broker from desktop if you want execution routing to appear here on mobile.",
        )}
      </div>
      <div class="desk-context-grid">
        <div class="desk-context-card">
          <span>Status</span>
          <strong>${escapeHtml(broker.status || "Offline")}</strong>
        </div>
        <div class="desk-context-card">
          <span>Method</span>
          <strong>${escapeHtml((broker.method || "none").toUpperCase())}</strong>
        </div>
        <div class="desk-context-card">
          <span>Reconnect</span>
          <strong>${escapeHtml(broker.reconnect_required ? "Required" : "Ready")}</strong>
        </div>
        <div class="desk-context-card">
          <span>Signal Route</span>
          <strong>${escapeHtml(broker.connected ? "Execution aware" : "Signal only")}</strong>
        </div>
      </div>
      <div class="info-chip-row">
        ${renderStatusChip(broker.connected ? "Saved link" : "No broker", broker.connected ? "" : "offline")}
        ${renderStatusChip(broker.reconnect_required ? "Reconnect required" : "Session ready", broker.reconnect_required ? "warm" : "")}
      </div>
    </div>
  `;
}

function renderDeskEmptyState(message = "") {
  return `
    <div class="desk-empty-shell">
      <div class="desk-kicker">AI Signal</div>
      <div class="desk-empty-title">Ready to analyze ${escapeHtml(state.symbol)} on ${escapeHtml(state.interval)}</div>
      <div class="desk-empty-copy">
        ${escapeHtml(
          message ||
            `Trade Desk now keeps the latest AI read attached to execution and routing context. Pick your ${fallbackTradeStyleLabel(state.tradeStyle)} style, set your balance basis, and Finwise will send the signal when Telegram notifications are allowed.`,
        )}
      </div>
      <div class="info-chip-row">
        ${renderStatusChip(state.usage?.is_unlimited ? "Unlimited plan" : `${signalsLeftLabel(state.usage)} left`)}
        ${renderStatusChip("Desk workflow", "warm")}
      </div>
    </div>
  `;
}

function syncHomeErrorState(message) {
  els.homeSyncTitle.textContent = "Sync paused";
  els.homeSyncMessage.textContent = message;
  els.homeSyncPill.textContent = "Retry";
  els.homeSyncPill.classList.add("warm");
  els.homeHistoryList.innerHTML = renderInlineEmpty("Home data could not be loaded right now.");
}

function syncDeskErrorState(message) {
  els.deskSummary.innerHTML = renderInlineEmpty(message);
  els.deskBrokerCard.innerHTML = renderInlineEmpty("Broker context is temporarily unavailable.");
  setHidden(els.deskSignalCard, true);
  setHidden(els.deskSignalEmpty, false);
  els.deskSignalEmpty.innerHTML = renderDeskEmptyState("Signal context is temporarily unavailable. Try refreshing the desk.");
}

function syncJournalErrorState(message) {
  els.journalMetrics.innerHTML = renderMetricGrid({});
  els.journalList.innerHTML = renderInlineEmpty(message);
}

function syncSettingsErrorState(message) {
  els.settingsAccount.innerHTML = renderInlineEmpty(message);
  els.settingsSecurity.innerHTML = renderInlineEmpty("Security settings are temporarily unavailable.");
}

async function loadHome({ silent = false } = {}) {
  const ticket = nextRequestTicket("home");
  setPageLoading("home", true, pageLoadingLabel("home"));
  try {
    const [dashboard, journal, marketPayload] = await Promise.all([
      api("/api/mobile/dashboard"),
      api("/api/mobile/journal"),
      api(`/api/mobile/market?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}`),
    ]);
    if (!isActiveRequestTicket("home", ticket)) return;
    updateTopSummary(state.session, dashboard.usage, dashboard.broker);
    state.tickerSnapshots[marketPayload.symbol] = marketPayload.market || {};
    renderHomeDashboardPayload({ dashboard, journal, marketPayload });
  } catch (error) {
    if (!isActiveRequestTicket("home", ticket)) return;
    syncHomeErrorState(error.message || "Dashboard data is unavailable.");
    if (!silent) throw error;
  } finally {
    if (isActiveRequestTicket("home", ticket)) {
      setPageLoading("home", false);
    }
  }
}

async function loadMarket(options = {}) {
  return loadMarketView(options);
}

async function loadDesk({ silent = false } = {}) {
  const ticket = nextRequestTicket("desk");
  setPageLoading("desk", true, pageLoadingLabel("desk"));
  try {
    const data = await api(
      `/api/mobile/desk?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}&trade_style=${encodeURIComponent(state.tradeStyle)}`,
    );
    if (!isActiveRequestTicket("desk", ticket)) return;
    syncTradeStyleControl(data.trade_style || {});
    persistWorkspaceSelection();
    updateTopSummary(state.session, data.usage, data.broker);
    els.deskSummary.innerHTML = renderDeskSummaryCard(data);
    els.deskBrokerCard.innerHTML = renderDeskBrokerSnapshot(data);
    if (lastSignalMatchesSelection()) {
      renderSignalCard(state.lastSignal);
    } else {
      setHidden(els.deskSignalCard, true);
      setHidden(els.deskSignalEmpty, false);
      els.deskSignalEmpty.innerHTML = renderDeskEmptyState();
    }
  } catch (error) {
    if (!isActiveRequestTicket("desk", ticket)) return;
    syncDeskErrorState(error.message || "Desk data is unavailable.");
    if (!silent) throw error;
  } finally {
    if (isActiveRequestTicket("desk", ticket)) {
      setPageLoading("desk", false);
    }
  }
}

async function loadJournal({ silent = false } = {}) {
  const ticket = nextRequestTicket("journal");
  setPageLoading("journal", true, pageLoadingLabel("journal"));
  try {
    const statusQuery = state.journalStatus === "all" ? "" : `?status=${encodeURIComponent(state.journalStatus)}`;
    const data = await api(`/api/mobile/journal${statusQuery}`);
    if (!isActiveRequestTicket("journal", ticket)) return;
    els.journalMetrics.innerHTML = renderMetricGrid(data.metrics || {});
    els.journalList.innerHTML = renderTradeCards(data.trades || []);
  } catch (error) {
    if (!isActiveRequestTicket("journal", ticket)) return;
    syncJournalErrorState(error.message || "Journal data is unavailable.");
    if (!silent) throw error;
  } finally {
    if (isActiveRequestTicket("journal", ticket)) {
      setPageLoading("journal", false);
    }
  }
}

function applySettingsPayload(data) {
  state.notifications = data.notifications || state.notifications;
  els.settingsAccount.innerHTML = renderInfoCard(
    "Workspace account",
    "Tune the channels that should light up when Finwise spots a trade worth your attention.",
    [
      { label: "Username", value: data.account?.username || "--" },
      { label: "Email", value: data.account?.email || "--" },
      { label: "Phone", value: data.account?.phone || "--" },
      { label: "Plan", value: data.account?.premium ? "Premium" : "Free" },
    ],
    [
      renderStatusChip(data.broker?.connected ? `${data.broker.broker_name}` : "No broker", data.broker?.connected ? "" : "offline"),
    ],
  );

  els.settingsPhone.value = data.account?.phone || "";
  els.settingsTelegramChatId.value = data.notifications?.telegram_chat_id || "";
  els.settingsWhatsappEnabled.checked = Boolean(data.notifications?.whatsapp_enabled);
  els.settingsTelegramEnabled.checked = Boolean(data.notifications?.telegram_enabled);
  syncTelegramConnectUi(data.notifications || {});

  els.prefBuySignals.checked = Boolean(data.preferences?.notify_buy_signals);
  els.prefSellSignals.checked = Boolean(data.preferences?.notify_sell_signals);
  els.prefSignalUpdates.checked = Boolean(data.preferences?.notify_signal_updates);
  els.prefHighConfidence.checked = Boolean(data.preferences?.notify_high_confidence_only);
  els.prefMarketDigest.checked = Boolean(data.preferences?.notify_market_digest);
  els.prefAuthenticator.checked = Boolean(data.security?.authenticator_2fa);
  els.prefSmsVerification.checked = Boolean(data.security?.sms_verification);
  els.prefLoginAlerts.checked = Boolean(data.security?.login_alerts);

  els.settingsSecurity.innerHTML = renderInfoCard(
    "Security posture",
    "Keep your access clean while your alert cockpit stays ready for the next move.",
    [
      { label: "Authenticator", value: data.security?.authenticator_2fa ? "Enabled" : "Off" },
      { label: "SMS Verify", value: data.security?.sms_verification ? "Enabled" : "Off" },
      { label: "Login Alerts", value: data.security?.login_alerts ? "Enabled" : "Off" },
      { label: "Broker Status", value: data.broker?.status || "Offline" },
    ],
    [
      renderStatusChip(data.notifications?.whatsapp_enabled ? "WhatsApp on" : "WhatsApp off"),
      renderStatusChip(data.notifications?.telegram_enabled ? "Telegram on" : "Telegram off"),
      renderStatusChip(data.security?.login_alerts ? "Login alerts on" : "Login alerts off"),
    ],
  );
}

async function loadSettings({ silent = false } = {}) {
  const ticket = nextRequestTicket("settings");
  setPageLoading("settings", true, pageLoadingLabel("settings"));
  try {
    const data = await api("/api/mobile/settings");
    if (!isActiveRequestTicket("settings", ticket)) return;
    applySettingsPayload(data);
  } catch (error) {
    if (!isActiveRequestTicket("settings", ticket)) return;
    syncSettingsErrorState(error.message || "Settings could not be loaded.");
    if (!silent) throw error;
  } finally {
    if (isActiveRequestTicket("settings", ticket)) {
      setPageLoading("settings", false);
    }
  }
}

const loadMarketView = async function loadMarketView({ silent = false } = {}) {
  const ticket = nextRequestTicket("markets");
  setPageLoading("markets", true, pageLoadingLabel("markets"));
  try {
    const data = await api(`/api/mobile/market?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}`);
    if (!isActiveRequestTicket("markets", ticket)) return;
    state.symbol = data.symbol;
    state.interval = data.interval;
    ensureControls(data);
    const candles = data.candles || [];
    setChartData(candles);
    const snapshot = data.market || {};
    const latest = candles[candles.length - 1] || {};
    const previous = candles[candles.length - 2] || latest;
    const candleChange =
      latest.close === undefined || previous.close === undefined ? null : Number(latest.close) - Number(previous.close);
    const candleChangePct =
      latest.close === undefined || previous.close === undefined || !Number(previous.close)
        ? null
        : (Number(latest.close) - Number(previous.close)) / Number(previous.close);

    setActiveMarketView(state.marketView || "market-chart-section");
    els.marketChartTitle.textContent = `${data.symbol} Perpetual - ${data.interval}`;
    els.marketChartOhlc.textContent = `O ${formatNumber(latest.open, 2)}  H ${formatNumber(latest.high, 2)}  L ${formatNumber(latest.low, 2)}  C ${formatNumber(latest.close, 2)}  ${formatSignedNumber(candleChange, 2)} (${formatPercent(candleChangePct)})`;
    els.marketLiveStatus.classList.toggle("warm", !data.engine_status?.ready);
    els.marketLiveStatus.querySelector("span:last-child").textContent = data.engine_status?.ready ? "Live" : "Warming";
    els.marketFeedBanner.textContent = data.engine_status?.message || "Live market feed is connected.";
    if (els.headerLivePill) {
      els.headerLivePill.classList.toggle("warm", !data.engine_status?.ready);
      els.sessionBrokerStatus.textContent = data.engine_status?.ready ? "Live Feed" : "Warming";
    }

    state.tickerSnapshots[data.symbol] = snapshot;
    renderMarketStats(snapshot, data.orderbook || {}, candles);
    if (!lastSignalMatchesSelection()) {
      applyMarketSignalState();
    } else {
      applyMarketSignalState(state.lastSignal);
    }
    refreshTickerRail().catch((error) => console.debug(error));
  } catch (error) {
    if (!isActiveRequestTicket("markets", ticket)) return;
    els.marketLiveStatus.classList.add("warm");
    els.marketLiveStatus.querySelector("span:last-child").textContent = "Retry";
    els.marketFeedBanner.textContent = error.message || "Market data is temporarily unavailable.";
    if (els.headerLivePill) {
      els.headerLivePill.classList.add("warm");
      els.sessionBrokerStatus.textContent = "Retrying";
    }
    if (!silent) throw error;
  } finally {
    if (isActiveRequestTicket("markets", ticket)) {
      setPageLoading("markets", false);
    }
  }
};

function openTradeDeskFromMarket() {
  persistWorkspaceSelection();
  jumpToWorkspace("desk", state.symbol, state.interval);
  showToast("Trade Desk is ready. Telegram signals can send automatically.");
}

async function requestSignal(button = null, options = {}) {
  const automatic = Boolean(options.automatic);
  const activeButton = button || (automatic ? null : els.marketSignalButton || els.deskSignalButton);
  const originalLabel = activeButton?.textContent || "Send Signal Now";
  if (els.deskTradeStyle?.value) {
    state.tradeStyle = els.deskTradeStyle.value;
    persistWorkspaceSelection();
  }
  if (activeButton) {
    activeButton.disabled = true;
    activeButton.textContent = "Analyzing...";
  }
  try {
    const payload = await api("/api/mobile/signal", {
      method: "POST",
      body: {
        symbol: state.symbol,
        interval: state.interval,
        trade_style: state.tradeStyle,
        balance_basis: Number(els.deskBalance.value || 10000),
      },
    });
    const enrichedPayload = {
      ...payload,
      symbol: state.symbol,
      interval: state.interval,
      captured_at: new Date().toISOString(),
    };
    updateTopSummary(state.session, enrichedPayload.usage, enrichedPayload.broker);
    storeSignal(enrichedPayload);
    renderSignalCard(enrichedPayload);
    els.deskSummary.innerHTML = renderDeskSummaryCard({
      market: {
        symbol: state.symbol,
        interval: state.interval,
        snapshot: state.tickerSnapshots[state.symbol] || {},
        engine_status: { ready: true },
      },
      usage: enrichedPayload.usage,
      broker: enrichedPayload.broker,
      trade_style: {
        selected: state.tradeStyle,
        label: enrichedPayload.signal?.trade_style || fallbackTradeStyleLabel(state.tradeStyle),
      },
    });
    if (options.showReadyToast !== false) {
      showToast("AI signal is ready.");
    }
    return enrichedPayload;
  } catch (error) {
    if (options.showErrorToast !== false) {
      showToast(error.message, "error");
    }
    if (options.rethrow) {
      throw error;
    }
    return null;
  } finally {
    if (activeButton) {
      activeButton.disabled = false;
      activeButton.textContent = originalLabel;
    }
  }
}

async function refreshCurrentPage({ silent = false, showMessage = false } = {}) {
  const activePage = state.page;
  if (activePage === "home") await loadHome({ silent });
  if (activePage === "markets") await refreshMarketSurface({ restartTimer: true, silent });
  if (activePage === "desk") await loadDesk({ silent });
  if (activePage === "journal") await loadJournal({ silent });
  if (activePage === "settings") await loadSettings({ silent });
  if (showMessage) {
    const messages = {
      home: "Dashboard refreshed.",
      markets: "Market refreshed.",
      desk: "Desk refreshed.",
      journal: "Journal refreshed.",
      settings: "Settings refreshed.",
    };
    showToast(messages[activePage] || "Refreshed.");
  }
}

function jumpToWorkspace(targetPage, symbol = "", interval = "") {
  if (symbol) state.symbol = symbol;
  if (interval) state.interval = interval;
  persistWorkspaceSelection();
  if (targetPage === state.page) {
    if (targetPage === "markets") {
      refreshCurrentPage().catch((error) => showToast(error.message, "error"));
      return;
    }
    if (targetPage === "desk") {
      refreshCurrentPage().catch((error) => showToast(error.message, "error"));
      return;
    }
  }
  activatePage(targetPage).catch((error) => showToast(error.message, "error"));
}

function startLiveRefresh() {
  clearInterval(state.liveTimer);
  if (!state.session) return;
  if (state.page === "markets") {
    state.liveTimer = setInterval(() => {
      loadMarket({ silent: true }).catch((error) => console.debug(error));
    }, 5000);
  } else if (state.page === "desk") {
    state.liveTimer = setInterval(() => {
      loadDesk({ silent: true }).catch((error) => console.debug(error));
    }, 7000);
  } else {
    state.liveTimer = null;
  }
}

async function refreshMarketSurface({ restartTimer = false, silent = false } = {}) {
  syncUrl();
  await loadMarket({ silent });
  if (restartTimer) {
    startLiveRefresh();
  }
}

async function activatePage(page) {
  state.page = ["home", "markets", "desk", "journal", "settings"].includes(page) ? page : "markets";
  if (els.appView) {
    els.appView.setAttribute("data-active-page", state.page);
  }
  els.pages.forEach((section) => {
    section.classList.toggle("is-active", section.dataset.page === state.page);
  });
  els.navItems.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.pageTarget === state.page);
  });
  syncUrl();
  startLiveRefresh();
  if (state.page === "home") await loadHome();
  if (state.page === "markets") await loadMarket();
  if (state.page === "desk") await loadDesk();
  if (state.page === "journal") await loadJournal();
  if (state.page === "settings") await loadSettings();
}

function handleAuthSuccess(data, message = "") {
  state.session = data.user || null;
  state.usage = data.usage || null;
  state.broker = data.broker || null;
  state.notifications = data.notifications || state.notifications;
  state.symbol = state.symbol || data.defaults?.symbol || "BTCUSDT";
  state.interval = state.interval || data.defaults?.interval || "5m";
  ensureControls(data);
  setHidden(els.authView, true);
  setHidden(els.appView, false);
  setAuthMessage("");
  updateTopSummary(data.user, data.usage, data.broker);
  loadStoredSignal();
  activatePage(state.page).catch((error) => showToast(error.message, "error"));
  scheduleAutomaticTelegramSignal({ delayMs: 1200 });
  if (message) showToast(message);
}

async function bootstrap() {
  try {
    const data = await api("/api/mobile/bootstrap");
    state.symbol = state.symbol || data.defaults?.symbol || "BTCUSDT";
    state.interval = state.interval || data.defaults?.interval || "5m";
    ensureControls(data);
    if (data.authenticated) {
      handleAuthSuccess(data);
      return;
    }
    applyLoggedOut(data);
    if (data.email_auth && !data.email_auth.enabled && state.authPanel !== "login") {
      setAuthMessage(data.email_auth.message);
    }
  } catch (error) {
    applyLoggedOut();
    setAuthMessage(error.message, "error");
  }
}

els.authSwitches.forEach((button) => {
  button.addEventListener("click", () => {
    setAuthMessage("");
    switchAuthPanel(button.dataset.authPanel);
  });
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setAuthMessage("");
  try {
    const data = await api("/api/mobile/auth/login", {
      method: "POST",
      body: {
        username: els.loginUsername.value.trim(),
        password: els.loginPassword.value,
        remember_me: els.loginRemember.checked,
      },
    });
    handleAuthSuccess(data, data.message || "Signed in.");
  } catch (error) {
    setAuthMessage(error.message, "error");
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setAuthMessage("");
  try {
    if (!state.registerPending) {
      const response = await api("/api/mobile/auth/register/start", {
        method: "POST",
        body: {
          username: els.registerUsername.value.trim(),
          email: els.registerEmail.value.trim(),
          phone: els.registerPhone.value.trim(),
          password: els.registerPassword.value,
        },
      });
      state.registerPending = true;
      setHidden(els.registerOtpBlock, false);
      els.registerSubmit.textContent = "Verify And Create Workspace";
      setStageBanner(els.registerStageBanner, response.message || "Verification code sent.");
      showToast(response.message || "Verification code sent.");
      return;
    }
    const data = await api("/api/mobile/auth/register/complete", {
      method: "POST",
      body: {
        username: els.registerUsername.value.trim(),
        otp: els.registerOtp.value.trim(),
        remember_me: els.registerRemember.checked,
      },
    });
    handleAuthSuccess(data, data.message || "Workspace created.");
  } catch (error) {
    setAuthMessage(error.message, "error");
  }
});

els.resetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setAuthMessage("");
  try {
    if (!state.resetPending) {
      const response = await api("/api/mobile/auth/password/request", {
        method: "POST",
        body: {
          username: els.resetUsername.value.trim(),
          email: els.resetEmail.value.trim(),
        },
      });
      state.resetPending = true;
      setHidden(els.resetOtpBlock, false);
      els.resetSubmit.textContent = "Reset Password And Sign In";
      setStageBanner(els.resetStageBanner, response.message || "Reset code sent.");
      showToast(response.message || "Reset code sent.");
      return;
    }
    const data = await api("/api/mobile/auth/password/reset", {
      method: "POST",
      body: {
        username: els.resetUsername.value.trim(),
        email: els.resetEmail.value.trim(),
        otp: els.resetOtp.value.trim(),
        new_password: els.resetPassword.value,
        remember_me: els.resetRemember.checked,
      },
    });
    handleAuthSuccess(data, data.message || "Password updated.");
  } catch (error) {
    setAuthMessage(error.message, "error");
  }
});

els.navItems.forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.pageTarget === state.page) {
      refreshCurrentPage({ showMessage: true }).catch((error) => showToast(error.message, "error"));
      return;
    }
    activatePage(button.dataset.pageTarget).catch((error) => showToast(error.message, "error"));
  });
});

els.homeRefresh.addEventListener("click", () => {
  refreshCurrentPage({ showMessage: true }).catch((error) => showToast(error.message, "error"));
});

els.homeSearch?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  const [firstMatch] = filteredSymbols(els.homeSearch.value);
  if (firstMatch) {
    state.symbol = firstMatch;
  }
  persistWorkspaceSelection();
  jumpToWorkspace("markets", state.symbol, state.interval);
});

els.homeFilterButton?.addEventListener("click", () => {
  const [firstMatch] = filteredSymbols(els.homeSearch?.value);
  if (firstMatch) {
    state.symbol = firstMatch;
  }
  persistWorkspaceSelection();
  jumpToWorkspace("markets", state.symbol, state.interval);
});

els.homePeriodSelect?.addEventListener("change", () => {
  state.homePeriod = els.homePeriodSelect.value || "24H";
  persistWorkspaceSelection();
  syncUrl();
  if (state.page === "home") {
    loadHome().catch((error) => showToast(error.message, "error"));
  }
});

els.homeNotificationButton?.addEventListener("click", () => {
  if (!telegramNotificationsReady()) {
    showToast("Connect and enable Telegram alerts first.", "error");
    jumpToWorkspace("settings");
    return;
  }
  if (automaticSignalAlreadySent()) {
    showToast("Today's automatic Telegram signal has already been sent.");
    return;
  }
  removeStoredValue(AUTO_SIGNAL_PERMISSION_KEY);
  scheduleAutomaticTelegramSignal({
    delayMs: 0,
    forcePermissionPrompt: true,
    showToasts: true,
  });
});

els.marketSearchToggle?.addEventListener("click", () => {
  const shouldHide = !els.marketSearchShell.classList.contains("hidden");
  setHidden(els.marketSearchShell, shouldHide);
  if (!shouldHide) {
    window.setTimeout(() => els.marketSearch.focus(), 40);
  }
});

els.marketSearch.addEventListener("input", () => {
  renderSymbolOptions(filteredSymbols(els.marketSearch.value));
});

els.marketSearch.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  const [firstMatch] = filteredSymbols(els.marketSearch.value);
  if (!firstMatch) return;
  state.symbol = firstMatch;
  persistWorkspaceSelection();
  renderSymbolOptions(filteredSymbols(els.marketSearch.value));
  refreshMarketSurface().catch((error) => showToast(error.message, "error"));
});

els.marketSymbol.addEventListener("change", () => {
  state.symbol = els.marketSymbol.value;
  persistWorkspaceSelection();
  clearStoredSignal(`Ready to analyze ${state.symbol} on ${state.interval}.`);
  refreshMarketSurface({ restartTimer: true }).catch((error) => showToast(error.message, "error"));
  scheduleAutomaticTelegramSignal({ delayMs: 700 });
});

els.marketInterval.addEventListener("change", () => {
  state.interval = els.marketInterval.value;
  persistWorkspaceSelection();
  clearStoredSignal(`Ready to analyze ${state.symbol} on ${state.interval}.`);
  refreshMarketSurface({ restartTimer: true }).catch((error) => showToast(error.message, "error"));
  scheduleAutomaticTelegramSignal({ delayMs: 700 });
});

els.marketIndicatorToggle?.addEventListener("click", () => {
  toggleIndicatorDrawer();
});

els.deskRefresh.addEventListener("click", () => {
  refreshCurrentPage({ showMessage: true }).catch((error) => showToast(error.message, "error"));
});

els.deskBalance?.addEventListener("input", () => {
  if (state.page !== "desk") return;
  els.deskSummary.innerHTML = renderDeskSummaryCard({
    market: {
      symbol: state.symbol,
      interval: state.interval,
      snapshot: state.tickerSnapshots[state.symbol] || {},
      engine_status: { ready: true },
    },
    usage: state.usage,
    broker: state.broker,
  });
});

els.deskTradeStyle?.addEventListener("change", () => {
  state.tradeStyle = els.deskTradeStyle.value || "day_trade";
  persistWorkspaceSelection();
  syncUrl();
  clearStoredSignal(`${fallbackTradeStyleLabel(state.tradeStyle)} selected. Finwise is checking for a fresh signal.`);
  scheduleAutomaticTelegramSignal({ delayMs: 350 });
  if (state.page !== "desk") return;
  els.deskSummary.innerHTML = renderDeskSummaryCard({
    market: {
      symbol: state.symbol,
      interval: state.interval,
      snapshot: state.tickerSnapshots[state.symbol] || {},
      engine_status: { ready: true },
    },
    usage: state.usage,
    broker: state.broker,
    trade_style: {
      selected: state.tradeStyle,
      label: fallbackTradeStyleLabel(state.tradeStyle),
    },
  });
});

els.deskSignalButton.addEventListener("click", () => {
  requestSignal(els.deskSignalButton);
});

els.marketSignalButton.addEventListener("click", () => {
  openTradeDeskFromMarket();
});

els.journalFilters.forEach((button) => {
  button.addEventListener("click", () => {
    state.journalStatus = button.dataset.journalStatus || "all";
    els.journalFilters.forEach((chip) => {
      chip.classList.toggle("is-active", chip.dataset.journalStatus === state.journalStatus);
    });
    loadJournal().catch((error) => showToast(error.message, "error"));
  });
});

els.settingsNotificationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const body = {
      phone: els.settingsPhone.value.trim(),
      whatsapp_enabled: els.settingsWhatsappEnabled.checked,
      telegram_enabled: els.settingsTelegramEnabled.checked,
    };
    const manualTelegramChatId = els.settingsTelegramChatId.value.trim();
    if (manualTelegramChatId) {
      body.telegram_chat_id = manualTelegramChatId;
    }
    const data = await api("/api/mobile/settings/notifications", {
      method: "POST",
      body,
    });
    applySettingsPayload(data);
    showToast(data.message || "Notification routes saved.");
    if (telegramNotificationsReady() && !automaticSignalAlreadySent()) {
      scheduleAutomaticTelegramSignal({ delayMs: 250, showToasts: true });
    }
  } catch (error) {
    showToast(error.message, "error");
  }
});

if (els.settingsTelegramOpen) {
  els.settingsTelegramOpen.addEventListener("click", (event) => {
    if (els.settingsTelegramOpen.classList.contains("is-disabled")) {
      event.preventDefault();
    }
  });
}

if (els.settingsTelegramFinish) {
  els.settingsTelegramFinish.addEventListener("click", async () => {
    try {
      const data = await api("/api/mobile/settings/telegram/connect", {
        method: "POST",
        body: {},
      });
      applySettingsPayload(data);
      showToast(data.message || "Telegram connected.");
      if (telegramNotificationsReady() && !automaticSignalAlreadySent()) {
        scheduleAutomaticTelegramSignal({ delayMs: 250, showToasts: true });
      }
    } catch (error) {
      showToast(error.message, "error");
    }
  });
}

els.settingsPreferencesForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("/api/mobile/settings/preferences", {
      method: "POST",
      body: {
        notify_buy_signals: els.prefBuySignals.checked,
        notify_sell_signals: els.prefSellSignals.checked,
        notify_signal_updates: els.prefSignalUpdates.checked,
        notify_high_confidence_only: els.prefHighConfidence.checked,
        notify_market_digest: els.prefMarketDigest.checked,
        security_authenticator_2fa: els.prefAuthenticator.checked,
        security_sms_verification: els.prefSmsVerification.checked,
        security_login_alerts: els.prefLoginAlerts.checked,
      },
    });
    applySettingsPayload(data);
    showToast(data.message || "Preferences saved.");
  } catch (error) {
    showToast(error.message, "error");
  }
});

els.settingsPasswordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const currentPassword = els.settingsCurrentPassword.value;
  const newPassword = els.settingsNewPassword.value;
  const confirmPassword = els.settingsConfirmPassword.value;
  if (!currentPassword || !newPassword || !confirmPassword) {
    showToast("Fill in all password fields.", "error");
    return;
  }
  if (newPassword !== confirmPassword) {
    showToast("New password and confirmation do not match.", "error");
    return;
  }
  try {
    const data = await api("/api/mobile/settings/password", {
      method: "POST",
      body: {
        current_password: currentPassword,
        new_password: newPassword,
      },
    });
    els.settingsCurrentPassword.value = "";
    els.settingsNewPassword.value = "";
    els.settingsConfirmPassword.value = "";
    showToast(data.message || "Password updated.");
  } catch (error) {
    showToast(error.message, "error");
  }
});

document.addEventListener("click", (event) => {
  const clickTarget = event.target instanceof Element ? event.target : null;
  if (!clickTarget || !clickTarget.closest(".custom-select-host")) {
    closeCustomSelects();
  }

  const indicatorToggle = clickTarget ? clickTarget.closest("#market-indicator-toggle") : null;
  if (!indicatorToggle && els.marketIndicatorDrawer && els.marketIndicatorToggle && !els.marketIndicatorDrawer.classList.contains("hidden")) {
    const clickedInsideDrawer = clickTarget ? clickTarget.closest("#market-indicator-drawer") : null;
    if (!clickedInsideDrawer) {
      toggleIndicatorDrawer(false);
    }
  }

  const indicatorButton = clickTarget ? clickTarget.closest("[data-market-indicator]") : null;
  if (indicatorButton) {
    setActiveIndicator(indicatorButton.dataset.marketIndicator);
    return;
  }

  const marketViewButton = clickTarget ? clickTarget.closest("[data-market-scroll]") : null;
  if (marketViewButton) {
    scrollToMarketSection(marketViewButton.dataset.marketScroll);
    return;
  }

  const timeframeButton = clickTarget ? clickTarget.closest("[data-timeframe-target]") : null;
  if (timeframeButton) {
    state.interval = timeframeButton.dataset.timeframeTarget || state.interval;
    els.marketInterval.value = state.interval;
    persistWorkspaceSelection();
    clearStoredSignal(`Ready to analyze ${state.symbol} on ${state.interval}.`);
    renderTimeframePills();
    refreshMarketSurface({ restartTimer: true }).catch((error) => showToast(error.message, "error"));
    scheduleAutomaticTelegramSignal({ delayMs: 700 });
    return;
  }

  const actionButton = clickTarget ? clickTarget.closest("[data-trade-open]") : null;
  if (!actionButton) return;
  const targetPage = actionButton.dataset.tradeOpen || "markets";
  const symbol = actionButton.dataset.symbol || state.symbol;
  const interval = actionButton.dataset.interval || state.interval;
  jumpToWorkspace(targetPage, symbol, interval);
});

els.logoutButton.addEventListener("click", async () => {
  try {
    const response = await api("/api/mobile/auth/logout", { method: "POST" });
    showToast(response.message || "Signed out.");
    applyLoggedOut(response);
  } catch (error) {
    showToast(error.message, "error");
  }
});

window.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearInterval(state.liveTimer);
    state.liveTimer = null;
    closeCustomSelects();
    return;
  }
  updateResponsiveDensity();
  if (state.session) {
    refreshCurrentPage({ silent: true }).catch((error) => console.debug(error));
  }
  startLiveRefresh();
});

window.addEventListener("online", () => {
  if (!state.session) {
    bootstrap();
    return;
  }
  showToast("Connection restored. Checking Telegram signal route.");
  refreshCurrentPage({ silent: true }).catch((error) => console.debug(error));
  scheduleAutomaticTelegramSignal({ delayMs: 900, showToasts: true });
});

window.addEventListener("offline", () => {
  if (!state.session) return;
  showToast("Connection lost. Telegram signal delivery will retry when you are online.", "error");
});

window.addEventListener("resize", () => {
  closeCustomSelects();
  updateResponsiveDensity();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeCustomSelects();
  }
});

updateResponsiveDensity();
switchAuthPanel(state.authPanel);
resetAuthStages();
setActiveIndicator(state.chartIndicator, { sync: false });
initializeCustomSelects();
bootstrap();
