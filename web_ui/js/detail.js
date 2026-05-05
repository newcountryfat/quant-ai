/**
 * Stock / Index detail page (Xueqiu-style layout) with multi-period K-line.
 */

const DETAIL_FULL_HISTORY_START = '1990-01-01';

function detailSyncBtn(show) {
  const btn = document.getElementById('dtFullSyncBtn');
  if (!btn) return;
  btn.style.display = show ? '' : 'none';
  if (show) {
    btn.disabled = false;
    btn.textContent = '更新补齐';
  }
}

function detailResearchBtn(show) {
  const btn = document.getElementById('dtResearchBtn');
  if (!btn) return;
  btn.style.display = show ? '' : 'none';
  if (show) {
    btn.disabled = false;
    btn.textContent = '研究';
  }
}

/* ===== Chart period tab click handler ===== */
function initChartTabs() {
  document.querySelectorAll('#dtChartTabs .chart-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#dtChartTabs .chart-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderChartForPeriod(btn.dataset.period);
    });
  });
}

function renderChartForPeriod(period) {
  if (!App.detailDailyRows.length) return;
  const agg = aggregateKline(App.detailDailyRows, period);
  renderChart(document.getElementById('dtChart'), agg, 260);
}

function resetChartTabToDay() {
  document.querySelectorAll('#dtChartTabs .chart-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.period === 'day');
  });
}

/* ===== Open stock detail ===== */
async function openDetail(sym) {
  App.currentDetail = sym;
  App.currentDetailType = 'stock';
  document.getElementById('dtEmpty').style.display = 'none';
  document.getElementById('dtContent').style.display = 'block';
  switchTab('detail', true);

  const info = App.allStocks.find(s => s.symbol === sym) || {};
  document.getElementById('dtName').textContent = info.name || sym;
  document.getElementById('dtCode').textContent = sym;
  document.getElementById('dtIndustry').textContent = info.industry || '';
  document.getElementById('dtIndustry').style.display = info.industry ? '' : 'none';
  detailResearchBtn(true);
  detailSyncBtn(true);
  resetDetailDisplay();

  const t = today();
  try {
    const infoR = await api(`/api/v1/data/${sym}/info`);
    const hasData = infoR.count > 0;
    const isRecent = hasData && infoR.max_date >= t;
    if (!hasData) {
      toast('首次加载 ' + sym + ' 数据…');
      await fetchSilent(sym, '2025-01-01', t);
    } else if (!isRecent) {
      await fetchSilent(sym, infoR.max_date, t);
    }
    const [daily, factors] = await Promise.all([
      api(`/api/v1/data/${sym}/daily?start=${DETAIL_FULL_HISTORY_START}&end=${t}&limit=10000`),
      api(`/api/v1/factors/${sym}`),
    ]);
    renderDetailData(daily.data || [], factors);
  } catch (e) { toast('加载失败', 'error'); }
}

/* ===== Open index detail ===== */
async function openIndexDetail(code, name) {
  App.currentDetail = code;
  App.currentDetailType = 'index';
  document.getElementById('dtEmpty').style.display = 'none';
  document.getElementById('dtContent').style.display = 'block';
  switchTab('detail', true);

  document.getElementById('dtName').textContent = name;
  document.getElementById('dtCode').textContent = code;
  document.getElementById('dtIndustry').textContent = '指数';
  document.getElementById('dtIndustry').style.display = '';
  detailResearchBtn(false);
  detailSyncBtn(false);
  resetDetailDisplay();

  try {
    const r = await api(`/api/v1/index/${code}/daily?days=250`);
    const rows = (r.data || []).map(d => ({
      trade_date: d.trade_date, open: d.open, high: d.high, low: d.low,
      close: d.close, volume: d.volume, amount: 0,
    }));
    renderDetailData([...rows].reverse(), null);
    const idx = App.indexList.find(i => i.code === code);
    if (idx) {
      const up = idx.change >= 0;
      const c = up ? 'var(--r)' : 'var(--g)';
      const sg = idx.change > 0 ? '+' : '';
      document.getElementById('dtPrice').textContent = idx.close.toFixed(2);
      document.getElementById('dtPrice').style.color = c;
      document.getElementById('dtChange').innerHTML =
        `<span style="color:${c}">${sg}${idx.change.toFixed(2)}&nbsp;&nbsp;${sg}${idx.change_pct}%</span>`;
    }
  } catch (e) { toast('加载失败', 'error'); }
}

/* ===== Open ETF detail (reuses index K-line API) ===== */
async function openETFDetail(code, name) {
  App.currentDetail = code;
  App.currentDetailType = 'etf';
  document.getElementById('dtEmpty').style.display = 'none';
  document.getElementById('dtContent').style.display = 'block';
  switchTab('detail', true);

  document.getElementById('dtName').textContent = name;
  document.getElementById('dtCode').textContent = code;
  document.getElementById('dtIndustry').textContent = 'ETF';
  document.getElementById('dtIndustry').style.display = '';
  detailResearchBtn(true);
  detailSyncBtn(true);
  resetDetailDisplay();

  const t = today();
  try {
    const infoR = await api(`/api/v1/data/${code}/info`);
    const hasData = infoR.count > 0;
    const isRecent = hasData && infoR.max_date >= t;
    if (!hasData) {
      toast('首次加载 ' + code + ' 数据…');
      await fetchSilent(code, '2025-01-01', t);
    } else if (!isRecent) {
      await fetchSilent(code, infoR.max_date, t);
    }
    const daily = await api(`/api/v1/data/${code}/daily?start=${DETAIL_FULL_HISTORY_START}&end=${t}&limit=10000`);
    renderDetailData(daily.data || [], null);
    const etf = App.etfList.find(i => i.code === code) || App.etfUniverseList.find(i => i.code === code);
    if (etf) {
      const up = etf.change >= 0;
      const c = up ? 'var(--r)' : 'var(--g)';
      const sg = etf.change > 0 ? '+' : '';
      document.getElementById('dtPrice').textContent = etf.close.toFixed(4);
      document.getElementById('dtPrice').style.color = c;
      document.getElementById('dtChange').innerHTML =
        `<span style="color:${c}">${sg}${etf.change.toFixed(4)}&nbsp;&nbsp;${sg}${etf.change_pct}%</span>`;
    }
  } catch (e) { toast('加载失败', 'error'); }
}

function resetDetailDisplay() {
  document.getElementById('dtPrice').textContent = '--';
  document.getElementById('dtPrice').style.color = '';
  document.getElementById('dtChange').textContent = '';
  document.getElementById('dtDate').textContent = '';
  document.getElementById('dtMeta').innerHTML = '';
  document.getElementById('dtChart').innerHTML = '';
  document.getElementById('dtFactors').innerHTML =
    '<div style="color:var(--t3);font-size:.78rem;padding:12px;grid-column:1/-1"><span class="spinner"></span>加载中…</div>';
  const wb = document.getElementById('dtWatchBtn');
  if (wb) { wb.textContent = '+ 自选'; wb.disabled = false; }
  const rb = document.getElementById('dtResearchBtn');
  if (rb && rb.style.display !== 'none') { rb.textContent = '研究'; rb.disabled = false; }
  const sb = document.getElementById('dtFullSyncBtn');
  if (sb && sb.style.display !== 'none') { sb.textContent = '更新补齐'; sb.disabled = false; }
  App.detailDailyRows = [];
  resetChartTabToDay();
  checkWatchStatus();
}

async function checkWatchStatus() {
  if (!App.currentDetail) return;
  const btn = document.getElementById('dtWatchBtn');
  if (!btn) return;
  try {
    const r = await api('/api/v1/watchlist');
    const items = r.items || [];
    const found = items.some(i => i.symbol === App.currentDetail);
    if (found) {
      btn.textContent = '已自选';
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-outline');
    } else {
      btn.textContent = '+ 自选';
      btn.classList.remove('btn-outline');
      btn.classList.add('btn-primary');
    }
  } catch (e) { /* silent */ }
}

function renderDetailData(rows, factors) {
  if (rows.length) {
    const last = rows[0], prev = rows[1] || last;
    const price = last.close, chg = price - prev.close;
    const pctV = prev.close ? chg / prev.close * 100 : 0;
    const up = chg >= 0;
    const c = up ? 'var(--r)' : 'var(--g)';
    const sg = up ? '+' : '';

    document.getElementById('dtPrice').textContent = price.toFixed(2);
    document.getElementById('dtPrice').style.color = c;
    document.getElementById('dtChange').innerHTML =
      `<span style="color:${c}">${sg}${chg.toFixed(2)}&nbsp;&nbsp;${sg}${pctV.toFixed(2)}%</span>`;
    document.getElementById('dtDate').textContent = last.trade_date || '';

    const amp = prev.close ? ((last.high - last.low) / prev.close * 100).toFixed(2) + '%' : '--';
    const highC = last.high > prev.close ? 'var(--r)' : last.high < prev.close ? 'var(--g)' : '';
    const lowC  = last.low < prev.close ? 'var(--g)' : last.low > prev.close ? 'var(--r)' : '';

    document.getElementById('dtMeta').innerHTML = [
      xqCell('高', last.high?.toFixed(2), highC),
      xqCell('开', last.open?.toFixed(2)),
      xqCell('量', fV(last.volume)),
      xqCell('振幅', amp),
      xqCell('低', last.low?.toFixed(2), lowC),
      xqCell('昨收', prev.close?.toFixed(2)),
      xqCell('额', fV(last.amount)),
      xqCell('区间', rows.length + '日'),
    ].join('');

    const ascRows = rows.slice().reverse();
    App.detailDailyRows = ascRows;
    renderChart(document.getElementById('dtChart'), ascRows, 260);
  }

  if (factors && factors.sample?.length) {
    const last = factors.sample[factors.sample.length - 1];
    document.getElementById('dtFactors').innerHTML = factors.columns.map(c =>
      `<div class="factor-item"><div class="f-name">${FACTOR_CN[c] || c}</div><div class="f-val">${last[c] != null ? Number(last[c]).toFixed(4) : '--'}</div></div>`
    ).join('');
  } else if (!factors) {
    document.getElementById('dtFactors').innerHTML =
      '<div style="color:var(--t3);font-size:.78rem;padding:12px;grid-column:1/-1">指数/ETF暂不支持技术因子计算</div>';
  }

  loadDetailSignals();
}

function xqCell(label, val, color) {
  const vc = color ? ` style="color:${color}"` : '';
  return `<div class="xq-cell"><span class="xq-l">${label}</span><span class="xq-v"${vc}>${val ?? '--'}</span></div>`;
}

async function jumpDetailToResearch() {
  if (!App.currentDetail || !['stock', 'etf'].includes(App.currentDetailType || '')) return;
  const btn = document.getElementById('dtResearchBtn');
  if (btn?.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '跳转中…';
  }

  try {
    let start = '';
    let end = '';
    if (App.detailDailyRows.length) {
      start = App.detailDailyRows[0].trade_date || '';
      end = App.detailDailyRows[App.detailDailyRows.length - 1].trade_date || '';
    } else {
      const info = await api(`/api/v1/data/${App.currentDetail}/info`);
      start = info.min_date || '2025-01-01';
      end = info.max_date || today();
    }

    if (typeof rsApplyScope === 'function') rsApplyScope(App.currentDetail, start, end);
    else {
      document.getElementById('rsSymbol').value = App.currentDetail;
      document.getElementById('rsStart').value = start;
      document.getElementById('rsEnd').value = end;
    }
    switchTab('research');
    toast(`已切到研究页：${App.currentDetail} ${start} ~ ${end}`);
  } catch (e) {
    toast('跳转研究页失败', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '研究';
    }
  }
}

async function addToWatchFromDetail() {
  if (!App.currentDetail) return;
  const sym = App.currentDetail;
  const btn = document.getElementById('dtWatchBtn');
  if (btn && btn.textContent === '已自选') return;
  if (btn) { btn.disabled = true; btn.textContent = '添加中…'; }
  try {
    await api('/api/v1/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym }),
    });
    toast(sym + ' 已加自选');
    if (btn) {
      btn.textContent = '已自选';
      btn.disabled = false;
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-outline');
    }
  } catch (e) {
    toast('加自选失败', 'error');
    if (btn) { btn.textContent = '+ 自选'; btn.disabled = false; }
  }
}

async function updateDetailFullHistory() {
  if (!App.currentDetail) return;
  const sym = App.currentDetail;
  const kind = App.currentDetailType;
  const name = document.getElementById('dtName')?.textContent || sym;
  const btn = document.getElementById('dtFullSyncBtn');
  if (btn?.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '补齐中…';
  }
  try {
    const r = await api('/api/v1/data/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, start: DETAIL_FULL_HISTORY_START, end: today() }),
    });
    toast(`${sym} 历史补齐完成，累计 ${r.rows_in_db || 0} 条`);
    if (kind === 'etf') await openETFDetail(sym, name);
    else await openDetail(sym);
  } catch (e) {
    toast('历史补齐失败', 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '更新补齐';
    }
  }
}

function detailBacktest() {
  if (!App.currentDetail) return;
  document.getElementById('btSymbol').value = App.currentDetail;
  switchTab('backtest');
}

async function detailBacktestAll() {
  if (!App.currentDetail) return;
  const sym = App.currentDetail;
  const t = today();
  toast('全策略回测 ' + sym + '…');
  try {
    const strategies = ['ma_cross', 'rsi_reversal', 'bollinger_breakout'];
    const results = await Promise.all(strategies.map(sid =>
      api('/api/v1/backtest', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy_id: sid, symbol: sym, start: '2025-01-01', end: t, params: {} }),
      }).catch(() => null)
    ));
    const positive = results.filter(r => r && r.total_return > 0);
    if (positive.length) toast(`${positive.length}/${strategies.length} 个策略盈利`);
    else toast('暂无正收益策略', 'error');
    switchTab('strategy');
  } catch (e) { toast('回测失败', 'error'); }
}

/* ===== ML Signal Section ===== */
async function loadDetailSignals() {
  const card = document.getElementById('dtSignalCard');
  const content = document.getElementById('dtSignalContent');
  if (!App.currentDetail) { card.style.display = 'none'; return; }

  try {
    const r = await api('/api/v1/ml/models');
    const models = (r.models || []).filter(m => m.symbol === App.currentDetail);
    if (!models.length) {
      card.style.display = 'block';
      content.innerHTML = '<div style="font-size:.76rem;color:var(--t3)">暂无该标的的已训练模型，点击「一键研究」开始</div>';
      return;
    }

    card.style.display = 'block';
    const best = models[0];
    const pred = await api('/api/v1/ml/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: best.model_id, symbol: App.currentDetail, start: '2026-03-01' }),
    });

    const allPreds = pred.predictions || [];
    const preds = allPreds.slice(-5);
    let html = `<div style="font-size:.7rem;color:var(--t3);margin-bottom:4px">下一交易日操作建议 · 模型: ${best.model_type} | AUC: ${(best.test_metrics?.auc||0).toFixed(3)}</div>`;
    preds.forEach((p, idx) => {
      const globalIdx = allPreds.length - preds.length + idx;
      const prev = globalIdx > 0 ? allPreds[globalIdx - 1] : null;
      const action = nextTradeActionFromPrediction(p.prediction, prev?.prediction);
      html += `<div class="signal-row">
        <span class="signal-date">${p.date}</span>
        <span class="signal-badge ${actionBadgeClass(action)}">${action}</span>
        <span class="signal-prob">${p.probability != null ? (p.probability * 100).toFixed(1) + '%' : '--'}</span>
      </div>`;
    });
    content.innerHTML = html;
  } catch (e) {
    card.style.display = 'block';
    content.innerHTML = '<div style="font-size:.76rem;color:var(--t3)">暂无信号数据，点击「一键研究」生成</div>';
  }
}

async function runDetailPipeline() {
  if (!App.currentDetail) return;
  const btn = document.getElementById('dtPipelineBtn');
  const content = document.getElementById('dtSignalContent');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';

  try {
    const r = await api('/api/v1/ml/pipeline', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: App.currentDetail, model_type: 'lightgbm', label_col: 'label_dir_5', forward_period: 5, train_ratio: 0.8, wf_train_days: 200, wf_test_days: 20, wf_step_days: 20, start: '2025-01-01' }),
    });

    const sig = r.latest_signal || {};
    const tr = r.train_result || {};
    const tm = tr.test_metrics || {};
    let html = `<div style="font-size:.7rem;color:var(--t3);margin-bottom:4px">下一交易日操作建议 · 模型: ${tr.model_type || 'lightgbm'} | AUC: ${(tm.auc||0).toFixed(3)} | F1: ${(tm.f1||0).toFixed(3)}</div>`;
    if (sig.predictions?.length) {
      sig.predictions.forEach((p, idx) => {
        const prev = idx > 0 ? sig.predictions[idx - 1] : null;
        const action = nextTradeActionFromPrediction(p.prediction, prev?.prediction);
        html += `<div class="signal-row">
          <span class="signal-date">${p.date}</span>
          <span class="signal-badge ${actionBadgeClass(action)}">${action}</span>
          <span class="signal-prob">${p.probability != null ? (p.probability * 100).toFixed(1) + '%' : '--'}</span>
        </div>`;
      });
    } else {
      html += '<div style="color:var(--t3);font-size:.76rem">Pipeline 完成但无信号输出</div>';
    }
    content.innerHTML = html;
    toast('Pipeline 完成');
  } catch (e) {
    content.innerHTML = `<div style="color:var(--r);font-size:.76rem">失败: ${e.message}</div>`;
    toast('Pipeline 失败', 'error');
  }
  btn.disabled = false; btn.textContent = '一键研究';
}
