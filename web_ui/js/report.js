/**
 * Report page.
 */
async function generateReport() {
  const container = document.getElementById('reportContent');
  container.innerHTML = '<div class="empty-state" style="padding:24px"><span class="spinner"></span>正在生成中文日报…</div>';
  toast('生成中…');
  try {
    await api('/api/v1/reports/daily', { method: 'POST' });
    const payload = await api('/api/v1/reports/daily-view?refresh_data=false');
    container.innerHTML = renderDailyReport(payload || {});
    switchTab('report', true);
    toast('日报已生成');
  } catch (e) {
    container.innerHTML = `<div class="empty-state" style="padding:24px;color:var(--r)">生成失败：${e.message}</div>`;
    toast('生成失败', 'error');
  }
}

function reportFmtNum(v, digits = 2) {
  if (v == null || v === '') return '--';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : '--';
}

function reportFmtPct(v) {
  if (v == null || v === '') return '--';
  const n = Number(v);
  return Number.isFinite(n) ? (n * 100).toFixed(1) + '%' : '--';
}

function reportTypeLabel(type) {
  if (type === 'gp') return 'GP';
  if (type === 'lasso') return 'LASSO';
  if (type === 'lightgbm') return 'LIGHTGBM';
  return String(type || '--').toUpperCase();
}

function reportActionBadge(action) {
  const cls = actionBadgeClass(action);
  return `<span class="signal-badge ${cls}">${action || '无数据'}</span>`;
}

function renderReportSummaryCards(cards) {
  if (!cards || !cards.length) return '';
  return `<section class="report-section">
    <div class="report-section-head">
      <div>
        <div class="report-section-title">摘要卡片</div>
        <div class="report-section-sub">用最少的信息先把今天的关键状态扫一遍</div>
      </div>
    </div>
    <div class="report-summary-grid">
      ${cards.map(card => `<div class="report-summary-card">
        <div class="rsc-label">${card.label || '--'}</div>
        <div class="rsc-value">${card.value || '--'}</div>
        <div class="rsc-sub">${card.subtext || ''}</div>
      </div>`).join('')}
    </div>
  </section>`;
}

function renderReportStrategyGroups(groups) {
  if (!groups || !groups.length) {
    return `<section class="report-section">
      <div class="report-section-head">
        <div>
          <div class="report-section-title">策略分组表格</div>
          <div class="report-section-sub">当前还没有已保存模型或 GP 表达式</div>
        </div>
      </div>
    </section>`;
  }
  return `<section class="report-section">
    <div class="report-section-head">
      <div>
        <div class="report-section-title">策略分组表格</div>
        <div class="report-section-sub">按标的归类查看同一实体下各模型的下一交易日操作建议</div>
      </div>
    </div>
    <div class="report-groups">
      ${groups.map(group => `
        <div class="report-group-card">
          <div class="report-group-head">
            <div>
              <div class="report-group-title">${group.symbol}</div>
              <div class="report-group-sub">${group.symbol_name && group.symbol_name !== group.symbol ? `${group.symbol_name} · ` : ''}共 ${group.strategy_count} 个策略，最新信号日期 ${group.latest_signal_date || '--'}</div>
            </div>
          </div>
          <div class="report-table-wrap">
            <table class="report-table">
              <thead>
                <tr>
                  <th>策略</th>
                  <th>类型</th>
                  <th>信号日期</th>
                  <th>下一交易日</th>
                  <th>动作原因</th>
                  <th>信号值</th>
                  <th>概率</th>
                  <th>最新价格</th>
                  <th>行情日期</th>
                </tr>
              </thead>
              <tbody>
                ${group.rows.map(row => `<tr>
                  <td>${row.strategy_name || '--'}</td>
                  <td><span class="report-type-chip">${reportTypeLabel(row.strategy_type)}</span></td>
                  <td>${row.signal_date || '--'}</td>
                  <td>${reportActionBadge(row.action)}</td>
                  <td>${row.action_reason || '--'}</td>
                  <td>${reportFmtNum(row.signal_value, 4)}</td>
                  <td>${reportFmtPct(row.probability)}</td>
                  <td>${reportFmtNum(row.latest_price, 3)}</td>
                  <td>${row.latest_trade_date || '--'}</td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </div>`).join('')}
    </div>
  </section>`;
}

function renderReportRisk(risk) {
  const items = risk?.items || [];
  const unresolved = risk?.unresolved_count ?? 0;
  const total = risk?.total_count ?? 0;
  return `<section class="report-section">
    <div class="report-section-head">
      <div>
        <div class="report-section-title">风险区块</div>
        <div class="report-section-sub">最近告警 ${total} 条，其中未解决 ${unresolved} 条</div>
      </div>
    </div>
    ${!items.length ? `
      <div class="report-risk-empty">当前没有最近风险告警，可以继续按计划跟踪模型信号。</div>
    ` : `
      <div class="report-risk-list">
        ${items.map(item => `<div class="report-risk-item">
          <div class="report-risk-top">
            <span class="report-risk-level level-${String(item.level || '').toLowerCase()}">${item.level || 'INFO'}</span>
            <span class="report-risk-source">${item.source || '--'}</span>
            <span class="report-risk-time">${item.created_at || '--'}</span>
          </div>
          <div class="report-risk-message">${item.message || '--'}</div>
        </div>`).join('')}
      </div>
    `}
  </section>`;
}

function renderDailyReport(payload) {
  return `<div class="report-shell">
    <header class="report-hero">
      <div>
        <div class="report-eyebrow">中文固定版式日报</div>
        <h1>${payload.headline || '每日报告'}</h1>
        <p>${payload.subheadline || '聚合今天最值得读的摘要、策略建议和风险提示'}</p>
      </div>
      <div class="report-generated-at">生成时间：${payload.generated_at || '--'}</div>
    </header>
    ${renderReportSummaryCards(payload.summary_cards || [])}
    ${renderReportStrategyGroups(payload.strategy_groups || [])}
    ${renderReportRisk(payload.risk || {})}
  </div>`;
}
