/**
 * Paper trading page.
 */
async function loadPaperAccount() {
  try {
    const r = await api('/api/v1/paper/accounts/default');
    const pctVal = (r.total_return * 100).toFixed(2) + '%';
    const cl = r.total_return >= 0 ? 'var(--g)' : 'var(--r)';
    document.getElementById('ptAccount').innerHTML = [
      xqMetaCell('初始资金', (r.initial_capital / 10000).toFixed(0) + '万'),
      xqMetaCell('现金', r.cash.toFixed(2)),
      xqMetaCell('总权益', r.equity.toFixed(2)),
      xqMetaCell('总收益', '<span style="color:' + cl + '">' + pctVal + '</span>'),
    ].join('');

    const pos = r.positions || {}, syms = Object.keys(pos);
    if (syms.length) {
      let h = '<thead><tr><th>代码</th><th>数量</th><th>成本</th><th>现价</th><th>盈亏</th></tr></thead><tbody>';
      syms.forEach(s => {
        const p = pos[s];
        const pnl = p.shares * (p.current_price - p.avg_cost);
        const c = pnl >= 0 ? 'var(--g)' : 'var(--r)';
        h += `<tr><td class="mono">${s}</td><td>${p.shares}</td><td class="mono">${p.avg_cost.toFixed(2)}</td><td class="mono">${p.current_price.toFixed(2)}</td><td class="mono" style="color:${c}">${pnl.toFixed(2)}</td></tr>`;
      });
      h += '</tbody>';
      document.getElementById('ptPositions').innerHTML = h;
    } else {
      document.getElementById('ptPositions').innerHTML = '<tbody><tr><td style="color:var(--t3);padding:12px">暂无持仓</td></tr></tbody>';
    }

    const orders = await api('/api/v1/paper/orders?account_id=default&limit=10');
    if (orders.orders?.length) {
      let h = '<thead><tr><th>订单号</th><th>代码</th><th>方向</th><th>数量</th><th>价格</th><th>状态</th></tr></thead><tbody>';
      orders.orders.forEach(o => {
        const sc = o.status === 'filled' ? 'var(--g)' : o.status === 'rejected' ? 'var(--r)' : 'var(--t3)';
        const dc = o.side === 'buy' ? 'var(--r)' : 'var(--g)';
        h += `<tr><td class="mono" style="font-size:.7rem">${o.order_id}</td><td class="mono">${o.symbol}</td><td style="color:${dc}">${o.side === 'buy' ? '买入' : '卖出'}</td><td>${o.quantity}</td><td class="mono">${o.price?.toFixed(2) ?? '--'}</td><td style="color:${sc}">${o.status}</td></tr>`;
      });
      h += '</tbody>';
      document.getElementById('ptOrders').innerHTML = h;
    } else {
      document.getElementById('ptOrders').innerHTML = '<tbody><tr><td style="color:var(--t3);padding:12px">暂无订单</td></tr></tbody>';
    }
  } catch (e) { toast('加载失败', 'error'); }
}

async function placeOrder() {
  const sym = document.getElementById('ptSymbol').value.trim();
  const side = document.getElementById('ptSide').value;
  const qty = parseFloat(document.getElementById('ptQty').value) || 100;
  if (!sym) { toast('请输入代码', 'error'); return; }
  const btn = document.getElementById('ptBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>下单中';
  try {
    const r = await api('/api/v1/paper/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, side, quantity: qty }),
    });
    if (r.status === 'filled') toast(`${side === 'buy' ? '买入' : '卖出'} ${sym} x${qty} @ ${r.price} 成交`);
    else toast(`被拒绝: ${r.reason}`, 'error');
    loadPaperAccount();
  } catch (e) { toast('失败', 'error'); }
  btn.disabled = false; btn.textContent = '下单';
}
