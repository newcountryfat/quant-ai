/**
 * Core module: shared state, API, routing, utilities.
 */
const App = {
  allStocks: [],
  stockDataStatus: {},
  currentDetail: null,
  currentDetailType: null,
  indexList: [],
  etfList: [],
  etfUniverseList: [],
  btHistoryData: [],
  btFolders: [],
  effectiveStrategies: [],
  detailDailyRows: [],
  factorLibrary: [],
  trainedModels: [],
};

const API = '';

const FACTOR_CN = {
  ma_5:'5日均线', ma_10:'10日均线', ma_20:'20日均线', ma_60:'60日均线',
  macd:'MACD 差离值', macd_signal:'MACD 信号线', macd_hist:'MACD 柱状图',
  rsi_14:'RSI-14 相对强弱',
  bb_mid:'布林中轨', bb_upper:'布林上轨', bb_lower:'布林下轨', bb_width:'布林带宽',
  mom_10:'10日动量',
};

const FACTOR_DESC = {
  ma_5:'5日简单移动平均线，反映短期价格趋势。价格在均线上方为短期强势。',
  ma_10:'10日均线，短中期趋势参考。',
  ma_20:'20日均线（月线），常用的中期趋势判断指标。',
  ma_60:'60日均线（季线），反映中长期趋势方向。',
  macd:'MACD 差离值 = 12日EMA − 26日EMA。正值表示短期动能强于长期。',
  macd_signal:'MACD 信号线 = MACD的9日EMA。MACD上穿信号线为金叉（买入信号）。',
  macd_hist:'MACD 柱状图 = MACD − 信号线。柱子由负转正提示趋势反转。',
  rsi_14:'14日相对强弱指标。>70 超买区间，<30 超卖区间。用于判断价格是否偏离合理区间。',
  bb_mid:'布林中轨 = 20日均线。价格围绕中轨波动。',
  bb_upper:'布林上轨 = 中轨 + 2倍标准差。价格触及上轨可能面临压力。',
  bb_lower:'布林下轨 = 中轨 − 2倍标准差。价格触及下轨可能获得支撑。',
  bb_width:'布林带宽 = (上轨−下轨)/中轨。带宽收窄预示变盘，放大表示波动加剧。',
  mom_10:'10日动量 = 当前价/10日前价 − 1。正值表示上涨动量，负值表示下跌动量。',
};

const STRAT_NAMES = { ma_cross:'MA均线交叉', rsi_reversal:'RSI超买超卖反转', bollinger_breakout:'布林通道突破' };

/* ===== API helper ===== */
async function api(path, opts = {}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) throw new Error(`API ${r.status}`);
  return r.json();
}

/* ===== Toast ===== */
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  document.getElementById('toastContainer').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

/* ===== Tab routing ===== */
function switchTab(name, skip) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');
  const pg = document.getElementById('page-' + name);
  if (pg) pg.classList.add('active');
  if (name === 'dashboard' && !skip) loadDashboard();
  if (name === 'stocks' && !skip && App.allStocks.length === 0) loadStocks();
  if (name === 'watchlist') loadWatchlist();
  if (name === 'trading') loadPaperAccount();
  if (name === 'backtest') { /* config only, no history */ }
  if (name === 'strategy') loadBtRecords();
  if (name === 'research' && !skip) loadResearchPage();
  if (name === 'models' && !skip) { mlLoadModels(); mlLoadGpList(); }
  if (name === 'detail' && !App.currentDetail) {
    document.getElementById('dtEmpty').style.display = '';
    document.getElementById('dtContent').style.display = 'none';
  }
}

/* ===== Chart helper with scroll guard ===== */
function renderChart(ct, data, h) {
  ct.innerHTML = '';
  if (!data.length) return;
  const chart = LightweightCharts.createChart(ct, {
    width: ct.clientWidth, height: h,
    layout: { background: { color: '#16161c' }, textColor: '#5c5c72' },
    grid: { vertLines: { color: '#222230' }, horzLines: { color: '#222230' } },
    crosshair: { mode: 0 },
    timeScale: { borderColor: '#222230', timeVisible: false, rightOffset: 2 },
    rightPriceScale: { borderColor: '#222230' },
  });
  chart.addCandlestickSeries({
    upColor: '#ff4d4f', downColor: '#00b853',
    borderUpColor: '#ff4d4f', borderDownColor: '#00b853',
    wickUpColor: '#ff4d4f', wickDownColor: '#00b853',
  }).setData(data.map(d => ({ time: d.trade_date, open: d.open, high: d.high, low: d.low, close: d.close })));
  const vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
  vol.setData(data.map(d => ({ time: d.trade_date, value: d.volume, color: d.close >= d.open ? 'rgba(255,77,79,.2)' : 'rgba(0,184,83,.2)' })));
  chart.timeScale().fitContent();

  const maxRight = 2;
  let _guard = false;
  chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (!range || _guard) return;
    const maxTo = data.length - 1 + maxRight;
    if (range.to > maxTo) {
      _guard = true;
      const span = range.to - range.from;
      chart.timeScale().setVisibleLogicalRange({
        from: maxTo - span,
        to: maxTo,
      });
      setTimeout(() => { _guard = false; }, 60);
    }
  });

  new ResizeObserver(() => chart.applyOptions({ width: ct.clientWidth })).observe(ct);
  return chart;
}

/* ===== K-line period aggregation (daily -> week/month/quarter/year) ===== */
function aggregateKline(dailyAsc, period) {
  if (!dailyAsc.length) return [];
  if (period === '5d') return dailyAsc.slice(-5);
  if (period === 'day') return dailyAsc;

  const groups = {};
  const order = [];
  dailyAsc.forEach(d => {
    const [y, m] = d.trade_date.split('-');
    let key;
    if (period === 'week') {
      const dt = new Date(d.trade_date + 'T00:00:00');
      const day = dt.getDay() || 7;
      const mon = new Date(dt);
      mon.setDate(dt.getDate() - day + 1);
      key = mon.toISOString().slice(0, 10);
    } else if (period === 'month') {
      key = `${y}-${m}-01`;
    } else if (period === 'quarter') {
      const q = Math.ceil(parseInt(m) / 3);
      key = `${y}-${String(q * 3 - 2).padStart(2, '0')}-01`;
    } else if (period === 'year') {
      key = `${y}-01-01`;
    }
    if (!groups[key]) { groups[key] = []; order.push(key); }
    groups[key].push(d);
  });

  return order.map(key => {
    const bars = groups[key];
    return {
      trade_date: bars[bars.length - 1].trade_date,
      open: bars[0].open,
      high: Math.max(...bars.map(b => b.high)),
      low: Math.min(...bars.map(b => b.low)),
      close: bars[bars.length - 1].close,
      volume: bars.reduce((s, b) => s + (b.volume || 0), 0),
    };
  });
}

/* ===== Utility helpers ===== */
function xqMetaCell(l, v) {
  return `<div class="xq-cell"><span class="xq-l">${l}</span><span class="xq-v">${v ?? '--'}</span></div>`;
}

function fV(v) {
  if (!v) return '--';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万';
  return v.toFixed(0);
}

function today() { return new Date().toISOString().slice(0, 10); }

async function fetchSilent(sym, start, end) {
  try { await api('/api/v1/data/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: sym, start, end }) }); } catch (e) { }
}

async function loadHealth() {
  try {
    const h = await api('/health');
    document.getElementById('statusDot').style.background = h.status === 'ok' ? 'var(--g)' : 'var(--r)';
    document.getElementById('statusText').textContent = h.status === 'ok' ? '运行中' : '异常';
  } catch (e) {
    document.getElementById('statusDot').style.background = 'var(--r)';
    document.getElementById('statusText').textContent = '离线';
  }
}

function setDates() {
  const t = today();
  document.getElementById('btEnd').value = t;
}

function pct(v) { return (v * 100).toFixed(2) + '%'; }
function clr(v) { return v >= 0 ? 'var(--r)' : 'var(--g)'; }
function sgn(v) { return v > 0 ? '+' : ''; }
