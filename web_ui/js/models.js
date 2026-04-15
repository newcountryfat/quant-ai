/**
 * Models page: ML training, walk-forward, GP mining, pipeline, model list, predict, backtest.
 */

/**
 * Replace x0, x1, ... in a GP expression string with actual factor names.
 * featureCols is an array where index i maps to xi.
 */
function gpTranslateExpr(expr, featureCols) {
  if (!featureCols || !featureCols.length) return expr;
  return expr.replace(/\bx(\d+)\b/g, (match, idx) => {
    const i = parseInt(idx, 10);
    return i < featureCols.length ? featureCols[i] : match;
  });
}

/**
 * Reverse translate: replace factor names back to x0, x1, ... for backend.
 * Sorts names by descending length to avoid partial matches.
 */
function gpReverseTranslate(expr, featureCols) {
  if (!featureCols || !featureCols.length) return expr;
  const sorted = featureCols.map((name, i) => ({ name, i }))
    .sort((a, b) => b.name.length - a.name.length);
  let out = expr;
  for (const { name, i } of sorted) {
    out = out.replace(new RegExp('\\b' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'g'), `x${i}`);
  }
  return out;
}

/* ===== Pipeline ===== */
async function mlRunPipeline() {
  const btn = document.getElementById('mlPipeBtn');
  const result = document.getElementById('mlPipeResult');
  const sym = document.getElementById('mlPipeSym').value.trim();
  const model = document.getElementById('mlPipeModel').value;
  const label = document.getElementById('mlPipeLabel').value;
  const start = document.getElementById('mlPipeStart').value;
  if (!sym) { toast('请输入标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Pipeline 运行中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:16px"><span class="spinner"></span>正在执行完整 Pipeline（因子→标签→筛选→训练→验证→信号）…</div>';

  try {
    const r = await api('/api/v1/ml/pipeline', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, model_type: model, label_col: label, forward_period: 5, train_ratio: 0.8, wf_train_days: 200, wf_test_days: 20, wf_step_days: 20, start }),
    });
    result.innerHTML = renderPipelineResult(r);
    toast('Pipeline 完成');
    mlLoadModels();
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">Pipeline 失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '运行 Pipeline';
}

function renderPipelineResult(r) {
  let html = '';

  html += `<div class="pipe-section"><div class="ps-title">特征筛选</div>
    <div style="font-size:.78rem;color:var(--t2)">原始 <b>${r.n_features_original}</b> → 筛选后 <b style="color:var(--ac)">${r.n_features_selected}</b> 个特征</div></div>`;

  const tr = r.train_result || {};
  const tm = tr.test_metrics || {};
  if (tr.model_id) {
    html += `<div class="pipe-section"><div class="ps-title">训练结果 (${tr.model_type})</div>`;
    html += '<div class="bt-grid" style="margin-bottom:6px">';
    html += mCard('Accuracy', (tm.accuracy||0).toFixed(4), tm.accuracy >= 0.55 ? 'positive' : '');
    html += mCard('F1', (tm.f1||0).toFixed(4), tm.f1 >= 0.5 ? 'positive' : '');
    html += mCard('AUC', (tm.auc||0).toFixed(4), tm.auc >= 0.6 ? 'positive' : '');
    html += mCard('Precision', (tm.precision||0).toFixed(4), '');
    html += mCard('Recall', (tm.recall||0).toFixed(4), '');
    html += mCard('Log Loss', (tm.log_loss||0).toFixed(4), '');
    html += '</div>';
    if (tr.feature_importance?.length) {
      html += '<div style="font-size:.68rem;color:var(--t3);margin-bottom:3px">Top 特征</div><div style="display:flex;flex-wrap:wrap;gap:4px">';
      tr.feature_importance.slice(0, 10).forEach(f => {
        html += `<span class="fl-tag">${f.feature}: ${f.importance}</span>`;
      });
      html += '</div>';
    }
    html += '</div>';
  }

  const wf = r.walk_forward_result || {};
  if (wf.n_folds) {
    html += `<div class="pipe-section"><div class="ps-title">Walk-Forward (${wf.n_folds} folds)</div>`;
    html += '<div class="bt-grid" style="margin-bottom:6px">';
    html += mCard('Avg Acc', (wf.avg_accuracy||0).toFixed(4), wf.avg_accuracy >= 0.55 ? 'positive' : '');
    html += mCard('Avg F1', (wf.avg_f1||0).toFixed(4), '');
    html += mCard('Avg AUC', (wf.avg_auc||0).toFixed(4), wf.avg_auc >= 0.6 ? 'positive' : '');
    html += mCard('Cum Return', ((wf.cumulative_return||0)*100).toFixed(2)+'%', wf.cumulative_return >= 0 ? 'positive' : 'negative');
    html += mCard('Cum Sharpe', (wf.cumulative_sharpe||0).toFixed(2), wf.cumulative_sharpe >= 0 ? 'positive' : 'negative');
    html += mCard('Folds', wf.n_folds, '');
    html += '</div></div>';
  }

  const sig = r.latest_signal || {};
  if (sig.predictions?.length) {
    html += `<div class="pipe-section"><div class="ps-title">最新信号</div>`;
    sig.predictions.forEach(p => {
      const isLong = p.prediction === 1;
      html += `<div class="signal-row">
        <span class="signal-date">${p.date}</span>
        <span class="signal-badge ${isLong ? 'long' : 'short'}">${isLong ? '看多' : '看空'}</span>
        <span class="signal-prob">${p.probability != null ? (p.probability * 100).toFixed(1) + '%' : '--'}</span>
      </div>`;
    });
    html += '</div>';
  }

  return html;
}

function mCard(l, v, c) {
  return `<div class="bt-card"><div class="label">${l}</div><div class="val ${c}">${v}</div></div>`;
}

/* ===== Train ===== */
async function mlTrain() {
  const btn = document.getElementById('mlTrainBtn');
  const result = document.getElementById('mlTrainResult');
  const sym = document.getElementById('mlTrainSym').value.trim();
  const model = document.getElementById('mlTrainModel').value;
  const label = document.getElementById('mlTrainLabel').value;
  const start = document.getElementById('mlTrainStart').value;
  if (!sym) { toast('请输入标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>训练中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>训练中…</div>';

  try {
    const r = await api('/api/v1/ml/train', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, model_type: model, label_col: label, forward_period: 5, train_ratio: 0.8, start }),
    });
    const tm = r.test_metrics || {};
    let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px">模型 <span class="mono">${r.model_id}</span></div>`;
    html += '<div class="bt-grid" style="margin-bottom:6px">';
    html += mCard('Test Acc', (tm.accuracy||0).toFixed(4), tm.accuracy >= 0.55 ? 'positive' : '');
    html += mCard('Test F1', (tm.f1||0).toFixed(4), '');
    html += mCard('Test AUC', (tm.auc||0).toFixed(4), tm.auc >= 0.6 ? 'positive' : '');
    html += '</div>';
    if (r.feature_importance?.length) {
      html += '<div style="font-size:.68rem;color:var(--t3);margin-bottom:3px">Top 特征</div><div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px">';
      r.feature_importance.slice(0, 10).forEach(f => {
        html += `<span class="fl-tag">${f.feature}: ${f.importance}</span>`;
      });
      html += '</div>';
    }
    result.innerHTML = html;
    toast('训练完成');
    mlLoadModels();
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '训练模型';
}

/* ===== Model Walk-Forward ===== */
async function mlModelWF() {
  const btn = document.getElementById('mlWfBtn');
  const result = document.getElementById('mlWfResult');
  const sym = document.getElementById('mlTrainSym').value.trim();
  const model = document.getElementById('mlTrainModel').value;
  const label = document.getElementById('mlTrainLabel').value;
  const start = document.getElementById('mlTrainStart').value;
  if (!sym) { toast('请输入标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>验证中';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>Walk-Forward 中…</div>';

  try {
    const r = await api('/api/v1/ml/walk-forward', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, model_type: model, label_col: label, forward_period: 5, train_days: 200, test_days: 20, step_days: 20, start }),
    });
    let html = '<div class="bt-grid" style="margin-bottom:8px">';
    html += mCard('Avg Acc', (r.avg_accuracy||0).toFixed(4), '');
    html += mCard('Avg F1', (r.avg_f1||0).toFixed(4), '');
    html += mCard('Avg AUC', (r.avg_auc||0).toFixed(4), '');
    html += mCard('Cum Return', ((r.cumulative_return||0)*100).toFixed(2)+'%', r.cumulative_return >= 0 ? 'positive' : 'negative');
    html += mCard('Cum Sharpe', (r.cumulative_sharpe||0).toFixed(2), '');
    html += mCard('Folds', r.n_folds || 0, '');
    html += '</div>';

    if (r.folds?.length) {
      html += '<div style="overflow-x:auto"><table class="eval-table"><thead><tr><th>Fold</th><th>Train</th><th>Test</th><th>Acc</th><th>F1</th><th>AUC</th><th>Return</th><th>Sharpe</th></tr></thead><tbody>';
      r.folds.forEach(f => {
        html += `<tr><td>${f.fold}</td><td style="font-size:.64rem">${f.train_period}</td><td style="font-size:.64rem">${f.test_period}</td><td>${f.accuracy?.toFixed(3)}</td><td>${f.f1?.toFixed(3)}</td><td>${f.auc?.toFixed(3)}</td><td style="color:${f.fold_return>=0?'var(--r)':'var(--g)'}">${(f.fold_return*100).toFixed(2)}%</td><td>${f.fold_sharpe?.toFixed(2)}</td></tr>`;
      });
      html += '</tbody></table></div>';
    }
    result.innerHTML = html;
    toast('模型 Walk-Forward 完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '模型 Walk-Forward';
}

/* ===== GP Mining ===== */
let _gpLastMineSymbol = '';
let _gpLastExpressions = [];
let _gpLastFeatureCols = [];

async function mlGpMine() {
  const btn = document.getElementById('mlGpBtn');
  const result = document.getElementById('mlGpResult');
  const sym = document.getElementById('mlGpSym').value.trim();
  const start = document.getElementById('mlGpStart').value || '2024-01-01';
  const end = document.getElementById('mlGpEnd').value || today();
  const fwd = parseInt(document.getElementById('mlGpFwd').value) || 5;
  const pop = parseInt(document.getElementById('mlGpPop').value) || 200;
  const gen = parseInt(document.getElementById('mlGpGen').value) || 20;
  const maxDepth = parseInt(document.getElementById('mlGpDepth').value) || 5;
  const parsimony = parseFloat(document.getElementById('mlGpParsimony').value) || 0.005;
  const metric = document.getElementById('mlGpMetric').value;
  const save = document.getElementById('mlGpSave').checked;
  if (!sym) { toast('请输入标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>进化中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:16px"><span class="spinner"></span>GP 进化中 (可能需要10-30秒)…</div>';

  try {
    const r = await api('/api/v1/ml/gp-mine', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, forward_period: fwd, population_size: pop, n_generations: gen, max_depth: maxDepth, parsimony_coeff: parsimony, metric, save, start, end }),
    });
    _gpLastMineSymbol = sym;
    _gpLastExpressions = r.best_expressions || [];
    _gpLastFeatureCols = r.feature_cols || [];
    result.innerHTML = _renderGpMineResult(r, sym);
    toast('GP 挖掘完成');
    if (save) mlLoadGpList();
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '开始挖掘';
}

function _renderGpMineResult(r, sym) {
  const fc = r.feature_cols || _gpLastFeatureCols || [];
  let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px">${r.n_generations} 代进化, 种群 ${r.population_size}, Hall of Fame ${r.hall_of_fame_size} 个</div>`;
  (r.best_expressions || []).forEach((expr, i) => {
    const hasId = !!expr.gp_id;
    const translated = gpTranslateExpr(expr.expression, fc);
    const display = translated.length > 220 ? translated.slice(0, 220) + '…' : translated;
    html += `<div class="gp-expr">
      <span class="ge-rank">#${i + 1}</span>
      <span class="ge-code">${display}</span>
      <div class="ge-metrics">
        <span class="ge-m">Sharpe: <span>${expr.fitness_sharpe?.toFixed(4)}</span></span>
        <span class="ge-m">Return: <span style="color:${expr.fitness_return>=0?'var(--r)':'var(--g)'}">${(expr.fitness_return*100).toFixed(2)}%</span></span>
        <span class="ge-m">IC: <span>${expr.fitness_ic?.toFixed(4)}</span></span>
        <span class="ge-m">Depth: <span>${expr.depth}</span></span>
      </div>
      <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">`;
    if (hasId) {
      html += `<button class="btn btn-ghost btn-sm" style="font-size:.64rem" onclick="mlSelectGp('${expr.gp_id}','${sym}')">预测/回测</button>`;
      html += `<button class="btn btn-ghost btn-sm" style="font-size:.64rem" onclick="mlOpenGpEval('${expr.gp_id}','${sym}')">评估</button>`;
    } else {
      html += `<button class="btn btn-outline btn-sm" style="font-size:.64rem" onclick="mlGpSaveSingle(${i})" id="gpSaveBtn${i}">保存</button>`;
    }
    html += `</div></div>`;
  });
  return html;
}

async function mlGpSaveSingle(idx) {
  const expr = _gpLastExpressions[idx];
  if (!expr) { toast('表达式不存在', 'error'); return; }
  const sym = _gpLastMineSymbol || document.getElementById('mlGpSym').value.trim();
  const btn = document.getElementById('gpSaveBtn' + idx);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }

  try {
    const r = await api('/api/v1/ml/gp-save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expression: expr.expression, symbol: sym,
        metric: document.getElementById('mlGpMetric').value || 'sharpe',
        sharpe: expr.fitness_sharpe || 0, total_ret: expr.fitness_return || 0,
        ic: expr.fitness_ic || 0, depth: expr.depth || 0, tree_size: 0,
        data_start: document.getElementById('mlGpStart').value || '',
        data_end: document.getElementById('mlGpEnd').value || '',
        forward_period: parseInt(document.getElementById('mlGpFwd').value) || 5,
      }),
    });
    expr.gp_id = r.gp_id;
    const result = document.getElementById('mlGpResult');
    result.innerHTML = _renderGpMineResult({ n_generations: 0, population_size: 0, hall_of_fame_size: _gpLastExpressions.length, best_expressions: _gpLastExpressions }, sym);
    toast(`已保存: ${r.gp_id}`);
    mlLoadGpList();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '保存'; }
  }
}

/* ===== Saved GP List ===== */
async function mlLoadGpList() {
  const list = document.getElementById('mlGpSavedList');
  const empty = document.getElementById('mlGpSavedEmpty');
  try {
    const r = await api('/api/v1/ml/gp-list');
    const exprs = r.expressions || [];
    if (!exprs.length) { list.innerHTML = ''; empty.style.display = 'block'; return; }
    empty.style.display = 'none';
    list.innerHTML = exprs.map(e => {
      const fc = e.feature_cols || [];
      const translated = gpTranslateExpr(e.expression || '', fc);
      const display = translated.length > 180 ? translated.slice(0, 180) + '…' : translated;
      const ds = e.data_start || '--';
      const de = e.data_end || '--';
      const fwd = e.forward_period || '--';
      const pop = e.population_size || '--';
      const gen = e.n_generations || '--';
      const md = e.max_depth || '--';
      const pc = e.parsimony_coeff != null ? e.parsimony_coeff : '--';
      return `<div class="model-item">
        <div class="mi-head">
          <span class="mi-id">${e.gp_id}</span>
          <span class="mi-type gp">GP</span>
          <button class="btn btn-ghost btn-sm" style="font-size:.58rem;color:var(--t3);margin-left:auto;padding:2px 6px" onclick="event.stopPropagation();mlDeleteGp('${e.gp_id}')" title="删除">🗑</button>
        </div>
        <div class="mi-metrics">
          <div class="mi-m"><span class="mm-l">Sharpe</span><span class="mm-v">${(e.fitness_sharpe||0).toFixed(3)}</span></div>
          <div class="mi-m"><span class="mm-l">IC</span><span class="mm-v">${(e.fitness_ic||0).toFixed(4)}</span></div>
          <div class="mi-m"><span class="mm-l">Return</span><span class="mm-v">${((e.fitness_return||0)*100).toFixed(2)}%</span></div>
          <div class="mi-m"><span class="mm-l">Depth</span><span class="mm-v">${e.depth||'--'}</span></div>
          <div class="mi-m"><span class="mm-l">Nodes</span><span class="mm-v">${e.tree_size||'--'}</span></div>
          <div class="mi-m"><span class="mm-l">Symbol</span><span class="mm-v">${e.symbol||'--'}</span></div>
        </div>
        <div style="font-size:.6rem;color:var(--t3);margin-top:2px;display:flex;flex-wrap:wrap;gap:4px 10px">
          <span>区间: ${ds} ~ ${de}</span><span>前瞻: ${fwd}d</span>
          <span>种群: ${pop}</span><span>代数: ${gen}</span><span>深度≤${md}</span><span>惩罚: ${pc}</span>
        </div>
        <div style="font-size:.62rem;color:var(--t3);word-break:break-all;margin-top:4px;max-height:2.5em;overflow:hidden">${display}</div>
        <div style="margin-top:6px;display:flex;gap:6px">
          <button class="btn btn-ghost btn-sm" style="font-size:.64rem" onclick="event.stopPropagation();mlSelectGp('${e.gp_id}','${e.symbol||'sh000300'}')">预测/回测</button>
          <button class="btn btn-ghost btn-sm" style="font-size:.64rem" onclick="event.stopPropagation();mlOpenGpEval('${e.gp_id}','${e.symbol||'sh000300'}')">评估</button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { list.innerHTML = ''; empty.style.display = 'block'; }
}

async function mlDeleteGp(gpId) {
  if (!confirm(`确认删除 GP 表达式 ${gpId}？`)) return;
  try {
    await api(`/api/v1/ml/gp/${gpId}`, { method: 'DELETE' });
    toast('已删除 ' + gpId);
    mlLoadGpList();
  } catch (e) { toast('删除失败: ' + e.message, 'error'); }
}

/* ===== GP Evaluate ===== */
function mlOpenGpEval(gpId, symbol) {
  const card = document.getElementById('mlGpEvalCard');
  card.style.display = 'block';
  document.getElementById('mlGpEvalId').value = gpId;
  document.getElementById('mlGpEvalSym').value = symbol;
  if (!document.getElementById('mlGpEvalEnd').value) {
    document.getElementById('mlGpEvalEnd').value = today();
  }
  document.getElementById('mlGpEvalResult').style.display = 'none';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function mlGpEvaluate() {
  const btn = document.getElementById('mlGpEvalBtn');
  const result = document.getElementById('mlGpEvalResult');
  const gpId = document.getElementById('mlGpEvalId').value;
  const sym = document.getElementById('mlGpEvalSym').value.trim();
  const start = document.getElementById('mlGpEvalStart').value || '2024-01-01';
  const end = document.getElementById('mlGpEvalEnd').value || today();
  const fwd = parseInt(document.getElementById('mlGpEvalFwd').value) || 5;
  if (!gpId || !sym) { toast('请填写 GP ID 和标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>评估中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>计算中…</div>';

  try {
    const r = await api('/api/v1/ml/gp-evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gp_id: gpId, symbol: sym, forward_period: fwd, start, end }),
    });
    if (r.error) {
      result.innerHTML = `<div style="color:var(--r);font-size:.78rem">${r.error} (valid_rows: ${r.valid_rows || 0})</div>`;
    } else {
      result.innerHTML = _renderGpEvalResult(r, sym, start, end, fwd);
    }
    toast('评估完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">评估失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '评估';
}

function _renderGpEvalResult(r, sym, start, end, fwd) {
  let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px;line-height:1.7">
    <b>${r.gp_id}</b> @ <b>${sym}</b><br>
    评估区间: <span class="mono">${r.data_start || start}</span> ~ <span class="mono">${r.data_end || end}</span>，
    前瞻期: ${r.forward_period || fwd} 天，
    有效行: ${r.valid_rows} / ${r.total_rows}
  </div>`;
  html += '<div class="bt-grid" style="margin-bottom:8px">';
  html += mCard('Sharpe', (r.sharpe || 0).toFixed(4), r.sharpe >= 0 ? 'positive' : 'negative');
  html += mCard('总收益', ((r.total_return || 0) * 100).toFixed(2) + '%', r.total_return >= 0 ? 'positive' : 'negative');
  html += mCard('年化', ((r.annualized_return || 0) * 100).toFixed(2) + '%', r.annualized_return >= 0 ? 'positive' : 'negative');
  html += mCard('IC', (r.ic || 0).toFixed(4), '');
  html += mCard('胜率', ((r.win_rate || 0) * 100).toFixed(1) + '%', r.win_rate >= 0.5 ? 'positive' : '');
  html += mCard('最大回撤', ((r.max_drawdown || 0) * 100).toFixed(2) + '%', 'negative');
  html += mCard('盈亏比', r.profit_factor === 'inf' ? '∞' : (r.profit_factor || 0).toFixed(2), '');
  html += mCard('盈/亏', `${r.wins || 0}/${r.losses || 0}`, '');
  html += '</div>';
  if (r.avg_win || r.avg_loss) {
    html += `<div style="font-size:.72rem;color:var(--t3)">平均盈利: <span style="color:var(--r)">${((r.avg_win||0)*100).toFixed(3)}%</span>，平均亏损: <span style="color:var(--g)">${((r.avg_loss||0)*100).toFixed(3)}%</span></div>`;
  }
  return html;
}

/* ===== Model List ===== */
async function mlLoadModels() {
  const list = document.getElementById('mlModelList');
  const empty = document.getElementById('mlModelEmpty');
  try {
    const r = await api('/api/v1/ml/models');
    App.trainedModels = r.models || [];
    if (!App.trainedModels.length) { list.innerHTML = ''; empty.style.display = 'block'; return; }
    empty.style.display = 'none';
    list.innerHTML = App.trainedModels.map((m, i) => {
      const tm = m.test_metrics || {};
      const typeCls = m.model_type === 'lightgbm' ? 'lgb' : 'lasso';
      return `<div class="model-item" onclick="mlSelectModel(${i})" id="ml-model-${i}">
        <div class="mi-head">
          <span class="mi-id">${m.model_id}</span>
          <span class="mi-type ${typeCls}">${m.model_type}</span>
          <button class="btn btn-ghost btn-sm" style="font-size:.58rem;color:var(--t3);margin-left:auto;padding:2px 6px" onclick="event.stopPropagation();mlDeleteModel('${m.model_id}')" title="删除">🗑</button>
        </div>
        <div class="mi-metrics">
          <div class="mi-m"><span class="mm-l">Accuracy</span><span class="mm-v">${(tm.accuracy||0).toFixed(3)}</span></div>
          <div class="mi-m"><span class="mm-l">F1</span><span class="mm-v">${(tm.f1||0).toFixed(3)}</span></div>
          <div class="mi-m"><span class="mm-l">AUC</span><span class="mm-v">${(tm.auc||0).toFixed(3)}</span></div>
          <div class="mi-m"><span class="mm-l">Features</span><span class="mm-v">${m.n_features||'--'}</span></div>
          <div class="mi-m"><span class="mm-l">Symbol</span><span class="mm-v">${m.symbol||'--'}</span></div>
        </div>
      </div>`;
    }).join('');
  } catch (e) { list.innerHTML = ''; empty.style.display = 'block'; }
}

async function mlDeleteModel(modelId) {
  if (!confirm(`确认删除模型 ${modelId}？`)) return;
  try {
    await api(`/api/v1/ml/models/${modelId}`, { method: 'DELETE' });
    toast('已删除 ' + modelId);
    mlLoadModels();
  } catch (e) { toast('删除失败: ' + e.message, 'error'); }
}

function mlSelectModel(idx) {
  const m = App.trainedModels[idx];
  if (!m) return;
  document.querySelectorAll('.model-item').forEach(el => el.classList.remove('active'));
  const el = document.getElementById('ml-model-' + idx);
  if (el) el.classList.add('active');

  _mlShowPredictCard(m.model_id, m.symbol || 'sh000300', 'ml');
}

function mlSelectGp(gpId, symbol) {
  document.querySelectorAll('.model-item').forEach(el => el.classList.remove('active'));
  _mlShowPredictCard(gpId, symbol, 'gp');
}

function _mlShowPredictCard(id, symbol, type) {
  const card = document.getElementById('mlPredictCard');
  card.style.display = 'block';
  document.getElementById('mlPredModelId').value = id;
  document.getElementById('mlPredSym').value = symbol;
  document.getElementById('mlPredType').value = type;
  document.getElementById('mlPredResult').style.display = 'none';
  document.getElementById('mlBtResult').style.display = 'none';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ===== Predict ===== */
async function mlPredict() {
  const btn = document.getElementById('mlPredBtn');
  const result = document.getElementById('mlPredResult');
  const modelId = document.getElementById('mlPredModelId').value;
  const sym = document.getElementById('mlPredSym').value.trim();
  const type = document.getElementById('mlPredType').value;
  if (!modelId || !sym) { toast('请选择模型和标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  result.style.display = 'block';

  try {
    const endpoint = type === 'gp' ? '/api/v1/ml/gp-predict' : '/api/v1/ml/predict';
    const bodyKey = type === 'gp' ? 'gp_id' : 'model_id';
    const r = await api(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [bodyKey]: modelId, symbol: sym, start: '2026-03-01' }),
    });
    const preds = r.predictions || [];
    const recent = preds.slice(-10);
    let html = `<div style="font-size:.72rem;color:var(--t3);margin-bottom:4px">${sym} 最近 ${recent.length} 日信号 (${type.toUpperCase()})</div>`;
    recent.forEach(p => {
      if (type === 'gp') {
        const dir = p.direction;
        const isLong = dir > 0;
        html += `<div class="signal-row">
          <span class="signal-date">${p.date}</span>
          <span class="signal-badge ${isLong ? 'long' : 'short'}">${isLong ? '看多' : '看空'}</span>
          <span class="signal-prob">sig: ${p.signal?.toFixed(4) || '--'}</span>
        </div>`;
      } else {
        const isLong = p.prediction === 1;
        html += `<div class="signal-row">
          <span class="signal-date">${p.date}</span>
          <span class="signal-badge ${isLong ? 'long' : 'short'}">${isLong ? '看多' : '看空'}</span>
          <span class="signal-prob">${p.probability != null ? (p.probability * 100).toFixed(1) + '%' : '--'}</span>
        </div>`;
      }
    });
    result.innerHTML = html;
    toast('预测完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '预测';
}

/* ===== Backtest (GP / ML) ===== */
async function mlBacktest() {
  const btn = document.getElementById('mlBtBtn');
  const result = document.getElementById('mlBtResult');
  const modelId = document.getElementById('mlPredModelId').value;
  const sym = document.getElementById('mlPredSym').value.trim();
  const type = document.getElementById('mlPredType').value;
  if (!modelId || !sym) { toast('请选择模型/表达式和标的', 'error'); return; }

  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>回测中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>回测中…</div>';

  try {
    const endpoint = type === 'gp' ? '/api/v1/backtest/gp' : '/api/v1/backtest/ml';
    const bodyKey = type === 'gp' ? 'gp_id' : 'model_id';
    const body = { [bodyKey]: modelId, symbol: sym, start: '2025-01-01', initial_capital: 1000000, commission: 0.001 };
    if (type === 'ml') body.threshold = 0.5;

    const r = await api(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px">${type.toUpperCase()} 回测: ${modelId} @ ${sym}</div>`;
    html += '<div class="bt-grid" style="margin-bottom:8px">';
    html += mCard('总收益', (r.total_return * 100).toFixed(2) + '%', r.total_return >= 0 ? 'positive' : 'negative');
    html += mCard('年化', (r.annual_return * 100).toFixed(2) + '%', r.annual_return >= 0 ? 'positive' : 'negative');
    html += mCard('Sharpe', r.sharpe_ratio?.toFixed(4) || '0', r.sharpe_ratio >= 0 ? 'positive' : 'negative');
    html += mCard('最大回撤', (r.max_drawdown * 100).toFixed(2) + '%', 'negative');
    html += mCard('胜率', (r.win_rate * 100).toFixed(1) + '%', r.win_rate >= 0.5 ? 'positive' : '');
    html += mCard('交易次数', r.trade_count, '');
    html += '</div>';

    if (r.trades?.length) {
      html += renderMlTradeTable(r.trades);
    }

    result.innerHTML = html;
    toast('回测完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">回测失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '回测';
}

function renderMlTradeTable(trades) {
  let html = `<div style="margin-top:10px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--t3)">交易明细 (${trades.length} 笔)</div>`;
  html += '<div style="overflow-x:auto;margin-top:6px"><table class="eval-table"><thead><tr>';
  html += '<th>#</th><th>方向</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>盈亏</th><th>持仓天</th>';
  html += '</tr></thead><tbody>';

  trades.forEach((t, i) => {
    const isUp = t.pnl_pct >= 0;
    const pnlColor = isUp ? 'var(--r)' : 'var(--g)';
    const sg = t.pnl_pct > 0 ? '+' : '';
    const sideLabel = t.side === 'sell' ? '卖空' : '买入';
    const sideBg = t.side === 'sell' ? 'var(--gb)' : 'var(--rb)';
    const sideColor = t.side === 'sell' ? 'var(--g)' : 'var(--r)';

    html += `<tr>
      <td style="color:var(--t3)">${i + 1}</td>
      <td><span style="padding:1px 5px;border-radius:3px;font-size:.62rem;font-weight:700;background:${sideBg};color:${sideColor}">${sideLabel}</span></td>
      <td>${t.entry_date}</td>
      <td>${t.entry_price}</td>
      <td>${t.exit_date}</td>
      <td>${t.exit_price}</td>
      <td style="color:${pnlColor};font-weight:600">${sg}${t.pnl_pct}%</td>
      <td>${t.holding_days}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  const winTrades = trades.filter(t => t.pnl_pct > 0);
  const lossTrades = trades.filter(t => t.pnl_pct < 0);
  const avgWin = winTrades.length ? winTrades.reduce((s, t) => s + t.pnl_pct, 0) / winTrades.length : 0;
  const avgLoss = lossTrades.length ? lossTrades.reduce((s, t) => s + t.pnl_pct, 0) / lossTrades.length : 0;
  const avgHold = trades.length ? trades.reduce((s, t) => s + t.holding_days, 0) / trades.length : 0;

  html += `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:8px;font-size:.74rem;color:var(--t2)">
    <span>盈利 <b style="color:var(--r)">${winTrades.length}</b> / 亏损 <b style="color:var(--g)">${lossTrades.length}</b></span>
    <span>平均盈利 <b style="color:var(--r)">${avgWin.toFixed(2)}%</b></span>
    <span>平均亏损 <b style="color:var(--g)">${avgLoss.toFixed(2)}%</b></span>
    <span>平均持仓 <b>${avgHold.toFixed(1)}</b> 天</span>
  </div>`;

  return html;
}

/* ===== Custom Expression ===== */
let _ceFeatureCols = [];

function _ceReadInputs() {
  return {
    expression: document.getElementById('ceExpr').value.trim(),
    symbol: document.getElementById('ceSym').value.trim(),
    start: document.getElementById('ceStart').value || '2024-01-01',
    end: document.getElementById('ceEnd').value || today(),
    forward_period: parseInt(document.getElementById('ceFwd').value) || 5,
  };
}

async function ceEvaluate() {
  const inp = _ceReadInputs();
  if (!inp.expression || !inp.symbol) { toast('请输入表达式和标的', 'error'); return; }
  const btn = document.getElementById('ceEvalBtn');
  const result = document.getElementById('ceResult');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>评估中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>评估中…</div>';

  try {
    const r = await api('/api/v1/ml/custom-expression/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression: inp.expression, symbol: inp.symbol, start: inp.start, end: inp.end, forward_period: inp.forward_period }),
    });
    if (r.feature_cols) _ceFeatureCols = r.feature_cols;
    if (r.error) { result.innerHTML = `<div style="color:var(--r);font-size:.78rem">${r.error}</div>`; }
    else { result.innerHTML = _renderGpEvalResult(r); }
    toast('评估完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">评估失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '评估';
}

async function cePredict() {
  const inp = _ceReadInputs();
  if (!inp.expression || !inp.symbol) { toast('请输入表达式和标的', 'error'); return; }
  const btn = document.getElementById('cePredBtn');
  const result = document.getElementById('ceResult');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>预测中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>预测中…</div>';

  try {
    const r = await api('/api/v1/ml/custom-expression/predict', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression: inp.expression, symbol: inp.symbol, start: inp.start, end: inp.end }),
    });
    if (r.feature_cols) _ceFeatureCols = r.feature_cols;
    const preds = r.predictions || [];
    const last10 = preds.slice(-10);
    let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px">自定义表达式预测 @ ${inp.symbol} — ${preds.length} 条信号 (显示最近10条)</div>`;
    html += '<table class="eval-table" style="font-size:.7rem"><thead><tr><th>日期</th><th>信号值</th><th>方向</th></tr></thead><tbody>';
    last10.forEach(p => {
      const dirTxt = p.direction > 0 ? '看多' : (p.direction < 0 ? '看空' : '中性');
      const dirColor = p.direction > 0 ? 'var(--r)' : (p.direction < 0 ? 'var(--g)' : 'var(--t3)');
      html += `<tr><td>${p.date}</td><td class="mono">${p.signal}</td><td style="color:${dirColor};font-weight:600">${dirTxt}</td></tr>`;
    });
    html += '</tbody></table>';
    result.innerHTML = html;
    toast('预测完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">预测失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '预测';
}

async function ceBacktest() {
  const inp = _ceReadInputs();
  if (!inp.expression || !inp.symbol) { toast('请输入表达式和标的', 'error'); return; }
  const btn = document.getElementById('ceBtBtn');
  const result = document.getElementById('ceResult');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>回测中…';
  result.style.display = 'block';
  result.innerHTML = '<div class="empty-state" style="padding:12px"><span class="spinner"></span>回测中…</div>';

  try {
    const r = await api('/api/v1/ml/custom-expression/backtest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expression: inp.expression, symbol: inp.symbol, start: inp.start, end: inp.end, initial_capital: 1000000, commission: 0.001 }),
    });

    let html = `<div style="font-size:.78rem;color:var(--t2);margin-bottom:6px">自定义表达式回测 @ ${inp.symbol}</div>`;
    html += '<div class="bt-grid" style="margin-bottom:8px">';
    html += mCard('总收益', (r.total_return * 100).toFixed(2) + '%', r.total_return >= 0 ? 'positive' : 'negative');
    html += mCard('年化', (r.annual_return * 100).toFixed(2) + '%', r.annual_return >= 0 ? 'positive' : 'negative');
    html += mCard('Sharpe', r.sharpe_ratio?.toFixed(4) || '0', r.sharpe_ratio >= 0 ? 'positive' : 'negative');
    html += mCard('最大回撤', (r.max_drawdown * 100).toFixed(2) + '%', 'negative');
    html += mCard('胜率', (r.win_rate * 100).toFixed(1) + '%', r.win_rate >= 0.5 ? 'positive' : '');
    html += mCard('交易次数', r.trade_count, '');
    html += '</div>';
    if (r.trades?.length) html += renderMlTradeTable(r.trades);
    result.innerHTML = html;
    toast('回测完成');
  } catch (e) {
    result.innerHTML = `<div style="color:var(--r);font-size:.78rem">回测失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '回测';
}

async function ceSave() {
  const inp = _ceReadInputs();
  if (!inp.expression || !inp.symbol) { toast('请输入表达式和标的', 'error'); return; }
  const btn = document.getElementById('ceSaveBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';

  try {
    const r = await api('/api/v1/ml/gp-save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expression: inp.expression, symbol: inp.symbol,
        metric: 'custom', sharpe: 0, total_ret: 0, ic: 0, depth: 0, tree_size: 0,
        data_start: inp.start, data_end: inp.end, forward_period: inp.forward_period,
      }),
    });
    toast(`已保存: ${r.gp_id}`);
    mlLoadGpList();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  }
  btn.disabled = false; btn.textContent = '保存为 GP 表达式';
}
