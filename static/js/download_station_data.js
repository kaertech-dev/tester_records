/**
 * static/js/download_station_data.js  (yield edition)
 *
 * Additions over original:
 *   – renderYieldDashboard(yieldSummary) builds a Chart.js yield panel
 *     directly inside the preview wrap, above the data table.
 *   – previewData.yield_summary is forwarded to the dashboard renderer
 *     every time a preview loads.
 *   – No other logic changed.
 */

(function () {
  'use strict';

  /* ── DOM refs ─────────────────────────────────────────────────────────── */
  const openBtn     = document.getElementById('stn-open-btn');
  const overlay     = document.getElementById('stn-overlay');
  const closeBtn    = document.getElementById('stn-close-btn');
  const cancelBtn   = document.getElementById('stn-cancel-btn');
  const previewBtn  = document.getElementById('stn-preview-btn');
  const dlBtn       = document.getElementById('stn-dl-btn');
  const statusEl    = document.getElementById('stn-status');
  const dbSel       = document.getElementById('stn-database');
  const stationSel  = document.getElementById('stn-station');
  const tabs        = document.querySelectorAll('.stn-tab');
  const panels      = document.querySelectorAll('.stn-panel');
  const previewWrap = document.getElementById('stn-preview-wrap');
  const apiKeyInput = document.getElementById('stn-api-key');
  const promptInput = document.getElementById('stn-prompt-input');
  const promptBtn   = document.getElementById('stn-prompt-btn');

  if (!openBtn) return;

  /* ── State ────────────────────────────────────────────────────────────── */
  let lastPayload     = null;
  let currentTableIdx = 0;
  let previewData     = null;
  let currentPage     = 0;
  let aiSummary       = null;
  const PAGE_SIZE     = 20;

  /* ── Chart.js lazy-load ───────────────────────────────────────────────── */
  let chartJsReady = false;
  let _chartJsCallbacks = [];

  function withChartJs(cb) {
    if (chartJsReady) { cb(); return; }
    _chartJsCallbacks.push(cb);
    if (document.getElementById('_chartjs_script')) return;
    const s = document.createElement('script');
    s.id  = '_chartjs_script';
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js';
    s.onload = () => {
      chartJsReady = true;
      _chartJsCallbacks.forEach(fn => fn());
      _chartJsCallbacks = [];
    };
    document.head.appendChild(s);
  }

  /* ── Yield chart instances (kept so we can destroy before re-render) ──── */
  const _yieldCharts = {};

  function destroyYieldCharts() {
    Object.keys(_yieldCharts).forEach(k => {
      try { _yieldCharts[k].destroy(); } catch (_) {}
      delete _yieldCharts[k];
    });
  }

  /* ── Open / close ─────────────────────────────────────────────────────── */
  openBtn.addEventListener('click', () => {
    overlay.classList.add('active');
    loadDatabases();
    loadStations();
  });

  [closeBtn, cancelBtn].forEach(btn =>
    btn && btn.addEventListener('click', closeModal)
  );
  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });

  function closeModal() {
    overlay.classList.remove('active');
    setStatus('', '');
    clearPreview();
  }

  /* ── Tabs ─────────────────────────────────────────────────────────────── */
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`stn-panel-${tab.dataset.mode}`)?.classList.add('active');
      clearPreview();
    });
  });

  stationSel.addEventListener('change', clearPreview);
  dbSel?.addEventListener('change', () => {
    clearPreview();
    loadStations(dbSel.value);
  });

  /* ── Load databases ───────────────────────────────────────────────────── */
  let databasesLoaded = false;
  async function loadDatabases() {
    if (!dbSel || databasesLoaded) return;
    dbSel.innerHTML = '<option value="">Loading databases…</option>';
    try {
      const res  = await fetch('/api/active-databases');
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Failed to load databases');
      dbSel.innerHTML = '<option value="">— All databases —</option>';
      data.forEach(schema => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = schema;
        dbSel.appendChild(opt);
      });
      databasesLoaded = true;
    } catch (err) {
      dbSel.innerHTML = '<option value="">Error loading databases</option>';
      setStatus(`⚠ ${err.message}`, 'error');
    }
  }

  /* ── Load stations ────────────────────────────────────────────────────── */
  let stationsLoaded = false;
  async function loadStations(database = dbSel?.value || '') {
    stationSel.innerHTML = '<option value="">Loading stations…</option>';
    stationsLoaded = false;
    try {
      const qs = database ? `?database=${encodeURIComponent(database)}` : '';
      const res  = await fetch(`/api/stations-list${qs}`);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Failed to load');
      stationSel.innerHTML = `
        <option value="">— Select station —</option>
        <option value="__all__" title="May be slow for large date ranges">★ All Stations</option>
      `;
      data.forEach(s => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = s;
        stationSel.appendChild(opt);
      });
      stationsLoaded = true;
    } catch (err) {
      stationSel.innerHTML = '<option value="">Error loading stations</option>';
      setStatus(`⚠ ${err.message}`, 'error');
    }
  }

  /* ── Build payload ────────────────────────────────────────────────────── */
  function buildPayload() {
    const station = stationSel.value.trim();
    if (!station) { setStatus('Please select a station.', 'error'); return null; }

    const database = (dbSel?.value || '').trim();
    const mode     = document.querySelector('.stn-tab.active')?.dataset.mode || 'today';
    const payload  = { station, mode, ...(database ? { database } : {}) };

    if (mode === 'day') {
      const d = document.getElementById('stn-date').value;
      if (!d) { setStatus('Please select a date.', 'error'); return null; }
      payload.date = d;
    } else if (mode === 'week') {
      const y = document.getElementById('stn-week-year').value;
      const w = document.getElementById('stn-week-num').value;
      if (!y || !w) { setStatus('Please fill in year and week.', 'error'); return null; }
      payload.year = y; payload.week = w;
    } else if (mode === 'month') {
      const y = document.getElementById('stn-month-year').value;
      const m = document.getElementById('stn-month-num').value;
      if (!y || !m) { setStatus('Please fill in year and month.', 'error'); return null; }
      payload.year = y; payload.month = m;
    } else if (mode === 'range') {
      const f = document.getElementById('stn-range-start').value;
      const t = document.getElementById('stn-range-end').value;
      if (!f || !t) { setStatus('Please fill in both dates.', 'error'); return null; }
      if (f > t)    { setStatus('Start date must be before end date.', 'error'); return null; }
      payload.date_from = f; payload.date_to = t;
    }
    return payload;
  }

  /* ── Preview ──────────────────────────────────────────────────────────── */
  previewBtn.addEventListener('click', async () => {
    const payload = buildPayload();
    if (!payload) return;

    setStatus('⏳ Loading preview…', 'loading');
    previewBtn.disabled = true;
    clearPreview();

    try {
      const res  = await fetch('/api/preview-station-data', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });

      const text = await res.text();
      let data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = null;
        }
      }

      if (!res.ok) {
        const message = data?.error || text || `Server error ${res.status}`;
        throw new Error(message);
      }
      if (!data || data.error) {
        throw new Error(data?.error || 'Invalid response from server.');
      }

      lastPayload     = payload;
      previewData     = data;
      currentTableIdx = 0;
      currentPage     = 0;
      aiSummary       = null;

      renderPreview();
      setStatus('', '');
      dlBtn.disabled = false;
    } catch (err) {
      setStatus(`⚠ ${err.message}`, 'error');
    } finally {
      previewBtn.disabled = false;
    }
  });

  /* ════════════════════════════════════════════════════════════════════════
     YIELD DASHBOARD
  ════════════════════════════════════════════════════════════════════════ */

  /**
   * Build and inject the yield dashboard above the data table.
   * Uses Chart.js (lazy-loaded).
   */
  function renderYieldDashboard(yld, container) {
    if (!yld || !yld.has_yield_data) return;

    const overall = yld.overall;
    const pct     = overall.yield_pct;

    /* ── colour helpers ── */
    const yieldColor = p =>
      p >= 99    ? '#22c55e' :
      p >= 95    ? '#f59e0b' : '#ef4444';

    const yieldBg = p =>
      p >= 99    ? 'rgba(34,197,94,0.10)' :
      p >= 95    ? 'rgba(245,158,11,0.10)' : 'rgba(239,68,68,0.10)';

    /* ── wrapper ── */
    const wrap = document.createElement('div');
    wrap.className = 'stn-yield-dashboard';
    wrap.innerHTML = `
      <div class="stn-yield-header">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
             stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
        </svg>
        Yield Summary
      </div>

      <!-- KPI cards -->
      <div class="stn-yield-kpis">
        <div class="stn-yield-kpi" style="border-color:${yieldColor(pct)};background:${yieldBg(pct)}">
          <span class="stn-yield-kpi-label">Overall Yield</span>
          <span class="stn-yield-kpi-value" style="color:${yieldColor(pct)}">${pct.toFixed(2)}%</span>
        </div>
        <div class="stn-yield-kpi">
          <span class="stn-yield-kpi-label">Total Tested</span>
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
      </div>

      <!-- Charts row -->
      <div class="stn-yield-charts">
        <!-- Daily trend -->
        <div class="stn-yield-chart-box" id="stn-yield-box-daily" style="${!yld.by_date?.length ? 'display:none' : ''}">
          <div class="stn-yield-chart-title">Daily Yield %</div>
          <div style="position:relative;height:160px"><canvas id="stn-yield-daily"></canvas></div>
        </div>

        <!-- Shift -->
        <div class="stn-yield-chart-box" id="stn-yield-box-shift" style="${!yld.by_shift?.length ? 'display:none' : ''}">
          <div class="stn-yield-chart-title">By Shift</div>
          <div style="position:relative;height:160px"><canvas id="stn-yield-shift"></canvas></div>
        </div>

        <!-- PO -->
        <div class="stn-yield-chart-box" id="stn-yield-box-po" style="${!yld.by_po?.length ? 'display:none' : ''}">
          <div class="stn-yield-chart-title">By PO Number</div>
          <div style="position:relative;height:160px"><canvas id="stn-yield-po"></canvas></div>
        </div>
      </div>

      <!-- Fail reasons -->
      ${yld.fail_reasons?.length ? `
      <div class="stn-yield-fails">
        <div class="stn-yield-chart-title">Top Fail Reasons</div>
        <div style="position:relative;height:${Math.max(120, yld.fail_reasons.length * 22)}px">
          <canvas id="stn-yield-fails-chart"></canvas>
        </div>
      </div>` : ''}
    `;

    container.insertBefore(wrap, container.firstChild);

    /* ── draw charts after Chart.js loads ── */
    withChartJs(() => {
      const textColor = '#9ca3af';
      const gridColor = 'rgba(255,255,255,0.06)';

      /* Daily line chart */
      if (yld.by_date?.length) {
        const labels = yld.by_date.map(d => d.date);
        const data   = yld.by_date.map(d => +d.yield_pct.toFixed(2));
        const minY   = Math.max(0, Math.min(...data) - 2);

        _yieldCharts['daily'] = new Chart(
          document.getElementById('stn-yield-daily'),
          {
            type: 'line',
            data: {
              labels,
              datasets: [{
                label: 'Yield %',
                data,
                borderColor:     '#22c55e',
                backgroundColor: 'rgba(34,197,94,0.08)',
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointBackgroundColor: '#22c55e',
                borderDash: [],
              }],
            },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { ticks: { color: textColor, font: { size: 9 }, maxRotation: 45, autoSkip: true, maxTicksLimit: 10 }, grid: { color: gridColor } },
                y: { min: minY, max: 100.2, ticks: { color: textColor, font: { size: 10 }, callback: v => v.toFixed(1) + '%' }, grid: { color: gridColor } },
              },
            },
          }
        );
      }

      /* Shift bar chart */
      if (yld.by_shift?.length) {
        const labels = yld.by_shift.map(s => `Shift ${s.shift}`);
        const data   = yld.by_shift.map(s => +s.yield_pct.toFixed(2));

        _yieldCharts['shift'] = new Chart(
          document.getElementById('stn-yield-shift'),
          {
            type: 'bar',
            data: {
              labels,
              datasets: [{
                label: 'Yield %',
                data,
                backgroundColor: data.map(v => yieldColor(v) + '99'),
                borderColor:     data.map(v => yieldColor(v)),
                borderWidth: 1,
                borderRadius: 4,
              }],
            },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { ticks: { color: textColor, font: { size: 11 } }, grid: { display: false } },
                y: { min: Math.max(0, Math.min(...data) - 3), max: 100.2,
                     ticks: { color: textColor, font: { size: 10 }, callback: v => v.toFixed(1) + '%' },
                     grid: { color: gridColor } },
              },
            },
          }
        );
      }

      /* PO bar chart */
      if (yld.by_po?.length) {
        const labels = yld.by_po.map(p => p.po_num);
        const data   = yld.by_po.map(p => +p.yield_pct.toFixed(2));

        _yieldCharts['po'] = new Chart(
          document.getElementById('stn-yield-po'),
          {
            type: 'bar',
            data: {
              labels,
              datasets: [{
                label: 'Yield %',
                data,
                backgroundColor: data.map(v => yieldColor(v) + '99'),
                borderColor:     data.map(v => yieldColor(v)),
                borderWidth: 1,
                borderRadius: 4,
              }],
            },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { ticks: { color: textColor, font: { size: 10 }, maxRotation: 30, autoSkip: false }, grid: { display: false } },
                y: { min: Math.max(0, Math.min(...data) - 3), max: 100.2,
                     ticks: { color: textColor, font: { size: 10 }, callback: v => v.toFixed(1) + '%' },
                     grid: { color: gridColor } },
              },
            },
          }
        );
      }

      /* Fail reasons horizontal bar */
      if (yld.fail_reasons?.length) {
        const labels = yld.fail_reasons.map(f => f.reason);
        const data   = yld.fail_reasons.map(f => f.count);

        _yieldCharts['fails'] = new Chart(
          document.getElementById('stn-yield-fails-chart'),
          {
            type: 'bar',
            data: {
              labels,
              datasets: [{
                label: 'Count',
                data,
                backgroundColor: 'rgba(239,68,68,0.7)',
                borderColor:     '#ef4444',
                borderWidth: 1,
                borderRadius: 3,
                borderSkipped: false,
              }],
            },
            options: {
              indexAxis: 'y',
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false } },
              scales: {
                x: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
                y: { ticks: { color: textColor, font: { size: 10 } }, grid: { display: false } },
              },
            },
          }
        );
      }
    });
  }

  /* ── Render preview panel ─────────────────────────────────────────────── */
  function renderPreview() {
    if (!previewData) return;
    const { station, date_from, date_to, total_rows, total_tables, tables } = previewData;

    previewWrap.innerHTML = '';
    previewWrap.style.display = 'block';
    destroyYieldCharts();

    // Summary bar
    const summary = document.createElement('div');
    summary.className = 'stn-preview-summary';
    summary.innerHTML = `
      <span class="stn-preview-badge">${escHtml(station)}</span>
      <span class="stn-preview-badge stn-badge-date">📅 ${escHtml(date_from)} → ${escHtml(date_to)}</span>
      <span class="stn-preview-badge stn-badge-count">🗂 ${total_tables} table${total_tables !== 1 ? 's' : ''}</span>
      <span class="stn-preview-badge stn-badge-count">📊 ${total_rows.toLocaleString()} total rows</span>
    `;
    previewWrap.appendChild(summary);

    // ── Yield dashboard (NEW) ──────────────────────────────────────────────
    if (previewData.yield_summary?.has_yield_data) {
      renderYieldDashboard(previewData.yield_summary, previewWrap);
    }

    if (tables.length === 0) {
      previewWrap.innerHTML += '<p class="stn-preview-empty">No data found.</p>';
      return;
    }

    // Table selector tabs
    if (tables.length > 1) {
      const tabBar = document.createElement('div');
      tabBar.className = 'stn-tbl-tabs';
      tables.forEach((tbl, idx) => {
        const btn = document.createElement('button');
        btn.className = 'stn-tbl-tab' + (idx === 0 ? ' active' : '');
        btn.textContent = `${tbl.schema} (${tbl.row_count.toLocaleString()})`;
        btn.addEventListener('click', () => {
          currentTableIdx = idx;
          currentPage     = 0;
          document.querySelectorAll('.stn-tbl-tab').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          renderTable();
        });
        tabBar.appendChild(btn);
      });
      previewWrap.appendChild(tabBar);
    }

    const tableContainer = document.createElement('div');
    tableContainer.id = 'stn-table-container';
    previewWrap.appendChild(tableContainer);

    const pagination = document.createElement('div');
    pagination.id = 'stn-pagination';
    pagination.className = 'stn-pagination';
    previewWrap.appendChild(pagination);

    const aiWrap = document.createElement('div');
    aiWrap.id = 'stn-ai-result-wrap';
    aiWrap.className = 'stn-ai-result-wrap';
    aiWrap.style.display = 'none';
    previewWrap.appendChild(aiWrap);

    renderTable();
  }

  function renderTable() {
    const container  = document.getElementById('stn-table-container');
    const pagination = document.getElementById('stn-pagination');
    if (!container || !previewData) return;

    const tbl        = previewData.tables[currentTableIdx];
    const rows       = tbl.rows;
    const cols       = tbl.columns;
    const start      = currentPage * PAGE_SIZE;
    const end        = Math.min(start + PAGE_SIZE, rows.length);
    const pageRows   = rows.slice(start, end);
    const totalPages = Math.ceil(rows.length / PAGE_SIZE);

    container.innerHTML = `
      <div class="stn-tbl-info">
        <strong>${escHtml(tbl.schema)}.${escHtml(tbl.table)}</strong>
        — showing rows ${start + 1}–${end} of ${tbl.row_count.toLocaleString()}
        ${tbl.row_count > 100 ? '<span class="stn-preview-note">(preview: first 100 rows)</span>' : ''}
      </div>
    `;

    const wrapper = document.createElement('div');
    wrapper.className = 'stn-table-wrap';

    const table = document.createElement('table');
    table.className = 'stn-data-table';

    const thead = document.createElement('thead');
    const hrow  = document.createElement('tr');
    hrow.innerHTML = `<th>#</th>` + cols.map(c => `<th>${escHtml(c)}</th>`).join('');
    thead.appendChild(hrow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    pageRows.forEach((row, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="stn-row-num">${start + i + 1}</td>` +
        row.map(cell => `<td>${cell === null
          ? '<span class="stn-null">NULL</span>'
          : escHtml(String(cell))}</td>`).join('');
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);

    pagination.innerHTML = '';
    if (totalPages > 1) {
      const prev = document.createElement('button');
      prev.className   = 'stn-page-btn';
      prev.textContent = '← Prev';
      prev.disabled    = currentPage === 0;
      prev.addEventListener('click', () => { currentPage--; renderTable(); });

      const info = document.createElement('span');
      info.className   = 'stn-page-info';
      info.textContent = `Page ${currentPage + 1} / ${totalPages}`;

      const next = document.createElement('button');
      next.className   = 'stn-page-btn';
      next.textContent = 'Next →';
      next.disabled    = currentPage >= totalPages - 1;
      next.addEventListener('click', () => { currentPage++; renderTable(); });

      pagination.appendChild(prev);
      pagination.appendChild(info);
      pagination.appendChild(next);
    }
  }

  function clearPreview() {
    destroyYieldCharts();
    previewWrap.innerHTML  = '';
    previewWrap.style.display = 'none';
    previewData  = null;
    lastPayload  = null;
    aiSummary    = null;
    dlBtn.disabled = true;
  }

  /* ── AI Summarize ─────────────────────────────────────────────────────── */
  promptBtn.addEventListener('click', async () => {
    const apiKey = (apiKeyInput?.value || '').trim();
    const prompt = (promptInput?.value || '').trim();

    if (!apiKey) {
      setStatus('⚠ Please enter your Anthropic API key.', 'error');
      return;
    }
    if (!prompt) {
      setStatus('⚠ Please enter a prompt first.', 'error');
      return;
    }
    if (!previewData || !previewData.tables || previewData.tables.length === 0) {
      setStatus('⚠ Please preview data first before summarizing.', 'error');
      return;
    }
    if (stationSel.value === '__all__' && previewData?.total_rows > 20000) {
      if (!confirm(`This will export ${previewData.total_rows.toLocaleString()} rows and may take a while. Continue?`)) return;
    }

    promptBtn.disabled    = true;
    promptBtn.textContent = '⏳ Analyzing…';
    setStatus('🤖 AI is analyzing your data…', 'loading');

    const aiWrap = document.getElementById('stn-ai-result-wrap');
    if (aiWrap) aiWrap.style.display = 'none';

    try {
      const dataText   = buildDataTextForAI();
      const fullPrompt = buildFullPrompt(prompt, dataText);

      const res = await fetch('/api/ai-summarize', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey, prompt: fullPrompt }),
      });

      const result = await res.json();
      if (!res.ok) {
        const errMsg = result?.error?.message || result?.error || `API error ${res.status}`;
        throw new Error(errMsg);
      }

      const text = result.content
        ?.filter(b => b.type === 'text')
        .map(b => b.text)
        .join('\n') || '(No response)';

      aiSummary = text;
      renderAIResult(text);
      setStatus('✅ AI analysis complete! You can now download with the AI sheet included.', 'success');
    } catch (err) {
      setStatus(`⚠ AI Error: ${err.message}`, 'error');
    } finally {
      promptBtn.disabled    = false;
      promptBtn.textContent = 'Summarize Data';
    }
  });

  function buildDataTextForAI() {
    if (!previewData?.tables) return '(no data)';
    return previewData.tables.map(tbl => {
      const header = tbl.columns.join(', ');
      const rows   = tbl.rows.map(row =>
        row.map(cell => (cell === null ? 'NULL' : String(cell))).join(', ')
      ).join('\n');
      return `TABLE: ${tbl.schema}.${tbl.table} (${tbl.row_count} rows)\n${header}\n${rows}`;
    }).join('\n\n---\n\n');
  }

  function buildFullPrompt(userPrompt, dataText) {
    return (
      `You are a data analyst assistant. The user has provided station data and wants you to analyze it.\n\n` +
      `STATION: ${previewData.station}\n` +
      `DATE RANGE: ${previewData.date_from} → ${previewData.date_to}\n\n` +
      `DATA:\n${dataText}\n\n` +
      `USER REQUEST:\n${userPrompt}\n\n` +
      `Please provide a clear, structured analysis. Use tables or lists where helpful.`
    );
  }

  function renderAIResult(text) {
    const aiWrap = document.getElementById('stn-ai-result-wrap');
    if (!aiWrap) return;

    let html = escHtml(text)
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/^# (.+)$/gm, '<h2>$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/^[-•] (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>');

    aiWrap.innerHTML = `
      <div class="stn-ai-result-header">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="#c084fc" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"/>
          <path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12
                   M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/>
        </svg>
        AI Analysis
        <span class="stn-ai-result-badge">Powered by Claude</span>
      </div>
      <div class="stn-ai-result-body"><p>${html}</p></div>
    `;
    aiWrap.style.display = 'block';
    aiWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ── Download ─────────────────────────────────────────────────────────── */
  dlBtn.addEventListener('click', () => {
    const payload = lastPayload || buildPayload();
    if (!payload) return;
    dlBtn.disabled = true;
    setStatus('', '');
    showDownloadProgress(payload);
  });

  function showDownloadProgress(payload) {
    let progressWrap = document.getElementById('stn-dl-progress');
    if (!progressWrap) {
      progressWrap = document.createElement('div');
      progressWrap.id = 'stn-dl-progress';
      progressWrap.className = 'stn-dl-progress-wrap';
      previewWrap.parentNode.insertBefore(progressWrap, previewWrap.nextSibling);
    }
    progressWrap.style.display = 'block';
    progressWrap.innerHTML = `
      <div class="stn-dl-progress-header">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="#4ade80" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Preparing Download…
      </div>
      <div class="stn-dl-progress-bar-wrap">
        <div id="stn-dl-bar" class="stn-dl-bar" style="width:0%"></div>
      </div>
      <div id="stn-dl-progress-label" class="stn-dl-progress-label">Connecting…</div>
      <div id="stn-dl-log" class="stn-dl-log"></div>
    `;

    const bar   = document.getElementById('stn-dl-bar');
    const label = document.getElementById('stn-dl-progress-label');
    const log   = document.getElementById('stn-dl-log');

    const qs = new URLSearchParams({ ...payload });
    if (aiSummary) {
      qs.set('ai_summary', aiSummary);
      qs.set('ai_prompt', (promptInput?.value || '').trim());
    }

    const evtSource = new EventSource(`/api/download-station-data-stream?${qs}`);

    evtSource.onmessage = (e) => {
      const msg = JSON.parse(e.data);

      if (msg.type === 'start') {
        label.textContent = `Fetching 0 / ${msg.total} tables…`;

      } else if (msg.type === 'progress') {
        const pct = Math.round((msg.done / msg.total) * 90);
        bar.style.width   = pct + '%';
        label.textContent = `Fetching ${msg.done} / ${msg.total} tables…`;
        const entry = document.createElement('div');
        entry.className   = 'stn-dl-log-entry' + (msg.error ? ' stn-dl-log-error' : '');
        entry.textContent = msg.error
          ? `✖  ${msg.table} — ${msg.error}`
          : `✔  ${msg.table}  (${msg.rows.toLocaleString()} rows)`;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;

      } else if (msg.type === 'building') {
        bar.style.width   = '92%';
        label.textContent = 'Building Excel file (including Yield Summary sheet)…';

      } else if (msg.type === 'done') {
        bar.style.width      = '100%';
        bar.style.background = '#4ade80';
        label.textContent    = `✅ Done — ${msg.total_rows.toLocaleString()} rows`;
        evtSource.close();
        dlBtn.disabled = false;
        const a    = document.createElement('a');
        a.href     = msg.download_url;
        a.download = msg.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();

      } else if (msg.type === 'error') {
        bar.style.background = '#f87171';
        label.textContent    = `⚠ ${msg.message}`;
        evtSource.close();
        dlBtn.disabled = false;
        setStatus(`⚠ ${msg.message}`, 'error');
      }
    };

    evtSource.onerror = () => {
      label.textContent = '⚠ Connection lost.';
      evtSource.close();
      dlBtn.disabled = false;
    };
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function setStatus(msg, type) {
    statusEl.textContent = msg;
    statusEl.className   = `dl-status${type ? ' stn-status--' + type : ''}`;
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

})();