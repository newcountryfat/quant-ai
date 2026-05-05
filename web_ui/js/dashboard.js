/**
 * Dashboard page: system overview, quick actions, saved strategy signals.
 */
let _dashLoaded = false;

function groupBySymbol(items) {
  const groups = new Map();
  (items || []).forEach(item => {
    const key = item.symbol || '未指定标的';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return Array.from(groups.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([symbol, rows]) => ({
      symbol,
      symbol_name: rows[0]?.symbol_name || App.watchlistNameMap?.[symbol] || symbol,
      rows,
    }));
}

async function loadDashboard(force = false) {
  if (_dashLoaded && !force) return;
  const grid = document.getElementById('dashGrid');
  const health = document.getElementById('dashHealth');
  const list = document.getElementById('dashStrategyList');
  const empty = document.getElementById('dashStrategyEmpty');

  grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;padding:16px"><span class="spinner"></span>加载中…</div>';
  list.innerHTML = '<div class="empty-state" style="padding:16px"><span class="spinner"></span>刷新模型信号…</div>';
  empty.style.display = 'none';

  try {
    await ensureWatchlistNameMap();
    const payload = await api('/api/v1/dashboard/overview?refresh_data=true');
    const h = payload.health || {};
    const svc = payload.services || {};
    const s = payload.summary || {};
    const strategies = payload.saved_strategies || [];

    const healthy = Object.values(svc).every(Boolean);
    health.innerHTML = `<span class="dh-dot" style="background:${healthy ? 'var(--g)' : 'var(--y)'}"></span>
      <span style="font-weight:600">${healthy ? '系统运行正常' : '部分服务待检查'}</span>
      <span style="color:var(--t3);font-size:.72rem;margin-left:auto">
        CPU ${fmtPct(h.cpu_percent)} · 内存 ${fmtPct(h.memory_percent)} · 磁盘 ${fmtPct(h.disk_percent)}
      </span>`;

    const au = s.asset_universe || {};
    grid.innerHTML = [
      dCard('股票总数', s.stocks_total ?? '--', ''),
      dCard('日线标的', s.daily_quote_symbols ?? '--', s.daily_quote_min_date && s.daily_quote_max_date ? `${s.daily_quote_min_date} ~ ${s.daily_quote_max_date}` : ''),
      dCard('日线行数', fmtNum(s.daily_quote_rows), ''),
      dCard('资产池', Object.values(au).reduce((a, b) => a + b, 0), Object.entries(au).map(([k, v]) => `${k}:${v}`).join(' ')),
      dCard('因子值', fmtNum(s.factor_value_rows), `${s.factor_value_symbols ?? 0} 标的`),
      dCard('因子评估', s.factor_eval_total ?? '--', ''),
      dCard('策略', s.strategies_total ?? '--', `活跃 ${s.strategies_active ?? 0}`),
      dCard('回测', s.backtests_total ?? '--', ''),
      dCard('自选', s.watchlist_total ?? '--', ''),
      dCard('任务日志', s.job_logs_total ?? '--', ''),
      dCard('市场宽度', fmtNum(s.breadth_rows), s.breadth_min_date && s.breadth_max_date ? `${s.breadth_min_date} ~ ${s.breadth_max_date}` : ''),
      dCard('告警', s.alerts_total ?? '--', `未解决 ${s.alerts_unresolved ?? 0}`),
    ].join('');

    if (!strategies.length) {
      list.innerHTML = '';
      empty.style.display = 'block';
    } else {
      list.innerHTML = groupBySymbol(strategies).map(renderDashboardStrategyGroup).join('');
      empty.style.display = 'none';
    }

    _dashLoaded = true;
  } catch (e) {
    health.innerHTML = '<span class="dh-dot" style="background:var(--r)"></span><span style="font-weight:600">总览加载失败</span>';
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1">加载失败</div>';
    list.innerHTML = '<div class="empty-state" style="padding:16px">模型信号加载失败</div>';
    empty.style.display = 'none';
  }
}

function renderDashboardStrategyGroup(group) {
  const latestDate = group.rows
    .map(item => item.snapshot_date || item.latest_trade_date || '')
    .filter(Boolean)
    .sort()
    .pop() || '--';
  const symbolName = group.symbol_name && group.symbol_name !== group.symbol ? group.symbol_name : '';
  return `<section class="symbol-group">
    <div class="symbol-group-head">
      <div>
        <div class="symbol-group-title">${group.symbol}</div>
        <div class="symbol-group-sub">${symbolName ? `${symbolName} · ` : ''}共 ${group.rows.length} 个已收藏模型，最新信号日期 ${latestDate}</div>
      </div>
    </div>
    <div class="symbol-group-body">
      ${group.rows.map(renderDashboardStrategy).join('')}
    </div>
  </section>`;
}

function renderDashboardStrategy(item) {
  const actionCls = actionBadgeClass(item.action);
  const valueText = item.signal_value == null ? '--' : Number(item.signal_value).toFixed(4);
  const probText = item.probability == null ? '--' : (Number(item.probability) * 100).toFixed(1) + '%';
  const priceText = item.latest_price == null ? '--' : Number(item.latest_price).toFixed(3);
  const typeText = item.strategy_type === 'gp' ? 'GP' : String(item.strategy_type || 'ML').toUpperCase();
  const dateText = item.snapshot_date || item.latest_trade_date || '--';
  return `<div class="model-item">
    <div class="mi-head">
      <div class="mi-id">${item.strategy_name}</div>
      <span class="mi-type ${item.strategy_type === 'gp' ? 'gp' : (item.strategy_type === 'lasso' ? 'lasso' : 'lgb')}">${typeText}</span>
    </div>
    <div class="mi-metrics">
      <div class="mi-m"><span class="mm-l">信号日期</span><span class="mm-v">${dateText}</span></div>
      <div class="mi-m"><span class="mm-l">最新价格</span><span class="mm-v">${priceText}</span></div>
      <div class="mi-m"><span class="mm-l">信号值</span><span class="mm-v">${valueText}</span></div>
      <div class="mi-m"><span class="mm-l">概率</span><span class="mm-v">${probText}</span></div>
      <div class="mi-m"><span class="mm-l">下一交易日</span><span class="signal-badge ${actionCls}">${item.action}</span></div>
    </div>
    <div class="mi-reason">${item.action_reason || '动作原因暂不可用'}</div>
  </div>`;
}

function dCard(label, value, sub) {
  return `<div class="dash-card"><div class="dc-label">${label}</div><div class="dc-val">${value}</div>${sub ? `<div class="dc-sub">${sub}</div>` : ''}</div>`;
}

function fmtNum(v) {
  if (v == null) return '--';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return String(v);
}

function fmtPct(v) {
  if (v == null) return '--';
  return Number(v).toFixed(1) + '%';
}

async function dashAction(type) {
  const resultEl = document.getElementById('dashActionResult');
  const pre = document.getElementById('dashActionPre');
  resultEl.style.display = 'block';
  pre.textContent = '执行中…';

  try {
    let r;
    if (type === 'bootstrap') {
      r = await api('/api/v1/universe/bootstrap', { method: 'POST' });
    } else if (type === 'breadth') {
      r = await api('/api/v1/features/breadth/rebuild', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start: '2025-01-01', end: today() }),
      });
    } else if (type === 'compute') {
      r = await api('/api/v1/factors/batch-compute', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: 'sh000300', start: '2025-01-01', persist: true }),
      });
    } else if (type === 'evaluate') {
      r = await api('/api/v1/factors/evaluate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: 'sh000300', forward_period: 5, start: '2025-01-01', persist: true }),
      });
    }
    pre.textContent = JSON.stringify(r, null, 2);
    toast('操作完成');
    _dashLoaded = false;
    loadDashboard(true);
  } catch (e) {
    pre.textContent = '失败: ' + e.message;
    toast('操作失败', 'error');
  }
}
