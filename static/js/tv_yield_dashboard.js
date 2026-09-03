/**
 * static/js/tv_yield_dashboard.js
 *
 * Always-on "Live Yield Monitor" panel embedded directly in the main
 * Process Traceability window — built for unattended TV/kiosk display.
 *
 *   - Loads TODAY's yield data for ALL stations on page load.
 *   - Auto-refreshes every 60 seconds.
 *   - Never throws blocking errors (no alert/confirm) — a failed refresh
 *     shows a small inline banner and just tries again on the next tick.
 *     The last successfully rendered dashboard stays on screen while a
 *     refresh is retrying, so the TV never goes blank on a hiccup.
 *   - Destroys old Chart.js instances before every re-render so memory
 *     stays flat across many hours of continuous refreshing.
 *
 * Requires a container in the page:
 *   <div id="tv-yield-container">...</div>
 * and optionally:
 *   <span id="tv-yield-updated"></span>
 *   <span id="tv-yield-live-dot"></span>
 */

(function () {
  'use strict';

  const REFRESH_MS = 60 * 1000;

  const container = document.getElementById('tv-yield-container');
  const updatedEl  = document.getElementById('tv-yield-updated');
  const liveDot    = document.getElementById('tv-yield-live-dot');

  if (!container) return; // section not present on this page — nothing to do

  /* ── Chart.js lazy-load (independent of any other loader on the page,
     but polls instead of double-fetching if one is already in flight) ── */
  let _callbacks = [];

  function withChartJs(cb) {
    if (window.Chart) { cb(); return; }
    _callbacks.push(cb);
    if (document.getElementById('_chartjs_script_tv') || document.getElementById('_chartjs_script')) {
      pollForChart();
      return;
    }
    const s = document.createElement('script');
    s.id  = '_chartjs_script_tv';
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js';
    s.onload = () => {
      _callbacks.forEach(fn => fn());
      _callbacks = [];
    };
    document.head.appendChild(s);
  }

  function pollForChart(attempt) {
    attempt = attempt || 0;
    if (window.Chart) {
      _callbacks.forEach(fn => fn());
      _callbacks = [];
      return;
    }
    if (attempt > 100) return; // ~20s, give up quietly this cycle
    setTimeout(() => pollForChart(attempt + 1), 200);
  }

  /* ── Chart instances (destroyed + rebuilt each refresh) ─────────────── */
  const charts = {};
  function destroyCharts() {
    Object.keys(charts).forEach(k => {
      try { charts[k].destroy(); } catch (_) {}
      delete charts[k];
    });
  }

  /* ── Colour helpers (match the modal's yield thresholds) ─────────────── */
  const yieldColor = p => (p >= 99 ? '#22c55e' : p >= 95 ? '#f59e0b' : '#ef4444');
  const yieldBg    = p => (p >= 99 ? 'rgba(34,197,94,0.10)' : p >= 95 ? 'rgba(245,158,11,0.10)' : 'rgba(239,68,68,0.10)');

  /* ── Fetch + render ───────────────────────────────────────────────────── */
  async function refresh() {
    try {
      const res = await fetch('/traceability/api/preview-station-data', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ station: '__all__', mode: 'today' }),
      });
      const data = await res.json();

      if (!res.ok || data.error) {
        showError(data?.error || `Server error ${res.status}`);
        setLive(false);
        return;
      }

      render(data);
      setLive(true);
      stampUpdated();
    } catch (err) {
      showError(err.message);
      setLive(false);
    }
  }

  function setLive(ok) {
    if (!liveDot) return;
    liveDot.classList.toggle('tv-live-ok', ok);
    liveDot.classList.toggle('tv-live-bad', !ok);
  }

  function stampUpdated() {
    if (!updatedEl) return;
    updatedEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }

  function showError(msg) {
    // Only blank the panel if nothing has ever rendered yet — otherwise
    // keep the last good dashboard on screen and just flag the failure.
    if (!container.dataset.hasRendered) {
      container.innerHTML = `<p class="tv-yield-error">⚠ ${escHtml(msg)} — retrying…</p>`;
    }
    if (updatedEl) updatedEl.textContent = '⚠ Refresh failed — retrying…';
  }

  function render(data) {
    const yld = data.yield_summary;
    destroyCharts();
    container.innerHTML = '';
    container.dataset.hasRendered = '1';

    if (!yld || !yld.has_yield_data) {
      container.innerHTML = '<p class="tv-yield-empty">No yield data recorded yet today.</p>';
      return;
    }

    const overall = yld.overall;
    const pct     = overall.yield_pct;

    const wrap = document.createElement('div');
    wrap.className = 'stn-yield-dashboard tv-yield-dashboard';
    wrap.innerHTML = `
      <div class="stn-yield-kpis">
        <div class="stn-yield-kpi" style="border-color:${yieldColor(pct)};background:${yieldBg(pct)}">
          <span class="stn-yield-kpi-label">Overall Yield</span>
          <span class="stn-yield-kpi-value" style="color:${yieldColor(pct)}">${pct.toFixed(2)}%</span>
        </div>
        <div class="stn-yield-kpi">
          <span class="stn-yield-kpi-label">Total Unit Tested Today</span>
          <span class="stn-yield-kpi-value">${overall.total.toLocaleString()}</span>
        </div>
        <div class="stn-yield-kpi" style="border-color:#22c55e;background:rgba(34,197,94,0.06)">
          <span class="stn-yield-kpi-label">Pass</span>
          <span class="stn-yield-kpi-value" style="color:#22c55e">${overall.pass.toLocaleString()}</span>
        </div>
        <div class="stn-yield-kpi" style="border-color:#ef4444;background:rgba(239,68,68,0.06)">
          <span class="stn-yield-kpi-label">Fail</span>
          <span class="stn-yield-kpi-value" style="color:#ef4444">${overall.fail.toLocaleString()}</span>
        </div>
        <div class="stn-yield-kpi">
          <span class="stn-yield-kpi-label">Process Stations</span>
          <span class="stn-yield-kpi-value">${data.total_tables}</span>
        </div>
      </div>

      <div class="stn-yield-charts">
        <div class="stn-yield-chart-box" id="tv-box-shift" style="${!yld.by_shift?.length ? 'display:none' : ''}">
          <div class="stn-yield-chart-title">By Shift</div>
          <div style="position:relative;height:300px"><canvas id="tv-chart-shift"></canvas></div>
        </div>
        <div class="stn-yield-chart-box" id="tv-box-po" style="${!yld.by_po?.length ? 'display:none' : ''}">
          <div class="stn-yield-chart-title">By PO Number</div>
          <div style="position:relative;height:300px"><canvas id="tv-chart-po"></canvas></div>
        </div>
      </div>

      ${yld.fail_reasons?.length ? `
      <div class="stn-yield-fails">
        <div class="stn-yield-chart-title">Top Fail Reasons Today</div>
        <div style="position:relative;height:${Math.max(140, yld.fail_reasons.length * 24)}px">
          <canvas id="tv-chart-fails"></canvas>
        </div>
      </div>` : ''}
    `;
    container.appendChild(wrap);

    withChartJs(() => {
      const textColor = '#9ca3af';
      const gridColor = 'rgba(255,255,255,0.06)';

      if (yld.by_shift?.length) {
        const labels = yld.by_shift.map(s => `Shift ${s.shift}`);
        const vals   = yld.by_shift.map(s => +s.yield_pct.toFixed(2));
        charts.shift = new Chart(document.getElementById('tv-chart-shift'), {
          type: 'bar',
          data: { labels, datasets: [{
            data: vals,
            backgroundColor: vals.map(v => yieldColor(v) + '99'),
            borderColor:     vals.map(v => yieldColor(v)),
            borderWidth: 1, borderRadius: 4,
          }] },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: textColor, font: { size: 12 } }, grid: { display: false } },
              y: { min: Math.max(0, Math.min(...vals) - 3), max: 100.2,
                   ticks: { color: textColor, font: { size: 11 }, callback: v => v.toFixed(1) + '%' },
                   grid: { color: gridColor } },
            },
          },
        });
      }

      if (yld.by_po?.length) {
        const labels = yld.by_po.map(p => p.po_num);
        const vals   = yld.by_po.map(p => +p.yield_pct.toFixed(2));
        charts.po = new Chart(document.getElementById('tv-chart-po'), {
          type: 'bar',
          data: { labels, datasets: [{
            data: vals,
            backgroundColor: vals.map(v => yieldColor(v) + '99'),
            borderColor:     vals.map(v => yieldColor(v)),
            borderWidth: 1, borderRadius: 4,
          }] },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: textColor, font: { size: 11 }, maxRotation: 30 }, grid: { display: false } },
              y: { min: Math.max(0, Math.min(...vals) - 3), max: 100.2,
                   ticks: { color: textColor, font: { size: 11 }, callback: v => v.toFixed(1) + '%' },
                   grid: { color: gridColor } },
            },
          },
        });
      }

      if (yld.fail_reasons?.length) {
        const labels = yld.fail_reasons.map(f => f.reason);
        const vals   = yld.fail_reasons.map(f => f.count);
        charts.fails = new Chart(document.getElementById('tv-chart-fails'), {
          type: 'line',
          data: { labels, datasets: [{
            data: vals,
            backgroundColor: 'rgba(239,68,68,0.7)',
            borderColor:     '#ef4444',
            borderWidth: 1, borderRadius: 3, borderSkipped: false,
            pointBackgroundColor: 'rgba(239,68,68,0.7)',
            color: '#ffff',
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0
          }] },
          options: {
            indexAxis: 'y', responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: textColor, font: { size: 11 } }, grid: { color: gridColor } },
              y: { ticks: { color: textColor, font: { size: 11 } }, grid: { display: false } },
            },
          },
        });
      }
    });
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */
  refresh();
  setInterval(refresh, REFRESH_MS);

})();