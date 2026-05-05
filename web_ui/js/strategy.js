/**
 * Backtest Records page: history list + folders + comments.
 */
let _btRecLoaded = false;
let _btRecExpandedIdx = -1;
let _btRecSelected = new Set();
let _btCommentsCache = {};

function btEscapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function btSelectedIds() {
  return Array.from(_btRecSelected);
}

function btFolderName(folderId) {
  const folder = (App.btFolders || []).find(f => f.id === folderId);
  return folder?.name || '未分类';
}

async function loadBtFolders() {
  const payload = await api('/api/v1/backtest/folders');
  App.btFolders = payload.folders || [];
  renderBtFolderControls();
}

function renderBtFolderControls() {
  const filter = document.getElementById('btFolderFilter');
  const moveTarget = document.getElementById('btFolderMoveTarget');
  const chips = document.getElementById('btFolderChips');
  if (!filter || !moveTarget || !chips) return;

  const current = filter.value || '';
  filter.innerHTML = [
    '<option value="">全部记录</option>',
    '<option value="unassigned">未分类</option>',
    ...App.btFolders.map(f => `<option value="${f.id}">${btEscapeHtml(f.name)} (${f.record_count || 0})</option>`),
  ].join('');
  if ([...filter.options].some(opt => opt.value === current)) filter.value = current;

  moveTarget.innerHTML = [
    '<option value="">移动到未分类</option>',
    ...App.btFolders.map(f => `<option value="${f.id}">${btEscapeHtml(f.name)}</option>`),
  ].join('');

  chips.innerHTML = [
    `<button class="bt-folder-chip ${!filter.value ? 'active' : ''}" onclick="document.getElementById('btFolderFilter').value='';loadBtRecords()">全部</button>`,
    `<button class="bt-folder-chip ${filter.value === 'unassigned' ? 'active' : ''}" onclick="document.getElementById('btFolderFilter').value='unassigned';loadBtRecords()">未分类</button>`,
    ...App.btFolders.map(f => (
      `<div class="bt-folder-chip-row">
        <button class="bt-folder-chip ${String(f.id) === filter.value ? 'active' : ''}" onclick="document.getElementById('btFolderFilter').value='${f.id}';loadBtRecords()">${btEscapeHtml(f.name)}</button>
        <button class="bt-folder-mini" onclick="event.stopPropagation();btRenameFolder(${f.id})">改</button>
        <button class="bt-folder-mini" onclick="event.stopPropagation();btDeleteFolder(${f.id})">删</button>
      </div>`
    )),
  ].join('');

  renderBtBatchBar();
}

function renderBtBatchBar() {
  const bar = document.getElementById('btRecBatchBar');
  if (!bar) return;
  const count = _btRecSelected.size;
  if (!count) {
    bar.style.display = 'none';
    bar.innerHTML = '';
    return;
  }
  bar.style.display = 'flex';
  bar.innerHTML = `
    <span>已选中 <b>${count}</b> 条记录</span>
    <button class="btn btn-ghost btn-sm" onclick="btSelectAllVisible()">全选当前列表</button>
    <button class="btn btn-ghost btn-sm" onclick="btClearSelected()">清空选择</button>
  `;
}

function btToggleSelected(recordId, checked) {
  if (checked) _btRecSelected.add(recordId);
  else _btRecSelected.delete(recordId);
  renderBtBatchBar();
}

function btToggleSelectAll(checked) {
  (App.btHistoryData || []).forEach(item => {
    if (!item?.id) return;
    if (checked) _btRecSelected.add(item.id);
    else _btRecSelected.delete(item.id);
  });
  document.querySelectorAll('.bt-rec-check').forEach(el => { el.checked = checked; });
  renderBtBatchBar();
}

function btSelectAllVisible() {
  btToggleSelectAll(true);
}

function btClearSelected() {
  _btRecSelected.clear();
  document.querySelectorAll('.bt-rec-check, #btRecCheckAll').forEach(el => { el.checked = false; });
  renderBtBatchBar();
}

async function loadBtRecords() {
  const list = document.getElementById('btRecList');
  const loading = document.getElementById('btRecLoading');
  const empty = document.getElementById('btRecEmpty');
  const folderFilter = document.getElementById('btFolderFilter');

  loading.style.display = 'block';
  empty.style.display = 'none';
  list.innerHTML = '';
  _btRecExpandedIdx = -1;

  try {
    if (!App.btFolders.length) await loadBtFolders();
    const selectedFolder = folderFilter?.value || '';
    const r = await api('/api/v1/backtest/history?limit=100');
    let history = r.history || [];
    if (selectedFolder === 'unassigned') history = history.filter(item => !item.folder_id);
    else if (selectedFolder) history = history.filter(item => String(item.folder_id || '') === selectedFolder);
    App.btHistoryData = history;

    if (!history.length) {
      empty.style.display = 'block';
      loading.style.display = 'none';
      _btRecLoaded = true;
      renderBtBatchBar();
      return;
    }

    list.innerHTML = `
      <div class="bt-rec-list-head">
        <label class="bt-rec-check-wrap">
          <input id="btRecCheckAll" type="checkbox" onchange="btToggleSelectAll(this.checked)">
          <span>本页全选</span>
        </label>
        <span>${history.length} 条记录</span>
      </div>
      ${history.map((h, idx) => renderBtRecordCard(h, idx)).join('')}
    `;

    _btRecLoaded = true;
    renderBtBatchBar();
  } catch (e) {
    list.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = '加载失败，请重试';
  }
  loading.style.display = 'none';
}

function renderBtRecordCard(h, idx) {
  const ret = ((h.total_return || 0) * 100).toFixed(2);
  const isWin = (h.total_return || 0) > 0;
  const retColor = isWin ? 'var(--r)' : ((h.total_return || 0) < 0 ? 'var(--g)' : 'var(--t3)');
  const sg = (h.total_return || 0) > 0 ? '+' : '';
  const sharpe = h.sharpe?.toFixed(2) ?? '--';
  const maxdd = h.max_dd != null ? (h.max_dd * 100).toFixed(2) + '%' : '--';
  const winR = h.win_rate != null ? (h.win_rate * 100).toFixed(1) + '%' : '--';
  const trades = h.trade_count ?? '--';
  const cap = h.initial_capital ? (h.initial_capital / 10000).toFixed(0) + '万' : '--';
  const period = (h.start_date || '--') + ' ~ ' + (h.end_date || '--');
  const time = (h.run_at || '').slice(5, 16);
  const recId = h.id || '';
  const commentCount = h.comment_count || 0;
  const checked = _btRecSelected.has(recId) ? 'checked' : '';
  const folderLabel = h.folder_name || '未分类';

  return `<div class="strat-card" onclick="toggleBtRecDetail(${idx})" id="btRec-${idx}">
  <div class="strat-head">
    <div style="display:flex;align-items:center;gap:8px;min-width:0">
      <label class="bt-rec-check-wrap" onclick="event.stopPropagation()">
        <input class="bt-rec-check" type="checkbox" ${checked} onchange="btToggleSelected(${recId}, this.checked)">
      </label>
      <div style="display:flex;flex-direction:column;gap:4px;min-width:0">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="strat-name">${STRAT_NAMES[h.strategy_id] || h.strategy_id}</span>
          <span class="mono" style="font-size:.76rem;color:var(--t3)">${btEscapeHtml(h.symbol)}</span>
          <span class="bt-folder-tag">${btEscapeHtml(folderLabel)}</span>
          <span class="bt-comment-tag" id="btCommentTag-${recId}">评论 ${commentCount}</span>
        </div>
      </div>
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

    const [r, commentPayload] = await Promise.all([
      btFetchRecordDetail(h, params),
      api(`/api/v1/backtest/history/${h.id}/comments`),
    ]);

    _btCommentsCache[h.id] = commentPayload.comments || [];
    renderRecDetail(detailEl, r, params, h);
  } catch (e) {
    detailEl.innerHTML = '<div style="color:var(--r);padding:8px;text-align:center">回测失败</div>';
  }
}

async function btFetchRecordDetail(record, params) {
  const start = record.start_date || '2025-01-01';
  const end = record.end_date || today();
  if (record.strategy_id === 'custom_expr') {
    return api('/api/v1/ml/custom-expression/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expression: params.expression || '',
        symbol: record.symbol,
        start,
        end,
        initial_capital: params.initial_capital || 1000000,
        commission: params.commission || 0.001,
        save_result: false,
      }),
    });
  }
  if ((record.strategy_id || '').startsWith('gp:')) {
    return api('/api/v1/backtest/gp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        gp_id: (params.gp_id || record.strategy_id.slice(3)),
        symbol: record.symbol,
        start,
        end,
        initial_capital: params.initial_capital || 1000000,
        commission: params.commission || 0.001,
        save_result: false,
      }),
    });
  }
  if ((record.strategy_id || '').startsWith('ml:')) {
    return api('/api/v1/backtest/ml', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: (params.model_id || record.strategy_id.slice(3)),
        symbol: record.symbol,
        start,
        end,
        initial_capital: params.initial_capital || 1000000,
        commission: params.commission || 0.001,
        threshold: params.threshold ?? 0.5,
        save_result: false,
      }),
    });
  }
  return api('/api/v1/backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strategy_id: record.strategy_id,
      symbol: record.symbol,
      start,
      end,
      params,
      save_result: false,
    }),
  });
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
<b>策略:</b> ${STRAT_NAMES[r.strategy_id] || r.strategy_id} | <b>股票:</b> ${btEscapeHtml(r.symbol)}<br>
<b>文件夹:</b> ${btEscapeHtml(meta.folder_name || '未分类')} | <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();btMoveSingleRecord(${meta.id})">移动</button><br>
<b>初始资金:</b> <span class="mono">${(cap / 10000).toFixed(0)}万</span> → <b>最终权益:</b> <span class="mono" style="color:${r.total_return >= 0 ? 'var(--g)' : 'var(--r)'}">${(finalCap / 10000).toFixed(2)}万</span><br>
<b>交易成本:</b> ${(comm * 1000).toFixed(1)}‰${pj ? ' | <b>参数:</b> ' + btEscapeHtml(pj) : ''}
</div>`;

  if (r.trades && r.trades.length) {
    html += renderTradeTable(r.trades, cap, comm);
  }

  html += renderBtComments(meta.id);
  container.innerHTML = html;
}

function renderBtComments(recordId) {
  const comments = _btCommentsCache[recordId] || [];
  return `
    <div class="bt-comment-box" onclick="event.stopPropagation()">
      <div class="bt-comment-head">
        <div class="card-title" style="margin-bottom:0">评论 / 复盘想法</div>
        <span style="font-size:.72rem;color:var(--t3)">${comments.length} 条</span>
      </div>
      <textarea id="btCommentInput-${recordId}" class="bt-comment-input" placeholder="记录这次回测时的想法、假设、市场背景..."></textarea>
      <div class="btn-group" style="margin:8px 0 0">
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation();btCreateComment(${recordId})">添加评论</button>
      </div>
      <div class="bt-comment-list">
        ${comments.length ? comments.map(item => renderBtCommentItem(item)).join('') : '<div class="empty-state" style="padding:18px 12px">还没有评论，适合把当时的判断记下来</div>'}
      </div>
    </div>
  `;
}

function renderBtCommentItem(item) {
  return `<div class="bt-comment-item">
    <div class="bt-comment-meta">
      <span>${(item.updated_at || '').replace('T', ' ').slice(0, 16)}</span>
      <div style="display:flex;align-items:center;gap:6px">
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();btEditComment(${item.id})">编辑</button>
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();btDeleteComment(${item.id})">删除</button>
      </div>
    </div>
    <div class="bt-comment-content" id="btCommentContent-${item.id}">${btEscapeHtml(item.content).replaceAll('\n', '<br>')}</div>
  </div>`;
}

function btRecCard(label, value, cls) {
  return `<div class="bt-card"><div class="label">${label}</div><div class="val ${cls}">${value}</div></div>`;
}

async function btCreateFolder() {
  const name = prompt('请输入文件夹名称');
  if (!name || !name.trim()) return;
  try {
    await api('/api/v1/backtest/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    });
    toast('文件夹已创建');
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('创建失败: ' + e.message, 'error');
  }
}

async function btRenameFolder(folderId) {
  const currentName = btFolderName(folderId);
  const name = prompt('修改文件夹名称', currentName);
  if (!name || !name.trim() || name.trim() === currentName) return;
  try {
    await api(`/api/v1/backtest/folders/${folderId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim() }),
    });
    toast('文件夹已更新');
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('更新失败: ' + e.message, 'error');
  }
}

async function btDeleteFolder(folderId) {
  const folderName = btFolderName(folderId);
  if (!confirm(`确认删除文件夹“${folderName}”？其中记录会保留并回到未分类。`)) return;
  try {
    await api(`/api/v1/backtest/folders/${folderId}`, { method: 'DELETE' });
    toast('文件夹已删除');
    if (document.getElementById('btFolderFilter')?.value === String(folderId)) {
      document.getElementById('btFolderFilter').value = '';
    }
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}

async function btMoveSelected() {
  const recordIds = btSelectedIds();
  if (!recordIds.length) {
    toast('请先选择记录', 'error');
    return;
  }
  const targetValue = document.getElementById('btFolderMoveTarget')?.value || '';
  const folderId = targetValue ? Number(targetValue) : null;
  try {
    await api('/api/v1/backtest/history/batch-move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record_ids: recordIds, folder_id: folderId }),
    });
    toast(`已移动到${folderId ? `「${btFolderName(folderId)}」` : '未分类'}`);
    btClearSelected();
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('移动失败: ' + e.message, 'error');
  }
}

async function btMoveSingleRecord(recordId) {
  const options = ['0: 未分类', ...App.btFolders.map(f => `${f.id}: ${f.name}`)].join('\n');
  const raw = prompt(`输入目标文件夹 ID：\n${options}`, '0');
  if (raw == null) return;
  const folderId = raw === '0' || raw === '' ? null : Number(raw);
  if (raw !== '0' && raw !== '' && !App.btFolders.some(f => f.id === folderId)) {
    toast('文件夹不存在', 'error');
    return;
  }
  try {
    await api('/api/v1/backtest/history/batch-move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record_ids: [recordId], folder_id: folderId }),
    });
    toast('记录已移动');
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('移动失败: ' + e.message, 'error');
  }
}

async function btDeleteSelected() {
  const recordIds = btSelectedIds();
  if (!recordIds.length) {
    toast('请先选择记录', 'error');
    return;
  }
  if (!confirm(`确认批量删除选中的 ${recordIds.length} 条回测记录？`)) return;
  try {
    await api('/api/v1/backtest/history/batch-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record_ids: recordIds }),
    });
    toast('批量删除完成');
    btClearSelected();
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('批量删除失败: ' + e.message, 'error');
  }
}

async function deleteBtRecord(recordId) {
  if (!confirm('确认删除该回测记录？')) return;
  try {
    await api(`/api/v1/backtest/history/${recordId}`, { method: 'DELETE' });
    _btRecSelected.delete(recordId);
    toast('已删除');
    await loadBtFolders();
    await loadBtRecords();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}

async function btCreateComment(recordId) {
  const input = document.getElementById(`btCommentInput-${recordId}`);
  const content = input?.value?.trim();
  if (!content) {
    toast('请输入评论内容', 'error');
    return;
  }
  try {
    await api(`/api/v1/backtest/history/${recordId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    input.value = '';
    await btReloadComments(recordId);
    toast('评论已保存');
  } catch (e) {
    toast('评论失败: ' + e.message, 'error');
  }
}

async function btEditComment(commentId) {
  let targetRecordId = null;
  let current = null;
  Object.entries(_btCommentsCache).forEach(([recordId, list]) => {
    const found = (list || []).find(item => item.id === commentId);
    if (found) {
      targetRecordId = Number(recordId);
      current = found.content;
    }
  });
  if (!targetRecordId) return;
  const content = prompt('编辑评论', current || '');
  if (content == null || !content.trim()) return;
  try {
    await api(`/api/v1/backtest/comments/${commentId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content.trim() }),
    });
    await btReloadComments(targetRecordId);
    toast('评论已更新');
  } catch (e) {
    toast('更新失败: ' + e.message, 'error');
  }
}

async function btDeleteComment(commentId) {
  if (!confirm('确认删除这条评论？')) return;
  let targetRecordId = null;
  Object.entries(_btCommentsCache).forEach(([recordId, list]) => {
    if ((list || []).some(item => item.id === commentId)) targetRecordId = Number(recordId);
  });
  try {
    await api(`/api/v1/backtest/comments/${commentId}`, { method: 'DELETE' });
    if (targetRecordId) await btReloadComments(targetRecordId);
    toast('评论已删除');
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  }
}

async function btReloadComments(recordId) {
  const payload = await api(`/api/v1/backtest/history/${recordId}/comments`);
  _btCommentsCache[recordId] = payload.comments || [];
  const idx = (App.btHistoryData || []).findIndex(item => item.id === recordId);
  if (idx >= 0) {
    App.btHistoryData[idx].comment_count = _btCommentsCache[recordId].length;
    const tag = document.getElementById(`btCommentTag-${recordId}`);
    if (tag) tag.textContent = `评论 ${_btCommentsCache[recordId].length}`;
    const detail = document.getElementById(`btRecDetail-${idx}`);
    if (detail && detail.style.display !== 'none') {
      const meta = App.btHistoryData[idx];
      let params = {};
      try { params = JSON.parse(meta.params_json || '{}'); } catch (e) {}
      if (!params.initial_capital) params.initial_capital = meta.initial_capital || 1000000;
      if (!params.commission) params.commission = 0.001;
      const summaryHtml = detail.innerHTML.split('<div class="bt-comment-box"')[0];
      detail.innerHTML = summaryHtml + renderBtComments(recordId);
    }
  }
}

function loadEffectiveStrategies() { loadBtRecords(); }
