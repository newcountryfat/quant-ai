/**
 * 自选 page (Xueqiu-style watchlist with price + change pill).
 * Supports stocks, indices, and ETFs.
 */
const WL_ETF_FULL_HISTORY_START = '1990-01-01';

async function ensureWatchlistEtfsLoaded() {
  if (App.etfUniverseList?.length) {
    renderWatchlistEtfCandidates(App.etfUniverseList);
    return App.etfUniverseList;
  }
  const r = await api('/api/v1/market/etfs?scope=all&persist=true');
  App.etfUniverseList = r.etfs || [];
  renderWatchlistEtfCandidates(App.etfUniverseList);
  return App.etfUniverseList;
}

function renderWatchlistEtfCandidates(list) {
  const el = document.getElementById('wlEtfCandidates');
  if (!el) return;
  el.innerHTML = (list || []).map(i =>
    `<option value="${i.code}">${i.name}</option><option value="${i.name}">${i.code}</option>`
  ).join('');
}

function resolveEtfKeyword(keyword) {
  const q = (keyword || '').trim().toLowerCase();
  if (!q) return null;
  return (App.etfUniverseList || []).find(i =>
    i.code.toLowerCase() === q || i.name.toLowerCase() === q
  ) || (App.etfUniverseList || []).find(i =>
    i.code.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)
  ) || null;
}

function toggleWlEtfFullHistory() {
  const checked = !!document.getElementById('wlEtfFullHistory')?.checked;
  const startInput = document.getElementById('wlEtfStart');
  if (!startInput) return;
  startInput.disabled = checked;
  startInput.style.opacity = checked ? '.6' : '1';
}

function isMarketCode(sym) {
  return sym.length > 6 && (sym.startsWith('sh') || sym.startsWith('sz'));
}

function wlClickHandler(sym, name) {
  if (!isMarketCode(sym)) {
    openDetail(sym);
    return;
  }
  const idx = App.indexList.find(i => i.code === sym);
  if (idx) { openIndexDetail(sym, name); return; }
  const etf = App.etfList.find(i => i.code === sym);
  if (etf) { openETFDetail(sym, name); return; }
  openETFDetail(sym, name);
}

async function loadWatchlist() {
  try {
    await ensureWatchlistEtfsLoaded();
    const r = await api('/api/v1/watchlist');
    const list = r.items || [];
    if (!list.length) {
      document.getElementById('wlList').innerHTML = '';
      document.getElementById('wlEmpty').style.display = 'block';
      return;
    }
    document.getElementById('wlEmpty').style.display = 'none';
    document.getElementById('wlList').innerHTML = list.map(s => {
      const isMkt = isMarketCode(s.symbol);
      const p = s.close != null ? Number(s.close).toFixed(isMkt ? 4 : 2) : '--';
      const c = s.change || 0, cp = s.change_pct || 0;
      const up = c > 0, dn = c < 0;
      const priceColor = up ? 'var(--r)' : dn ? 'var(--g)' : 'var(--t1)';
      const sg = up ? '+' : '';
      const pctCls = up ? 'up' : dn ? 'dn' : 'flat';
      const pctText = cp !== 0 ? sg + cp.toFixed(2) + '%' : '0.00%';

      let marketBadge, badgeColor;
      if (isMkt) {
        const isIndex = s.industry === '指数';
        marketBadge = isIndex ? '指' : 'ETF';
        badgeColor = isIndex ? '#9b59b6' : '#e67e22';
      } else {
        marketBadge = s.symbol.startsWith('6') ? '沪' : '深';
        badgeColor = s.symbol.startsWith('6') ? '#4e8eff' : '#ff9500';
      }

      const displayName = s.name || s.symbol;
      const escapedName = displayName.replace(/'/g, "\\'");

      return `<div class="wl-item" onclick="wlClickHandler('${s.symbol}','${escapedName}')">
        <div class="wl-info">
          <div class="wl-name">${displayName}</div>
          <div class="wl-code"><span style="color:${badgeColor};font-size:.6rem;font-weight:700;margin-right:2px">${marketBadge}</span>${s.symbol}</div>
        </div>
        <div class="wl-right">
          <span class="wl-price" style="color:${priceColor}">${p}</span>
          <span class="wl-pct ${pctCls}">${pctText}</span>
          <button class="wl-remove" onclick="event.stopPropagation();removeWatch('${s.symbol}')">移除</button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { toast('加载失败', 'error'); }
}

async function pullEtfAndAddWatchlist() {
  const btn = document.getElementById('wlEtfAddBtn');
  const input = document.getElementById('wlEtfKeyword');
  const startInput = document.getElementById('wlEtfStart');
  const fullHistory = !!document.getElementById('wlEtfFullHistory')?.checked;
  const keyword = input?.value?.trim() || '';
  const start = fullHistory ? WL_ETF_FULL_HISTORY_START : (startInput?.value || '2024-01-01');
  if (!keyword) { toast('请输入 ETF 代码或名称', 'error'); return; }

  try {
    await ensureWatchlistEtfsLoaded();
  } catch (e) {
    toast('ETF 列表加载失败', 'error');
    return;
  }

  const matched = resolveEtfKeyword(keyword);
  if (!matched) {
    toast('未找到匹配 ETF，请输入正确代码或名称', 'error');
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.textContent = '拉取中…';
  }
  try {
    const updateRes = await api('/api/v1/data/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: matched.code, start }),
    });
    await api('/api/v1/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: matched.code, note: 'ETF手动添加' }),
    });
    await loadWatchlist();
    if (input) input.value = matched.code;
    toast(`${matched.name} 已拉取并加入自选，累计 ${updateRes.rows_in_db || 0} 条${fullHistory ? '（全部历史）' : ''}`);
  } catch (e) {
    toast('ETF 拉取或加自选失败', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '拉取并加自选';
    }
  }
}

async function syncA500Data() {
  const btn = document.getElementById('a500SyncBtn');
  if (btn?.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '同步中…';
  }
  try {
    const r = await api('/api/v1/data/a500/sync?add_watchlist=false&refresh_stock_list=true', {
      method: 'POST',
    });
    if (r.ok === false) {
      toast(r.hint || 'A500同步失败', 'error');
      return;
    }
    await Promise.all([
      loadWatchlist(),
      loadStocks(),
    ]);
    toast(`A500同步完成，更新 ${r.daily_updated ?? 0} 只股票数据`);
  } catch (e) {
    toast('A500同步失败', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '同步A500数据';
    }
  }
}

async function removeWatch(sym) {
  try {
    await api(`/api/v1/watchlist/${sym}`, { method: 'DELETE' });
    toast(sym + ' 已移除');
    loadWatchlist();
  } catch (e) { toast('失败', 'error'); }
}
