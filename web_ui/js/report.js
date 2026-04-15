/**
 * Report page.
 */
async function generateReport() {
  toast('生成中…');
  try {
    const r = await api('/api/v1/reports/daily', { method: 'POST' });
    document.getElementById('reportContent').innerHTML = mdHtml(r.content);
    switchTab('report', true);
    toast('日报已生成');
  } catch (e) { toast('生成失败', 'error'); }
}

function mdHtml(md) {
  return md
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '• $1')
    .replace(/\n/g, '<br>');
}
