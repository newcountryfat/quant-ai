/**
 * Stocks page: Xueqiu-style index panel + ETF panel + stock list.
 */
async function ensureEtfUniverseLoaded() {
  if (App.etfUniverseList?.length) return App.etfUniverseList;
  const r = await api('/api/v1/market/etfs?scope=all&persist=true');
  App.etfUniverseList = r.etfs || [];
  return App.etfUniverseList;
}

async function loadIndices() {
  try {
    const r = await api('/api/v1/market/indices');
    App.indexList = r.indices || [];
    if (!App.indexList.length) {
      document.getElementById('indexGrid').innerHTML =
        '<div style="color:var(--t3);font-size:.76rem;grid-column:1/-1;text-align:center;padding:8px">指数数据加载中…</div>';
      return;
    }
    document.getElementById('indexGrid').innerHTML = App.indexList.map(i => {
      const up = i.change >= 0;
      const c = up ? '#ff4d4f' : '#00b853';
      const s = i.change > 0 ? '+' : '';
      return `<div class="idx-card" onclick="openIndexDetail('${i.code}','${i.name}')">
        <div class="idx-name">${i.name}</div>
        <div class="idx-price" style="color:${c}">${i.close}</div>
        <div class="idx-chg" style="color:${c}">${s}${i.change.toFixed(2)} ${s}${i.change_pct}%</div>
      </div>`;
    }).join('');
  } catch (e) { document.getElementById('indexGrid').innerHTML = ''; }
}

async function loadETFs() {
  const grid = document.getElementById('etfGrid');
  try {
    const r = await api('/api/v1/market/etfs');
    App.etfList = r.etfs || [];
    if (!App.etfList.length) {
      grid.innerHTML =
        '<div style="color:var(--t3);font-size:.76rem;grid-column:1/-1;text-align:center;padding:8px">ETF数据加载中…</div>';
      return;
    }
    grid.innerHTML = App.etfList.map(i => {
      const up = i.change >= 0;
      const c = up ? '#ff4d4f' : '#00b853';
      const s = i.change > 0 ? '+' : '';
      return `<div class="idx-card" onclick="openETFDetail('${i.code}','${i.name}')">
        <div class="idx-name">${i.name}</div>
        <div class="idx-price" style="color:${c}">${i.close.toFixed(3)}</div>
        <div class="idx-chg" style="color:${c}">${s}${i.change.toFixed(4)} ${s}${i.change_pct}%</div>
      </div>`;
    }).join('');
  } catch (e) { grid.innerHTML = ''; }
}

async function loadStocks() {
  document.getElementById('stockLoading').style.display = 'block';
  document.getElementById('stockEmpty').style.display = 'none';
  try {
    const [d, statuses] = await Promise.all([
      api('/api/v1/stocks?market=A'),
      api('/api/v1/data/statuses').catch(() => ({ items: [] })),
    ]);
    App.allStocks = d.stocks || [];
    App.stockDataStatus = Object.fromEntries((statuses.items || []).map(i => [i.symbol, i]));
    renderStocks(App.allStocks);
  } catch (e) { toast('加载失败', 'error'); }
  document.getElementById('stockLoading').style.display = 'none';
}

function renderStocks(list) {
  const b = document.getElementById('stockBody');
  if (!list.length) { b.innerHTML = ''; document.getElementById('stockEmpty').style.display = 'block'; return; }
  document.getElementById('stockEmpty').style.display = 'none';
  const show = list.slice(0, 200);
  b.innerHTML = show.map(s =>
    `<tr onclick="openDetail('${s.symbol}')">
      <td class="mono">${s.symbol}</td>
      <td style="font-weight:600">${s.name || '--'}</td>
      <td style="color:var(--t3);font-size:.72rem">${s.industry || '--'}</td>
      <td style="text-align:right;white-space:nowrap">
        <button class="btn btn-outline btn-xs" onclick="event.stopPropagation();quickWatch('${s.symbol}')" style="margin-right:3px">+自选</button>
        <button class="btn btn-outline btn-xs" onclick="event.stopPropagation();quickFetch('${s.symbol}')">${App.stockDataStatus[s.symbol]?.count > 0 ? '更新' : '拉取'}</button>
      </td>
    </tr>`
  ).join('');
  if (list.length > 200) {
    b.innerHTML += `<tr><td colspan="4" style="text-align:center;color:var(--t3);font-size:.72rem;padding:10px">显示前 200 / 共 ${list.length} 条</td></tr>`;
  }
}

async function filterStocks() {
  const q = document.getElementById('stockSearch').value.trim().toLowerCase();
  if (!q) {
    renderStocks(App.allStocks);
    renderETFSearchResults([]);
    return;
  }
  renderStocks(App.allStocks.filter(s =>
    s.symbol.includes(q) || (s.name || '').toLowerCase().includes(q) || (s.industry || '').toLowerCase().includes(q)
  ));

  if (!App.etfUniverseList?.length) {
    renderETFSearchLoading();
    try {
      await ensureEtfUniverseLoaded();
    } catch (e) {
      renderETFSearchResults([]);
      return;
    }
    if (document.getElementById('stockSearch').value.trim().toLowerCase() !== q) return;
  }

  const etfMatches = (App.etfUniverseList || []).filter(e =>
    e.code.includes(q) || e.name.toLowerCase().includes(q)
  );
  renderETFSearchResults(etfMatches);
}

function renderETFSearchLoading() {
  const el = document.getElementById('etfSearchResults');
  if (!el) return;
  el.style.display = 'block';
  el.innerHTML = '<div class="section-header" style="margin-top:8px"><h2 class="section-title">ETF 搜索结果</h2></div>'
    + '<div class="empty-state" style="padding:10px 0"><span class="spinner"></span>加载全量 ETF 列表中…</div>';
}

function renderETFSearchResults(list) {
  const el = document.getElementById('etfSearchResults');
  if (!el) return;
  if (!list.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
  el.style.display = 'block';
  const show = list.slice(0, 80);
  el.innerHTML = '<div class="section-header" style="margin-top:8px"><h2 class="section-title">ETF 搜索结果</h2></div>'
    + show.map(e => {
      const up = e.change >= 0;
      const c = up ? '#ff4d4f' : '#00b853';
      const s = e.change > 0 ? '+' : '';
      return `<div class="wl-item" onclick="openETFDetail('${e.code}','${e.name}')">
        <div class="wl-info">
          <div class="wl-name">${e.name}</div>
          <div class="wl-code"><span style="color:#e67e22;font-size:.6rem;font-weight:700;margin-right:2px">ETF</span>${e.code}</div>
        </div>
        <div class="wl-right">
          <span class="wl-price" style="color:${c}">${e.close.toFixed(3)}</span>
          <span class="wl-pct ${up ? 'up' : e.change < 0 ? 'dn' : 'flat'}">${s}${e.change_pct}%</span>
        </div>
      </div>`;
    }).join('')
    + (list.length > show.length
      ? `<div style="text-align:center;color:var(--t3);font-size:.72rem;padding:8px">显示前 ${show.length} / 共 ${list.length} 条 ETF 结果</div>`
      : '');
}

async function syncStockList() {
  toast('同步中…');
  try {
    await api('/api/v1/stocks/update?market=A', { method: 'POST' });
    await loadStocks();
    toast('同步完成 ' + App.allStocks.length + ' 只');
  } catch (e) { toast('同步失败', 'error'); }
}

async function quickWatch(sym) {
  try {
    await api('/api/v1/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym }),
    });
    toast(sym + ' 已加自选');
  } catch (e) { toast('失败', 'error'); }
}

async function quickFetch(sym) {
  const hasData = (App.stockDataStatus[sym]?.count || 0) > 0;
  toast((hasData ? '更新 ' : '拉取 ') + sym);
  try {
    const r = await api('/api/v1/data/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, start: '2025-01-01', end: today() }),
    });
    App.stockDataStatus[sym] = { symbol: sym, count: r.rows_in_db, max_date: today() };
    filterStocks();
    toast(sym + ' 入库 ' + r.rows_in_db + ' 条');
  } catch (e) { toast('拉取失败', 'error'); }
}
