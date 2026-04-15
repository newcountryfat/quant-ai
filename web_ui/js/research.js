/**
 * Research page: factor library, compute, evaluate, walk-forward, labels, feature selection.
 */
const FACTOR_CATEGORIES = {
  'Trend': ['ma_5','ma_10','ma_20','ma_60','ema_5','ema_10','ema_20','ema_60','macd','macd_signal','macd_hist','adx','plus_di','minus_di'],
  'Momentum': ['rsi_14','roc_5','roc_10','roc_20','cci','williams_r','stoch_k','stoch_d'],
  'Volatility': ['bb_upper','bb_middle','bb_lower','bb_width','bb_pct','atr','atr_pct','rvol_5','rvol_10','rvol_20'],
  'Volume': ['obv','vwap','volume_ratio'],
  'Price': ['ret_1','ret_5','ret_10','ret_20','log_ret','hl_range','co_range'],
};

let _rsLibLoaded = false;
let _rsFormBound = false;

async function loadResearchPage() {
  const endEl = document.getElementById('rsEnd');
  if (endEl && !endEl.value) endEl.value = today();
  rsInitResearchForm();
  if (!_rsLibLoaded) await rsLoadFactorLib();
}

async function rsLoadFactorLib() {
  const el = document.getElementById('rsFactorLib');
  const countEl = document.getElementById('rsFactorCount');
  try {
    const r = await api('/api/v1/factors/library/list');
    App.factorLibrary = r.factors || [];
    countEl.textContent = `(${App.factorLibrary.length} 个)`;

    let html = '';
    for (const [cat, factors] of Object.entries(FACTOR_CATEGORIES)) {
      html += `<div class="fl-cat">${cat}</div>`;
      factors.forEach(f => {
        const exists = App.factorLibrary.includes(f);
        html += `<span class="fl-tag" style="${exists ? '' : 'opacity:.4'}">${f}</span>`;
      });
    }
    const extra = App.factorLibrary.filter(f => !Object.values(FACTOR_CATEGORIES).flat().includes(f));
    if (extra.length) {
      html += `<div class="fl-cat">Other</div>`;
      extra.forEach(f => { html += `<span class="fl-tag">${f}</span>`; });
    }
    el.innerHTML = html;
    _rsLibLoaded = true;
  } catch (e) {
    el.innerHTML = '<span style="color:var(--t3)">加载失败</span>';
  }
}

function rsGetScope() {
  const sym = document.getElementById('rsSymbol').value.trim();
  const start = document.getElementById('rsStart').value || '2025-01-01';
  const end = document.getElementById('rsEnd').value || today();
  if (!sym) { toast('请输入标的', 'error'); return null; }
  if (start && end && start > end) {
    toast('开始日期不能晚于结束日期', 'error');
    return null;
  }
  return { sym, start, end };
}

function rsClearBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = 'none';
  el.innerHTML = '';
}

function rsClearHistory() {
  const card = document.getElementById('rsEvalHistCard');
  const table = document.getElementById('rsEvalHistTable');
  if (card) card.style.display = 'none';
  if (table) table.innerHTML = '';
}

function rsClearResearchResults() {
  ['rsComputeResult', 'rsEvalResult', 'rsWfResult', 'rsLabelsResult', 'rsFeatResult'].forEach(rsClearBlock);
  rsClearHistory();
}

function rsInitResearchForm() {
  if (_rsFormBound) return;
  ['rsSymbol', 'rsStart', 'rsEnd', 'rsFwdPeriod'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', rsClearResearchResults);
    el.addEventListener('input', rsClearResearchResults);
  });
  _rsFormBound = true;
}

function rsApplyScope(sym, start, end) {
  if (sym != null) document.getElementById('rsSymbol').value = sym;
  if (start != null) document.getElementById('rsStart').value = start;
  if (end != null) document.getElementById('rsEnd').value = end;
  rsClearResearchResults();
}

function rsFmtNum(v, digits = 4) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : '--';
}

function rsRenderWidePreview(rows, factorNames, title = '样例预览') {
  if (!rows?.length || !factorNames?.length) return '';
  const cols = factorNames.slice(0, 8);
  let html = `<div style="font-size:.68rem;color:var(--t3);margin:8px 0 4px">${title}${factorNames.length > cols.length ? `，展示前 ${cols.length} 个因子` : ''}</div>`;
  html += '<div style="overflow-x:auto"><table class="eval-table"><thead><tr><th>trade_date</th>';
  cols.forEach(col => { html += `<th title="${col}">${FACTOR_CN[col] || col}</th>`; });
  html += '</tr></thead><tbody>';
  rows.forEach(row => {
    html += `<tr><td>${row.trade_date || '--'}</td>`;
    cols.forEach(col => { html += `<td>${rsFmtNum(row[col])}</td>`; });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  return html;
}

function rsLongRowsToWidePreview(items) {
  if (!items?.length) return { rows: [], factorNames: [] };
  const grouped = new Map();
  const factorNames = [];
  const seenFactors = new Set();
  items.forEach(item => {
    if (!grouped.has(item.trade_date)) grouped.set(item.trade_date, { trade_date: item.trade_date });
    grouped.get(item.trade_date)[item.factor_name] = item.value;
    if (!seenFactors.has(item.factor_name)) {
      seenFactors.add(item.factor_name);
      factorNames.push(item.factor_name);
    }
  });
  const rows = Array.from(grouped.values())
    .sort((a, b) => String(b.trade_date).localeCompare(String(a.trade_date)))
    .slice(0, 6);
  return { rows, factorNames };
}

function rsRenderStoredFactorQuery(data, scope) {
  const summary = data.summary || {};
  if (!summary.date_count) {
    return `<div style="font-size:.78rem;color:var(--t3);line-height:1.7">
      <b>${scope.sym}</b> 在 <span class="mono">${scope.start}</span> ~ <span class="mono">${scope.end}</span> 区间内暂无已持久化因子结果
    </div>`;
  }

  const preview = rsLongRowsToWidePreview(data.items || []);
  const rangeText = `${summary.min_date || scope.start} ~ ${summary.max_date || scope.end}`;
  return `<div style="font-size:.78rem;color:var(--t2);line-height:1.7">
    <b>${scope.sym}</b> 已计算区间: <span class="mono">${rangeText}</span><br>
    交易日: <span class="mono">${summary.date_count}</span>，
    因子数: <span class="mono">${summary.factor_count}</span>，
    存储值: <span class="mono">${summary.row_count}</span>
  </div>${rsRenderWidePreview(preview.rows, preview.factorNames, '已持久化因子预览')}`;
}

async function rsFetchStoredFactors(scope, limit = 240) {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (scope.start) qs.set('start', scope.start);
  if (scope.end) qs.set('end', scope.end);
  return api(`/api/v1/factors/values/${encodeURIComponent(scope.sym)}?${qs.toString()}`);
}

async function rsQueryFactors() {
  const btn = document.getElementById('rsQueryBtn');
  const result = document.getElementById('rsComputeResult');
  const scope = rsGetScope();
  if (!scope) return;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>查询中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>查询中…</div>';

  try {
    const data = await rsFetchStoredFactors(scope, 320);
    result.innerHTML = rsRenderStoredFactorQuery(data, scope);
    toast(data.summary?.date_count ? '查询完成' : '该区间暂无已计算因子');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">查询失败: ${e.message}</div>`;
    toast('查询失败', 'error');
  }

  btn.disabled = false;
  btn.textContent = '查询';
}

async function rsCompute() {
  const btn = document.getElementById('rsComputeBtn');
  const result = document.getElementById('rsComputeResult');
  const scope = rsGetScope();
  if (!scope) return;
  const { sym, start, end } = scope;

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>计算中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>计算中…</div>';

  try {
    const existing = await rsFetchStoredFactors(scope, 1);
    if ((existing.summary?.date_count || 0) > 0) {
      const ok = window.confirm(
        `${sym} 在 ${start} ~ ${end} 区间已存在 ${existing.summary.date_count} 个交易日、${existing.summary.factor_count} 个因子的计算结果，是否重新计算并覆盖？`
      );
      if (!ok) {
        result.innerHTML = rsRenderStoredFactorQuery(existing, scope);
        toast('已取消重算');
        return;
      }
    }

    const r = await api('/api/v1/factors/batch-compute', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, start, end, persist: true }),
    });
    result.innerHTML = `<div style="font-size:.78rem;color:var(--t2);line-height:1.7">
      <b>${sym}</b> 计算完成<br>
      请求区间: <span class="mono">${start}</span> ~ <span class="mono">${end}</span><br>
      实际数据: <span class="mono">${r.data_start || start}</span> ~ <span class="mono">${r.data_end || end}</span><br>
      结果: <span class="mono">${r.rows}</span> 行 × <span class="mono">${(r.factors||[]).length}</span> 因子，已持久化
    </div>${rsRenderWidePreview(r.sample || [], r.factors || [], '本次计算预览')}`;
    toast('因子计算完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">计算失败: ${e.message}</div>`;
    toast('因子计算失败', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '计算因子';
  }
}

async function rsEvaluate() {
  const btn = document.getElementById('rsEvalBtn');
  const result = document.getElementById('rsEvalResult');
  const scope = rsGetScope();
  if (!scope) return;
  const { sym, start, end } = scope;
  const fwd = parseInt(document.getElementById('rsFwdPeriod').value) || 5;

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>评估中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>评估中…</div>';

  try {
    const payload = await api('/api/v1/factors/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, forward_period: fwd, start, end, persist: true }),
    });
    const data = payload.results || payload || [];

    if (!data.length) { result.innerHTML = '<div style="color:var(--t3);font-size:.78rem">无评估结果</div>'; return; }

    const sorted = data.sort((a, b) => Math.abs(b.ic_mean || 0) - Math.abs(a.ic_mean || 0));
    let html = '<div style="overflow-x:auto"><table class="eval-table"><thead><tr>';
    html += '<th>因子</th><th>IC Mean</th><th>ICIR</th><th>Rank IC</th><th>Rank ICIR</th><th>IC+%</th><th>单调性</th>';
    html += '</tr></thead><tbody>';
    sorted.forEach(r => {
      const icC = (r.ic_mean || 0) > 0 ? 'color:var(--r)' : (r.ic_mean || 0) < 0 ? 'color:var(--g)' : '';
      html += `<tr>
        <td style="font-weight:600;color:var(--t1)">${r.factor_name}</td>
        <td style="${icC}">${(r.ic_mean||0).toFixed(4)}</td>
        <td>${(r.icir||0).toFixed(4)}</td>
        <td>${(r.rank_ic_mean||0).toFixed(4)}</td>
        <td>${(r.rank_icir||0).toFixed(4)}</td>
        <td>${((r.ic_positive_ratio||0)*100).toFixed(0)}%</td>
        <td>${(r.monotonicity||0).toFixed(4)}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
    result.innerHTML = `<div style="font-size:.7rem;color:var(--t3);margin-bottom:4px">${sorted.length} 个因子评估完成 (forward=${fwd}d)</div>` + html;
    toast('评估完成');
    rsLoadEvalHistory(sym);
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">评估失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '评估因子';
}

async function rsWalkForward() {
  const btn = document.getElementById('rsWfBtn');
  const result = document.getElementById('rsWfResult');
  const scope = rsGetScope();
  if (!scope) return;
  const { sym, start, end } = scope;
  const fwd = parseInt(document.getElementById('rsFwdPeriod').value) || 5;

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>验证中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>Walk-Forward 验证中…</div>';

  try {
    const payload = await api('/api/v1/factors/walk-forward', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, train_days: 120, test_days: 20, step_days: 20, forward_period: fwd, start, end }),
    });
    const data = payload.results || payload || [];

    if (!data.length) { result.innerHTML = '<div style="color:var(--t3);font-size:.78rem">无结果</div>'; return; }

    let html = '<div style="overflow-x:auto"><table class="eval-table"><thead><tr>';
    html += '<th>因子</th><th>Folds</th><th>Avg Test IC</th><th>Avg Return</th><th>Avg Sharpe</th><th>IC 一致性</th>';
    html += '</tr></thead><tbody>';
    data.forEach(r => {
      html += `<tr>
        <td style="font-weight:600;color:var(--t1)">${r.factor_name}</td>
        <td>${r.n_folds}</td>
        <td>${(r.avg_test_ic||0).toFixed(4)}</td>
        <td style="color:${(r.avg_test_return||0)>=0?'var(--r)':'var(--g)'}">${((r.avg_test_return||0)*100).toFixed(2)}%</td>
        <td>${(r.avg_test_sharpe||0).toFixed(4)}</td>
        <td>${((r.ic_consistency||0)*100).toFixed(0)}%</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
    result.innerHTML = `<div style="font-size:.7rem;color:var(--t3);margin-bottom:4px">${data.length} 因子 Walk-Forward 结果</div>` + html;
    toast('Walk-Forward 完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = 'Walk-Forward';
}

async function rsLabels() {
  const btn = document.getElementById('rsLabelsBtn');
  const result = document.getElementById('rsLabelsResult');
  const scope = rsGetScope();
  if (!scope) return;
  const { sym, start, end } = scope;

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>生成中';
  result.style.display = 'block';

  try {
    const r = await api('/api/v1/ml/labels', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, forward_periods: [5, 10, 20], start, end }),
    });
    const trunc = r.truncated_tail || 0;
    const validRows = r.valid_rows || r.rows;
    const nanInfo = r.nan_per_period || {};
    const nanDetail = Object.entries(nanInfo).map(([p, n]) => `${p}天: 尾部${n}行NaN`).join('，');
    let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px;line-height:1.7">
      <b>${sym}</b>: ${r.rows} 行, 全有效: <b>${validRows}</b> 行, 标签列: ${(r.labels||[]).join(', ')}<br>
      请求区间: <span class="mono">${start}</span> ~ <span class="mono">${end}</span><br>
      实际数据: <span class="mono">${r.data_start || start}</span> ~ <span class="mono">${r.data_end || end}</span>
      ${r.valid_end ? `<br>有效截止(所有前瞻期): <span class="mono">${r.valid_end}</span>` : ''}
      ${trunc > 0 ? `<br><span style="color:var(--warn,#e6a23c)">⚠ 前瞻期截断: ${nanDetail || trunc + '行'}，尾部标签为 NaN 不参与训练/挖掘</span>` : ''}
    </div>`;
    if (r.sample && r.sample.length) {
      html += '<div style="overflow-x:auto"><table class="eval-table"><thead><tr>';
      const cols = Object.keys(r.sample[0]);
      cols.forEach(c => { html += `<th>${c}</th>`; });
      html += '</tr></thead><tbody>';
      r.sample.forEach(row => {
        html += '<tr>';
        cols.forEach(c => { html += `<td>${row[c] != null ? (typeof row[c] === 'number' ? row[c].toFixed(4) : row[c]) : '--'}</td>`; });
        html += '</tr>';
      });
      html += '</tbody></table></div>';
    }
    result.innerHTML = html;
    toast('标签生成完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '生成标签';
}

async function rsFeatureSelect() {
  const btn = document.getElementById('rsFeatBtn');
  const result = document.getElementById('rsFeatResult');
  const scope = rsGetScope();
  if (!scope) return;
  const { sym, start, end } = scope;

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>筛选中';
  result.style.display = 'block';

  try {
    const r = await api('/api/v1/ml/feature-select', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, start, end }),
    });
    const rp = r.report || {};
    let html = `<div style="font-size:.78rem;color:var(--t2);line-height:1.8;margin-bottom:6px">
      <b>请求区间:</b> <span class="mono">${start}</span> ~ <span class="mono">${end}</span><br>
      <b>实际数据:</b> <span class="mono">${r.data_start || start}</span> ~ <span class="mono">${r.data_end || end}</span><br>
      <b>原始特征:</b> ${rp.original_count} → <b>方差过滤后:</b> ${rp.after_variance} → <b>相关性去重后:</b> ${rp.after_correlation} → <b>最终:</b> <span style="color:var(--ac);font-weight:700">${rp.final_count}</span></div>`;

    if (rp.dropped_correlation?.length) {
      html += `<div style="font-size:.72rem;color:var(--t3);margin-bottom:4px">相关性移除 (${rp.dropped_correlation.length}): ${rp.dropped_correlation.join(', ')}</div>`;
    }
    if (rp.feature_ranking?.length) {
      html += '<div style="font-size:.68rem;font-weight:700;text-transform:uppercase;color:var(--t3);margin:6px 0 3px">Top 特征 (by |IC|)</div>';
      html += '<div style="overflow-x:auto"><table class="eval-table"><thead><tr><th>#</th><th>特征</th><th>|IC|</th><th>IC</th></tr></thead><tbody>';
      rp.feature_ranking.slice(0, 20).forEach((f, i) => {
        html += `<tr><td>${i + 1}</td><td style="font-weight:600;color:var(--t1)">${f.feature}</td><td>${f.abs_ic?.toFixed(4)}</td><td style="color:${f.ic >= 0 ? 'var(--r)' : 'var(--g)'}">${f.ic?.toFixed(4)}</td></tr>`;
      });
      html += '</tbody></table></div>';
    }
    result.innerHTML = html;
    toast('特征筛选完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '特征筛选';
}

async function rsLoadEvalHistory(sym) {
  const card = document.getElementById('rsEvalHistCard');
  const table = document.getElementById('rsEvalHistTable');
  try {
    const payload = await api(`/api/v1/factors/eval-history?symbol=${sym}&limit=50`);
    const data = payload.items || payload || [];
    if (!data.length) { card.style.display = 'none'; return; }
    card.style.display = 'block';
    let html = '<thead><tr><th>因子</th><th>IC Mean</th><th>ICIR</th><th>Rank IC</th><th>前瞻期</th><th>时间</th></tr></thead><tbody>';
    data.forEach(r => {
      html += `<tr><td>${r.factor_name}</td><td class="mono">${(r.ic_mean||0).toFixed(4)}</td><td class="mono">${(r.icir||0).toFixed(4)}</td><td class="mono">${(r.rank_ic_mean||0).toFixed(4)}</td><td>${r.forward_period}d</td><td style="color:var(--t3);font-size:.68rem">${(r.evaluated_at||'').slice(0,16)}</td></tr>`;
    });
    html += '</tbody>';
    table.innerHTML = html;
  } catch (e) { card.style.display = 'none'; }
}
