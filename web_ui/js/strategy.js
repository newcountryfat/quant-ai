/**
 * Backtest Records page: shows all historical backtest runs.
 * (Previously "Effective Strategies" page, now renamed to "回测记录")
 */
let _btRecLoaded = false;
let _btRecExpandedIdx = -1;

async function loadBtRecords() {
  const list = document.getElementById('btRecList');
  const loading = document.getElementById('btRecLoading');
  const empty = document.getElementById('btRecEmpty');

  loading.style.display = 'block';
  empty.style.display = 'none';
  list.innerHTML = '';
  _btRecExpandedIdx = -1;

  try {
    const r = await api('/api/v1/backtest/history?limit=100');
    const history = r.history || [];
    App.btHistoryData = history;

    if (!history.length) {
      empty.style.display = 'block';
      loading.style.display = 'none';
      _btRecLoaded = true;
      return;
    }

    list.innerHTML = history.map((h, idx) => {
      const ret = (h.total_return * 100).toFixed(2);
      const isWin = h.total_return > 0;
      const retColor = isWin ? 'var(--r)' : (h.total_return < 0 ? 'var(--g)' : 'var(--t3)');
      const sg = h.total_return > 0 ? '+' : '';
      const sharpe = h.sharpe?.toFixed(2) ?? '--';
      const maxdd = h.max_dd ? (h.max_dd * 100).toFixed(2) + '%' : '--';
      const winR = h.win_rate ? (h.win_rate * 100).toFixed(1) + '%' : '--';
      const trades = h.trade_count ?? '--';
      const cap = h.initial_capital ? (h.initial_capital / 10000).toFixed(0) + '万' : '--';
      const period = (h.start_date || '--') + ' ~ ' + (h.end_date || '--');
      const time = (h.run_at || '').slice(5, 16);

      const recId = h.id || '';
      return `<div class="strat-card" onclick="toggleBtRecDetail(${idx})" id="btRec-${idx}">
  <div class="strat-head">
    <div style="display:flex;align-items:center;gap:8px">
      <span class="strat-name">${STRAT_NAMES[h.strategy_id] || h.strategy_id}</span>
      <span class="mono" style="font-size:.76rem;color:var(--t3)">${h.symbol}</span>
    </div>
    <div style="display:flex;align-items:center;gap:6px">
      <span class="strat-badge ${isWin ? 'win' : 'loss'}" style="color:${retColor}">${sg}${ret}%</span>
      ${recId ? `<button class="btn btn-ghost btn-sm" style="font-size:.58rem;color:var(--t3);padding:2px 6px" onclick="event.stopPropagation();deleteBtRecord(${recId})" title="删除">🗑</button>` : ''}
    </div>
  </div>
  <div class="strat-metrics">
    <div class="strat-metric"><span class="sm-label">夏普比率</span><span class="sm-val">${sharpe}</span></div>
    <div class="strat-metric"><span class="sm-label">最大回撤</span><span class="sm-val">${maxdd}</span></div>
    <div class="strat-metric"><span class="sm-label">胜率</span><span class="sm-val">${winR}</span></div>
    <div class="strat-metric"><span class="sm-label">交易次数</span><span class="sm-val">${trades}</span></div>
    <div class="strat-metric"><span class="sm-label">资金</span><span class="sm-val">${cap}</span></div>
    <div class="strat-metric"><span class="sm-label">区间</span><span class="sm-val" style="font-size:.7rem">${period}</span></div>
    <div class="strat-metric"><span class="sm-label">时间</span><span class="sm-val" style="font-size:.7rem">${time}</span></div>
  </div>
  <div class="btRec-detail" id="btRecDetail-${idx}" style="display:none;margin-top:8px;border-top:1px solid var(--bd);padding-top:8px"></div>
</div>`;
    }).join('');

    _btRecLoaded = true;
  } catch (e) {
    list.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = '加载失败，请重试';
  }
  loading.style.display = 'none';
}

async function toggleBtRecDetail(idx) {
  const detailEl = document.getElementById('btRecDetail-' + idx);
  if (!detailEl) return;

  if (_btRecExpandedIdx === idx) {
    detailEl.style.display = 'none';
    detailEl.innerHTML = '';
    document.getElementById('btRec-' + idx).classList.remove('active');
    _btRecExpandedIdx = -1;
    return;
  }

  if (_btRecExpandedIdx >= 0) {
    const prev = document.getElementById('btRecDetail-' + _btRecExpandedIdx);
    if (prev) { prev.style.display = 'none'; prev.innerHTML = ''; }
    const prevCard = document.getElementById('btRec-' + _btRecExpandedIdx);
    if (prevCard) prevCard.classList.remove('active');
  }

  _btRecExpandedIdx = idx;
  const card = document.getElementById('btRec-' + idx);
  if (card) card.classList.add('active');

  detailEl.style.display = 'block';
  detailEl.innerHTML = '<div style="text-align:center;padding:8px"><span class="spinner"></span>获取详情…</div>';

  const h = App.btHistoryData[idx];
  if (!h) return;

  try {
    let params = {};
    try { params = JSON.parse(h.params_json || '{}'); } catch (e) {}
    if (!params.initial_capital) params.initial_capital = h.initial_capital || 1000000;
    if (!params.commission) params.commission = 0.001;

    const r = await api('/api/v1/backtest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        strategy_id: h.strategy_id,
        symbol: h.symbol,
        start: h.start_date || '2025-01-01',
        end: h.end_date || today(),
        params,
      }),
    });

    renderRecDetail(detailEl, r, params, h);
  } catch (e) {
    detailEl.innerHTML = '<div style="color:var(--r);padding:8px;text-align:center">回测失败</div>';
  }
}

function renderRecDetail(container, r, params, meta) {
  const pct = v => (v * 100).toFixed(2) + '%';
  const cap = params.initial_capital || 1000000;
  const finalCap = cap * (1 + r.total_return);
  const comm = params.commission || 0.001;
  const pj = Object.entries(params)
    .filter(([k]) => !['initial_capital', 'commission'].includes(k))
    .map(([k, v]) => `${k}=${v}`).join(', ');

  let html = '<div class="bt-grid" style="margin-bottom:12px">';
  html += btRecCard('总收益', pct(r.total_return), r.total_return >= 0 ? 'positive' : 'negative');
  html += btRecCard('年化收益', pct(r.annual_return), r.annual_return >= 0 ? 'positive' : 'negative');
  html += btRecCard('夏普比率', r.sharpe_ratio.toFixed(4), r.sharpe_ratio >= 1 ? 'positive' : '');
  html += btRecCard('最大回撤', pct(r.max_drawdown), 'negative');
  html += btRecCard('胜率', pct(r.win_rate), r.win_rate >= 0.5 ? 'positive' : 'negative');
  html += btRecCard('交易次数', r.trade_count, '');
  html += '</div>';

  html += `<div style="font-size:.8rem;line-height:1.8;color:var(--t2);margin-bottom:12px">
<b>策略:</b> ${STRAT_NAMES[r.strategy_id] || r.strategy_id} | <b>股票:</b> ${r.symbol}<br>
<b>初始资金:</b> <span class="mono">${(cap / 10000).toFixed(0)}万</span> → <b>最终权益:</b> <span class="mono" style="color:${r.total_return >= 0 ? 'var(--g)' : 'var(--r)'}">${(finalCap / 10000).toFixed(2)}万</span><br>
<b>交易成本:</b> ${(comm * 1000).toFixed(1)}‰${pj ? ' | <b>参数:</b> ' + pj : ''}
</div>`;

  if (r.trades && r.trades.length) {
    html += renderTradeTable(r.trades, cap, comm);
  }

  container.innerHTML = html;
}

function btRecCard(label, value, cls) {
  return `<div class="bt-card"><div class="label">${label}</div><div class="val ${cls}">${value}</div></div>`;
}

async function deleteBtRecord(recordId) {
  if (!confirm('确认删除该回测记录？')) return;
  try {
    await api(`/api/v1/backtest/history/${recordId}`, { method: 'DELETE' });
    toast('已删除');
    loadBtRecords();
  } catch (e) { toast('删除失败: ' + e.message, 'error'); }
}

function loadEffectiveStrategies() { loadBtRecords(); }
