/**
 * Dashboard page: system overview, data summary, quick actions.
 */
let _dashLoaded = false;

async function loadDashboard() {
  if (_dashLoaded) return;
  const grid = document.getElementById('dashGrid');
  const health = document.getElementById('dashHealth');

  try {
    const [h, s] = await Promise.all([
      api('/health').catch(() => null),
      api('/api/v1/data/summary').catch(() => null),
    ]);

    if (h) {
      const ok = h.status === 'ok';
      health.innerHTML = `<span class="dh-dot" style="background:${ok ? 'var(--g)' : 'var(--r)'}"></span>
        <span style="font-weight:600">${ok ? '系统运行正常' : '系统异常'}</span>
        <span style="color:var(--t3);font-size:.72rem;margin-left:auto">数据: ${h.data_service ? '正常' : '异常'} · 策略: ${h.strategy_service ? '正常' : '异常'} · 调度: ${h.scheduler ? '正常' : '异常'}</span>`;
    }

    if (s) {
      const cards = [];
      cards.push(dCard('股票总数', s.stocks?.count ?? '--', ''));
      const dq = s.daily_quotes || {};
      cards.push(dCard('日线标的', dq.symbols ?? '--', dq.min_date && dq.max_date ? `${dq.min_date} ~ ${dq.max_date}` : ''));
      cards.push(dCard('日线行数', fmtNum(dq.rows), ''));

      const au = s.asset_universe || {};
      const auTotal = Object.values(au).reduce((a, b) => a + b, 0);
      cards.push(dCard('资产池', auTotal, Object.entries(au).map(([k, v]) => `${k}:${v}`).join(' ')));

      cards.push(dCard('因子值', fmtNum(s.factor_values?.rows), `${s.factor_values?.symbols ?? 0} 标的`));
      cards.push(dCard('因子评估', s.factor_eval_results?.rows ?? '--', ''));
      cards.push(dCard('策略', s.strategies?.count ?? '--', ''));
      cards.push(dCard('回测', s.backtest_results?.count ?? '--', ''));
      cards.push(dCard('自选', s.watchlist?.count ?? '--', ''));
      cards.push(dCard('任务日志', s.job_logs?.count ?? '--', ''));
      cards.push(dCard('市场宽度', fmtNum(s.market_breadth?.rows), s.market_breadth?.min_date ? `${s.market_breadth.min_date} ~` : ''));
      cards.push(dCard('告警', s.alerts?.count ?? '--', ''));
      grid.innerHTML = cards.join('');
    }

    _dashLoaded = true;
  } catch (e) {
    grid.innerHTML = '<div class="empty-state">加载失败</div>';
  }
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
    loadDashboard();
  } catch (e) {
    pre.textContent = '失败: ' + e.message;
    toast('操作失败', 'error');
  }
}
