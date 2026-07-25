const state = {
  symbol: "BTCUSDT",
  interval: "1m",
  balance: 1000,
  chart: null,
  candleSeries: null,
  volumeSeries: null,
  marketTimer: null,
  signalBusy: false,
  autoTradeBusy: false,
  chartKey: null,
  candleCache: [],
  volumeCache: [],
  marketRequestInFlight: false,
  brokerStatus: null,
  activeBrokerTab: "profile",
  orderbookDomRows: [],
};

const els = {
  symbolSelect: document.getElementById("symbol-select"),
  timeframeStrip: document.getElementById("timeframe-strip"),
  balanceInput: document.getElementById("balance-input"),
  brokerButton: document.getElementById("broker-button"),
  signalButton: document.getElementById("signal-button"),
  autoTradeButton: document.getElementById("autotrade-button"),
  brokerChip: document.getElementById("broker-chip"),
  serverMessage: document.getElementById("server-message"),
  chartRoot: document.getElementById("chart-root"),
  chartSymbolTitle: document.getElementById("chart-symbol-title"),
  chartStatus: document.getElementById("chart-status"),
  headlinePrice: document.getElementById("headline-price"),
  headlineChange: document.getElementById("headline-change"),
  headlineFunding: document.getElementById("headline-funding"),
  orderbookRows: document.getElementById("orderbook-rows"),
  spreadLabel: document.getElementById("spread-label"),
  midLabel: document.getElementById("mid-label"),
  statMark: document.getElementById("stat-mark"),
  statIndex: document.getElementById("stat-index"),
  statHigh: document.getElementById("stat-high"),
  statLow: document.getElementById("stat-low"),
  statOi: document.getElementById("stat-oi"),
  statVolume: document.getElementById("stat-volume"),
  signalEmpty: document.getElementById("signal-empty"),
  signalCard: document.getElementById("signal-card"),
  signalSide: document.getElementById("signal-side"),
  signalReason: document.getElementById("signal-reason"),
  signalConfidence: document.getElementById("signal-confidence"),
  signalEntry: document.getElementById("signal-entry"),
  signalTarget: document.getElementById("signal-target"),
  signalStop: document.getElementById("signal-stop"),
  signalRr: document.getElementById("signal-rr"),
  signalTags: document.getElementById("signal-tags"),
  brokerName: document.getElementById("broker-name"),
  brokerMode: document.getElementById("broker-mode"),
  brokerBalance: document.getElementById("broker-balance"),
  tradeResult: document.getElementById("trade-result"),
  brokerModal: document.getElementById("broker-modal"),
  modalClose: document.getElementById("modal-close"),
  modalTabs: [...document.querySelectorAll(".modal-tab")],
  modalPanes: {
    profile: document.getElementById("modal-tab-profile"),
    live: document.getElementById("modal-tab-live"),
  },
  brokerModalMessage: document.getElementById("broker-modal-message"),
  profileBrokerName: document.getElementById("profile-broker-name"),
  profileAccountAlias: document.getElementById("profile-account-alias"),
  profileBalance: document.getElementById("profile-balance"),
  profileSave: document.getElementById("profile-save"),
  profileDisconnect: document.getElementById("profile-disconnect"),
  liveBrokerName: document.getElementById("live-broker-name"),
  liveApiKey: document.getElementById("live-api-key"),
  liveApiSecret: document.getElementById("live-api-secret"),
  liveConnect: document.getElementById("live-connect"),
  liveDisconnect: document.getElementById("live-disconnect"),
};

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatCompact(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const num = Number(value) * 100;
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
}

function formatSignalPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(0)}%`;
}

function setElementText(element, value) {
  const next = String(value);
  if (element.textContent !== next) {
    element.textContent = next;
  }
}

function setActiveTimeframe(interval) {
  state.interval = interval;
  state.chartKey = null;
  state.candleCache = [];
  state.volumeCache = [];
  document.querySelectorAll(".tf-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.interval === interval);
  });
}

function setMessage(message, tone = "info") {
  if (!message) {
    els.serverMessage.className = "server-message hidden";
    els.serverMessage.textContent = "";
    return;
  }
  els.serverMessage.className = `server-message ${tone}`;
  els.serverMessage.textContent = message;
}

function setModalMessage(message, tone = "info") {
  if (!message) {
    els.brokerModalMessage.className = "inline-message hidden";
    els.brokerModalMessage.textContent = "";
    return;
  }
  els.brokerModalMessage.className = `inline-message ${tone}`;
  els.brokerModalMessage.textContent = message;
}

function showTradeResult(title, message, tone = "success") {
  els.tradeResult.className = `trade-result ${tone}`;
  els.tradeResult.innerHTML = `
    <div class="trade-result-title">${title}</div>
    <div class="trade-result-text">${message}</div>
  `;
}

function setActiveBrokerTab(tabName) {
  state.activeBrokerTab = tabName;
  els.modalTabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  });
  Object.entries(els.modalPanes).forEach(([name, pane]) => {
    pane.classList.toggle("active", name === tabName);
  });
}

function openBrokerModal(tabName = "profile") {
  setActiveBrokerTab(tabName);
  setModalMessage("");
  els.brokerModal.classList.remove("hidden");
}

function closeBrokerModal() {
  els.brokerModal.classList.add("hidden");
  setModalMessage("");
}

function buildChart() {
  if (!window.LightweightCharts) {
    els.chartStatus.textContent = "Lightweight Charts failed to load.";
    return;
  }

  const chart = window.LightweightCharts.createChart(els.chartRoot, {
    layout: {
      background: { color: "#0b1320" },
      textColor: "#8fa6bc",
    },
    width: els.chartRoot.clientWidth,
    height: els.chartRoot.clientHeight,
    grid: {
      vertLines: { color: "rgba(255,255,255,0.04)" },
      horzLines: { color: "rgba(255,255,255,0.05)" },
    },
    crosshair: { mode: 1 },
    rightPriceScale: {
      borderColor: "rgba(255,255,255,0.08)",
      scaleMargins: { top: 0.08, bottom: 0.28 },
    },
    timeScale: {
      borderColor: "rgba(255,255,255,0.08)",
      timeVisible: true,
      secondsVisible: false,
    },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#00c087",
    downColor: "#ff5c79",
    borderVisible: false,
    wickUpColor: "#00c087",
    wickDownColor: "#ff5c79",
    priceLineVisible: true,
  });

  const volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "",
    color: "rgba(0, 234, 255, 0.45)",
  });

  volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.78, bottom: 0 },
  });

  state.chart = chart;
  state.candleSeries = candleSeries;
  state.volumeSeries = volumeSeries;

  window.addEventListener("resize", () => {
    if (!state.chart) return;
    state.chart.applyOptions({
      width: els.chartRoot.clientWidth,
      height: els.chartRoot.clientHeight,
    });
  });

  setElementText(els.chartStatus, "Waiting for market data");
}

function ensureOrderBookRows(count) {
  if (state.orderbookDomRows.length >= count) return;

  const fragment = document.createDocumentFragment();
  for (let index = state.orderbookDomRows.length; index < count; index += 1) {
    const row = document.createElement("div");
    row.className = "orderbook-row";

    const bidPrice = document.createElement("span");
    bidPrice.className = "bid-price";
    const bidSize = document.createElement("span");
    bidSize.className = "bid-size";
    const askPrice = document.createElement("span");
    askPrice.className = "ask-price";
    const askSize = document.createElement("span");
    askSize.className = "ask-size";

    row.append(bidPrice, bidSize, askPrice, askSize);
    fragment.appendChild(row);
    state.orderbookDomRows.push({ row, bidPrice, bidSize, askPrice, askSize });
  }

  els.orderbookRows.appendChild(fragment);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = {};
  }

  if (!response.ok) {
    const error = new Error(payload.error || `Request failed: ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

function updateChart(candles) {
  if (!state.candleSeries || !state.volumeSeries) return;

  const candleData = candles.map((candle) => ({
    time: candle.time,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  }));

  const volumeData = candles.map((candle) => ({
    time: candle.time,
    value: candle.volume,
    color: candle.close >= candle.open ? "rgba(0, 192, 135, 0.38)" : "rgba(255, 92, 121, 0.38)",
  }));

  const nextKey = `${state.symbol}:${state.interval}`;
  if (state.chartKey !== nextKey || state.candleCache.length === 0 || candleData.length < state.candleCache.length) {
    state.candleSeries.setData(candleData);
    state.volumeSeries.setData(volumeData);
    state.chart.timeScale().fitContent();
    state.chartKey = nextKey;
    state.candleCache = candleData;
    state.volumeCache = volumeData;
    return;
  }

  if (candleData.length > state.candleCache.length + 1) {
    state.candleSeries.setData(candleData);
    state.volumeSeries.setData(volumeData);
    state.candleCache = candleData;
    state.volumeCache = volumeData;
    return;
  }

  const lastCandle = candleData[candleData.length - 1];
  const lastVolume = volumeData[volumeData.length - 1];
  const prevLast = state.candleCache[state.candleCache.length - 1];

  if (!prevLast || prevLast.time !== lastCandle.time) {
    state.candleSeries.update(lastCandle);
    state.volumeSeries.update(lastVolume);
    state.candleCache = candleData;
    state.volumeCache = volumeData;
    return;
  }

  const changed =
    prevLast.open !== lastCandle.open ||
    prevLast.high !== lastCandle.high ||
    prevLast.low !== lastCandle.low ||
    prevLast.close !== lastCandle.close;

  if (changed) {
    state.candleSeries.update(lastCandle);
    state.volumeSeries.update(lastVolume);
    state.candleCache[state.candleCache.length - 1] = lastCandle;
    state.volumeCache[state.volumeCache.length - 1] = lastVolume;
  }
}

function updateMarket(payload) {
  const market = payload.market || {};
  const orderbook = payload.orderbook || { bids: [], asks: [] };

  setElementText(els.chartSymbolTitle, `${payload.symbol} - ${payload.interval}`);
  setElementText(els.chartStatus, "Live market stream");
  setElementText(els.headlinePrice, formatNumber(market.last_price, 2));
  setElementText(els.headlineChange, formatPercent(market.price_24h_pcnt));
  setElementText(els.headlineFunding, formatPercent(market.funding_rate));

  setElementText(els.statMark, formatNumber(market.mark_price, 2));
  setElementText(els.statIndex, formatNumber(market.index_price, 2));
  setElementText(els.statHigh, formatNumber(market.high_24h, 2));
  setElementText(els.statLow, formatNumber(market.low_24h, 2));
  setElementText(els.statOi, formatCompact(market.open_interest));
  setElementText(els.statVolume, formatCompact(market.volume_24h));

  updateOrderBook(orderbook);
}

function updateOrderBook(orderbook) {
  const bids = orderbook.bids || [];
  const asks = orderbook.asks || [];
  const depth = Math.max(bids.length, asks.length, 12);
  ensureOrderBookRows(depth);
  const maxSize = Math.max(
    ...bids.map((level) => Number(level.size || 0)),
    ...asks.map((level) => Number(level.size || 0)),
    1
  );

  for (let index = 0; index < state.orderbookDomRows.length; index += 1) {
    const bid = bids[index];
    const ask = asks[index];
    const dom = state.orderbookDomRows[index];
    dom.row.style.setProperty("--bid-fill", `${((bid?.size || 0) / maxSize) * 100}%`);
    dom.row.style.setProperty("--ask-fill", `${((ask?.size || 0) / maxSize) * 100}%`);
    setElementText(dom.bidPrice, bid ? formatNumber(bid.price, 2) : "");
    setElementText(dom.bidSize, bid ? formatNumber(bid.size, 4) : "");
    setElementText(dom.askPrice, ask ? formatNumber(ask.price, 2) : "");
    setElementText(dom.askSize, ask ? formatNumber(ask.size, 4) : "");
  }

  const bestBid = bids[0]?.price;
  const bestAsk = asks[0]?.price;
  if (bestBid && bestAsk) {
    const spread = Number(bestAsk) - Number(bestBid);
    const mid = (Number(bestAsk) + Number(bestBid)) / 2;
    setElementText(els.spreadLabel, `Spread ${formatNumber(spread, 2)}`);
    setElementText(els.midLabel, `Mid ${formatNumber(mid, 2)}`);
  } else {
    setElementText(els.spreadLabel, "Spread --");
    setElementText(els.midLabel, "Mid --");
  }
}

function renderSignal(signal) {
  els.signalEmpty.classList.add("hidden");
  els.signalCard.classList.remove("hidden");

  const side = String(signal.signal || "HOLD").toUpperCase();
  els.signalSide.textContent = side;
  els.signalSide.className = `signal-side ${side.toLowerCase()}`;
  els.signalReason.textContent = signal.reason || "No reason provided.";
  els.signalConfidence.textContent = formatSignalPercent(signal.confidence);

  const entryExit = signal.entry_exit || {};
  els.signalEntry.textContent = formatNumber(entryExit.actual_entry || entryExit.entry_price, 4);
  els.signalTarget.textContent = formatNumber(entryExit.take_profit, 4);
  els.signalStop.textContent = formatNumber(entryExit.stop_loss, 4);
  els.signalRr.textContent = formatNumber(entryExit.risk_reward_ratio, 2);

  const summary = signal.summary || {};
  const positionSize = signal.position_size || {};
  const regime = signal.regime || {};
  const tags = [
    `Regime: ${regime.regime || "unknown"}`,
    `Setup: ${summary.setup_quality || "n/a"}`,
    `Size: ${formatNumber(positionSize.size_percent, 2)}%`,
    `Risk: ${formatNumber(entryExit.risk_amount, 2)}`,
  ];

  els.signalTags.replaceChildren(
    ...tags.map((tag) => {
      const pill = document.createElement("div");
      pill.className = "signal-tag";
      pill.textContent = tag;
      return pill;
    })
  );
}

function updateBrokerStatus(status) {
  state.brokerStatus = status;
  const live = status?.live_api || {};
  const manual = status?.manual_profile || {};
  const profile = manual.profile || {};

  els.liveBrokerName?.replaceChildren?.();
  const availableBrokers = status?.available_brokers || [];
  els.liveBrokerName.replaceChildren(
    ...availableBrokers.map((brokerName) => {
      const option = document.createElement("option");
      option.value = brokerName;
      option.textContent = brokerName;
      return option;
    })
  );

  if (manual.connected && profile.broker_name) {
    els.profileBrokerName.value = profile.broker_name;
    els.profileAccountAlias.value = profile.account_alias || "";
    els.profileBalance.value = profile.balance || state.balance;
  }

  const liveConnected = Boolean(live.connected);
  const profileConnected = Boolean(manual.connected);

  if (liveConnected) {
    els.brokerChip.className = "status-chip live";
    els.brokerChip.textContent = `${live.broker_name} API connected`;
    els.brokerName.textContent = live.broker_name || "Live broker";
    els.brokerMode.textContent = "Live API";
    els.brokerBalance.textContent = formatNumber(live.balance, 2);
    if (live.balance) {
      state.balance = Number(live.balance);
      els.balanceInput.value = state.balance;
    }
  } else if (profileConnected) {
    els.brokerChip.className = "status-chip profile";
    els.brokerChip.textContent = `${profile.broker_name} profile saved`;
    els.brokerName.textContent = profile.broker_name || "Broker profile";
    els.brokerMode.textContent = "Manual profile";
    els.brokerBalance.textContent = formatNumber(profile.balance, 2);
    if (profile.balance) {
      state.balance = Number(profile.balance);
      els.balanceInput.value = state.balance;
    }
  } else {
    els.brokerChip.className = "status-chip";
    els.brokerChip.textContent = "No broker connected";
    els.brokerName.textContent = "Not connected";
    els.brokerMode.textContent = "Offline";
    els.brokerBalance.textContent = "--";
  }
}

async function refreshBrokerStatus() {
  const payload = await fetchJson("/api/broker/status");
  updateBrokerStatus(payload);
}

async function refreshTerminal() {
  if (state.marketRequestInFlight) return;
  state.marketRequestInFlight = true;

  try {
    const payload = await fetchJson(`/api/market/terminal?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}`);
    updateChart(payload.candles || []);
    updateMarket(payload);
  } finally {
    state.marketRequestInFlight = false;
  }
}

async function fetchSignal() {
  if (state.signalBusy) return;
  state.signalBusy = true;
  els.signalButton.disabled = true;
  els.signalButton.textContent = "Loading...";

  try {
    const payload = await fetchJson(`/api/signal?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}&balance=${encodeURIComponent(state.balance)}`);
    renderSignal(payload);
    setMessage("Signal refreshed from the live market state.", "success");
  } catch (error) {
    els.signalEmpty.classList.remove("hidden");
    els.signalCard.classList.add("hidden");
    els.signalEmpty.textContent = `Signal request failed: ${error.message}`;
    setMessage(error.message, "error");
  } finally {
    state.signalBusy = false;
    els.signalButton.disabled = false;
    els.signalButton.textContent = "Get Signal";
  }
}

async function autoTrade() {
  if (state.autoTradeBusy) return;
  state.autoTradeBusy = true;
  els.autoTradeButton.disabled = true;
  els.autoTradeButton.textContent = "Routing...";

  try {
    const payload = await fetchJson("/api/trade/auto", {
      method: "POST",
      body: JSON.stringify({
        symbol: state.symbol,
        interval: state.interval,
        balance: state.balance,
      }),
    });

    renderSignal(payload.signal);
    await refreshBrokerStatus();

    const execution = payload.execution || {};
    if (execution.status === "success") {
      showTradeResult("Trade Executed", execution.message || "Signal routed to your connected broker.", "success");
      setMessage("Auto trade executed successfully.", "success");
    } else {
      showTradeResult("Trade Not Executed", execution.reason || "The broker did not execute this signal.", "error");
      setMessage(execution.reason || "Auto trade could not complete.", "error");
    }
  } catch (error) {
    if (error.status === 409) {
      openBrokerModal("live");
      setModalMessage(error.payload?.message || "Connect a live API broker before using auto trade.", "error");
      setMessage(error.payload?.message || error.message, "error");
    } else {
      showTradeResult("Trade Error", error.message, "error");
      setMessage(error.message, "error");
    }
  } finally {
    state.autoTradeBusy = false;
    els.autoTradeButton.disabled = false;
    els.autoTradeButton.textContent = "Auto Trade";
  }
}

async function saveProfile() {
  try {
    const payload = await fetchJson("/api/broker/profile", {
      method: "POST",
      body: JSON.stringify({
        broker_name: els.profileBrokerName.value.trim(),
        account_alias: els.profileAccountAlias.value.trim(),
        balance: Number(els.profileBalance.value || state.balance),
      }),
    });
    updateBrokerStatus(payload);
    setModalMessage("Broker profile saved.", "success");
    setMessage("Broker profile saved for the terminal.", "success");
    window.setTimeout(closeBrokerModal, 500);
  } catch (error) {
    setModalMessage(error.message, "error");
  }
}

async function disconnectProfile() {
  try {
    const payload = await fetchJson("/api/broker/profile", { method: "DELETE" });
    updateBrokerStatus(payload);
    setModalMessage("Broker profile disconnected.", "success");
    setMessage("Broker profile disconnected.", "success");
  } catch (error) {
    setModalMessage(error.message, "error");
  }
}

async function connectLive() {
  try {
    const payload = await fetchJson("/api/broker/live", {
      method: "POST",
      body: JSON.stringify({
        broker_name: els.liveBrokerName.value,
        api_key: els.liveApiKey.value.trim(),
        api_secret: els.liveApiSecret.value.trim(),
      }),
    });
    updateBrokerStatus(payload);
    els.liveApiKey.value = "";
    els.liveApiSecret.value = "";
    setModalMessage("Live API broker connected.", "success");
    setMessage("Live API broker connected.", "success");
    window.setTimeout(closeBrokerModal, 500);
  } catch (error) {
    setModalMessage(error.message, "error");
  }
}

async function disconnectLive() {
  try {
    const payload = await fetchJson("/api/broker/live", { method: "DELETE" });
    updateBrokerStatus(payload);
    setModalMessage("Live API broker disconnected.", "success");
    setMessage("Live API broker disconnected.", "success");
  } catch (error) {
    setModalMessage(error.message, "error");
  }
}

async function loadSymbols() {
  const payload = await fetchJson("/api/market/symbols");
  const symbols = payload.symbols || [];
  els.symbolSelect.replaceChildren(
    ...symbols.map((symbol) => {
      const option = document.createElement("option");
      option.value = symbol;
      option.textContent = symbol;
      if (symbol === state.symbol) option.selected = true;
      return option;
    })
  );
}

function bindEvents() {
  els.symbolSelect.addEventListener("change", async (event) => {
    state.symbol = event.target.value;
    setMessage("");
    await refreshTerminal();
  });

  els.balanceInput.addEventListener("change", (event) => {
    state.balance = Number(event.target.value || 1000);
  });

  els.timeframeStrip.addEventListener("click", async (event) => {
    const button = event.target.closest(".tf-button");
    if (!button) return;
    setActiveTimeframe(button.dataset.interval);
    setMessage("");
    await refreshTerminal();
  });

  els.brokerButton.addEventListener("click", () => openBrokerModal("profile"));
  els.signalButton.addEventListener("click", fetchSignal);
  els.autoTradeButton.addEventListener("click", autoTrade);
  els.modalClose.addEventListener("click", closeBrokerModal);
  els.brokerModal.addEventListener("click", (event) => {
    if (event.target.dataset.closeModal === "true") {
      closeBrokerModal();
    }
  });
  els.modalTabs.forEach((tab) => {
    tab.addEventListener("click", () => setActiveBrokerTab(tab.dataset.tab));
  });
  els.profileSave.addEventListener("click", saveProfile);
  els.profileDisconnect.addEventListener("click", disconnectProfile);
  els.liveConnect.addEventListener("click", connectLive);
  els.liveDisconnect.addEventListener("click", disconnectLive);
}

async function init() {
  buildChart();
  bindEvents();
  await Promise.all([loadSymbols(), refreshBrokerStatus()]);
  await refreshTerminal();

  // Split update speeds: chart every 3s, order book/market every 1s
  let lastChartUpdate = Date.now();
  async function splitUpdateLoop() {
    if (state.marketRequestInFlight) return;
    try {
      const payload = await fetchJson(`/api/market/terminal?symbol=${encodeURIComponent(state.symbol)}&interval=${encodeURIComponent(state.interval)}`);
      // Always update order book and market stats
      updateMarket(payload);
      // Update chart less frequently (every 3s)
      if (Date.now() - lastChartUpdate > 2900) {
        updateChart(payload.candles || []);
        lastChartUpdate = Date.now();
      }
    } catch (e) {
      // Optionally handle error
    }
  }
  state.marketTimer = window.setInterval(splitUpdateLoop, 1000);
}

init().catch((error) => {
  els.chartStatus.textContent = `Terminal failed to initialize: ${error.message}`;
  setMessage(error.message, "error");
});
