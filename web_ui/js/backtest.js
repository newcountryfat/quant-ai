/**
 * Backtest page: strategy selection, param config, run & show detailed results.
 */
function onStrategyChange() {
  const s = document.getElementById('btStrategy').value;
  document.getElementById('btParamsMaCross').style.display = s === 'ma_cross' ? 'flex' : 'none';
  document.getElementById('btParamsRsi').style.display = s === 'rsi_reversal' ? 'flex' : 'none';
  document.getElementById('btParamsBb').style.display = s === 'bollinger_breakout' ? 'flex' : 'none';
}

function getBtParams() {
  const s = document.getElementById('btStrategy').value;
  const cap = parseFloat(document.getElementById('btCapital').value) * 10000 || 1000000;
  const comm = parseFloat(document.getElementById('btCommission').value) / 1000 || 0.001;
  let p;
  if (s === 'rsi_reversal') p = { period: +document.getElementById('btRsiPeriod').value, oversold: +document.getElementById('btOversold').value, overbought: +document.getElementById('btOverbought').value };
  else if (s === 'bollinger_breakout') p = { period: +document.getElementById('btBbPeriod').value, num_std: +document.getElementById('btBbStd').value };
  else p = { fast: +document.getElementById('btFast').value || 5, slow: +document.getElementById('btSlow').value || 20 };
  return { ...p, initial_capital: cap, commission: comm };
}

async function runBacktest() {
  const sym = document.getElementById('btSymbol').value.trim();
  const start = document.getElementById('btStart').value, end = document.getElementById('btEnd').value;
  const sid = document.getElementById('btStrategy').value;
  if (!sym) { toast('请输入代码', 'error'); return; }
  const btn = document.getElementById('btBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>回测中';
  try {
    await fetchSilent(sym, start, end);
    const params = getBtParams();
    const r = await api('/api/v1/backtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ strategy_id: sid, symbol: sym, start, end, params }) });
    renderBT(r, params, sid, sym, start, end);
  } catch (e) { toast('回测失败', 'error'); }
  btn.disabled = false; btn.textContent = '运行回测';
}

async function runOptimize() {
  const sym = document.getElementById('btSymbol').value.trim();
  const start = document.getElementById('btStart').value, end = document.getElementById('btEnd').value;
  const sid = document.getElementById('btStrategy').value;
  if (!sym) { toast('请输入代码', 'error'); return; }
  const btn = document.getElementById('optBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>优化中…';
  try {
    const r = await api('/api/v1/optimize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ strategy_id: sid, symbol: sym, start, end, n_trials: 20, metric: 'sharpe_ratio' }) });
    toast(`最优: ${JSON.stringify(r.best_params)} Sharpe=${r.result.sharpe_ratio}`);
    renderBT(r.result, r.best_params, sid, sym, start, end);
  } catch (e) { toast('优化失败', 'error'); }
  btn.disabled = false; btn.textContent = '参数优化';
}

function renderBT(r, params, sid, sym, start, end) {
  document.getElementById('btResult').style.display = 'block';
  const pct = v => (v * 100).toFixed(2) + '%';
  const cls = v => v >= 0 ? 'positive' : 'negative';
  const cap = params.initial_capital || 1000000;
  const comm = params.commission || 0.001;
  const finalCap = cap * (1 + r.total_return);

  document.getElementById('btGrid').innerHTML = [
    bCard('总收益', pct(r.total_return), cls(r.total_return)),
    bCard('年化收益', pct(r.annual_return), cls(r.annual_return)),
    bCard('夏普比率', r.sharpe_ratio.toFixed(4), r.sharpe_ratio >= 1 ? 'positive' : ''),
    bCard('最大回撤', pct(r.max_drawdown), 'negative'),
    bCard('胜率', pct(r.win_rate), r.win_rate >= 0.5 ? 'positive' : 'negative'),
    bCard('交易次数', r.trade_count, ''),
  ].join('');

  const pj = typeof params === 'object'
    ? Object.entries(params).filter(([k]) => !['initial_capital', 'commission'].includes(k)).map(([k, v]) => `${k}=${v}`).join(', ') : '';

  let html = `
<b>策略:</b> ${STRAT_NAMES[sid] || sid}<br>
<b>股票:</b> ${sym} | <b>区间:</b> ${start} ~ ${end}<br>
<b>初始资金:</b> <span class="mono">${(cap / 10000).toFixed(0)}万</span> → <b>最终权益:</b> <span class="mono" style="color:${r.total_return >= 0 ? 'var(--g)' : 'var(--r)'}">${(finalCap / 10000).toFixed(2)}万</span><br>
<b>交易成本:</b> ${(comm * 1000).toFixed(1)}‰ | <b>策略参数:</b> ${pj}<br>
<b>年化波动:</b> ${r.sharpe_ratio !== 0 ? ((r.annual_return / r.sharpe_ratio) * 100).toFixed(1) + '%' : '--'} | <b>盈亏比:</b> ${r.win_rate > 0 ? (r.total_return / (r.max_drawdown || 1)).toFixed(2) : '--'}`;

  if (r.trades && r.trades.length) {
    html += renderTradeTable(r.trades, cap, comm);
  }

  document.getElementById('btDetailContent').innerHTML = html;
  document.getElementById('btDetailCard').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderTradeTable(trades, initialCapital, commRate) {
  let equity = initialCapital;
  let html = `<div style="margin-top:14px;font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--t3)">交易明细 (${trades.length} 笔)</div>`;
  html += '<div style="overflow-x:auto;margin-top:6px"><table class="eval-table"><thead><tr>';
  html += '<th>#</th><th>方向</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th><th>盈亏</th><th>持仓天</th><th>交易后资产</th><th>累计收益</th>';
  html += '</tr></thead><tbody>';

  let cumPnl = 0;
  trades.forEach((t, i) => {
    const tradePnl = equity * (t.pnl_pct / 100);
    const cost = equity * commRate * 2;
    equity = equity + tradePnl - cost;
    if (equity < 0) equity = 0;
    cumPnl = (equity / initialCapital - 1) * 100;
    const isUp = t.pnl_pct >= 0;
    const pnlColor = isUp ? 'var(--r)' : 'var(--g)';
    const cumColor = cumPnl >= 0 ? 'var(--r)' : 'var(--g)';
    const sg = t.pnl_pct > 0 ? '+' : '';
    const csg = cumPnl > 0 ? '+' : '';
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
      <td style="font-weight:600">${(equity / 10000).toFixed(2)}万</td>
      <td style="color:${cumColor};font-weight:600">${csg}${cumPnl.toFixed(2)}%</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  const winTrades = trades.filter(t => t.pnl_pct > 0);
  const lossTrades = trades.filter(t => t.pnl_pct < 0);
  const avgWin = winTrades.length ? winTrades.reduce((s, t) => s + t.pnl_pct, 0) / winTrades.length : 0;
  const avgLoss = lossTrades.length ? lossTrades.reduce((s, t) => s + t.pnl_pct, 0) / lossTrades.length : 0;
  const avgHold = trades.reduce((s, t) => s + t.holding_days, 0) / trades.length;
  const maxWin = trades.length ? Math.max(...trades.map(t => t.pnl_pct)) : 0;
  const maxLoss = trades.length ? Math.min(...trades.map(t => t.pnl_pct)) : 0;

  html += `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:10px;font-size:.74rem;color:var(--t2)">
    <span>盈利 <b style="color:var(--r)">${winTrades.length}</b> 笔 / 亏损 <b style="color:var(--g)">${lossTrades.length}</b> 笔</span>
    <span>平均盈利 <b style="color:var(--r)">${avgWin.toFixed(2)}%</b></span>
    <span>平均亏损 <b style="color:var(--g)">${avgLoss.toFixed(2)}%</b></span>
    <span>最大盈利 <b style="color:var(--r)">+${maxWin.toFixed(2)}%</b></span>
    <span>最大亏损 <b style="color:var(--g)">${maxLoss.toFixed(2)}%</b></span>
    <span>平均持仓 <b>${avgHold.toFixed(1)}</b> 天</span>
  </div>`;

  return html;
}

function bCard(l, v, c) {
  return `<div class="bt-card"><div class="label">${l}</div><div class="val ${c}">${v}</div></div>`;
}
