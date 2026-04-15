/**
 * App initialization: bind tab events, set dates, kick off data loading.
 */
document.querySelectorAll('.tab-btn').forEach(b => {
  b.addEventListener('click', () => switchTab(b.dataset.tab));
});

initChartTabs();
setDates();
loadHealth();
loadDashboard();
setInterval(loadHealth, 30000);
