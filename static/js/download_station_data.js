/**
 * static/js/download_station_data.js
 *
 * Station Data modal — filter → Preview table → Download Excel
 */

(function () {
  'use strict';

  /* ── DOM refs ─────────────────────────────────────────────────────────── */
  const openBtn    = document.getElementById('stn-open-btn');
  const overlay    = document.getElementById('stn-overlay');
  const closeBtn   = document.getElementById('stn-close-btn');
  const cancelBtn  = document.getElementById('stn-cancel-btn');
  const previewBtn = document.getElementById('stn-preview-btn');
  const dlBtn      = document.getElementById('stn-dl-btn');
  const statusEl   = document.getElementById('stn-status');
  const stationSel = document.getElementById('stn-station');
  const tabs       = document.querySelectorAll('.stn-tab');
  const panels     = document.querySelectorAll('.stn-panel');
  const previewWrap= document.getElementById('stn-preview-wrap');

  if (!openBtn) return;

  /* ── State ────────────────────────────────────────────────────────────── */
  let lastPayload      = null;   // reused by download without re-fetching
  let currentTableIdx  = 0;
  let previewData      = null;   // full /api/preview-station-data response
  let currentPage      = 0;
  const PAGE_SIZE      = 20;

  /* ── Open / close ─────────────────────────────────────────────────────── */
  openBtn.addEventListener('click', () => {
    overlay.classList.add('active');
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

  /* ── Station change → clear preview ──────────────────────────────────── */
  stationSel.addEventListener('change', clearPreview);

  /* ── Load stations ────────────────────────────────────────────────────── */
  let stationsLoaded = false;
  async function loadStations() {
    if (stationsLoaded) return;
    stationSel.innerHTML = '<option value="">Loading stations…</option>';
    try {
      const res  = await fetch('/api/stations-list');
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || 'Failed to load');
      stationSel.innerHTML = '<option value="">— Select station —</option>';
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

  /* ── Build payload from current form state ────────────────────────────── */
  function buildPayload() {
    const station = stationSel.value.trim();
    if (!station) { setStatus('Please select a station.', 'error'); return null; }

    const mode    = document.querySelector('.stn-tab.active')?.dataset.mode || 'today';
    const payload = { station, mode };

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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);

      lastPayload     = payload;
      previewData     = data;
      currentTableIdx = 0;
      currentPage     = 0;

      renderPreview();
      setStatus('', '');
      dlBtn.disabled = false;
    } catch (err) {
      setStatus(`⚠ ${err.message}`, 'error');
    } finally {
      previewBtn.disabled = false;
    }
  });

  /* ── Render preview panel ─────────────────────────────────────────────── */
  function renderPreview() {
    if (!previewData) return;
    const { station, date_from, date_to, total_rows, total_tables, tables } = previewData;

    previewWrap.innerHTML = '';
    previewWrap.style.display = 'block';

    // ── Summary bar
    const summary = document.createElement('div');
    summary.className = 'stn-preview-summary';
    summary.innerHTML = `
      <span class="stn-preview-badge">${station}</span>
      <span class="stn-preview-badge stn-badge-date">📅 ${date_from} → ${date_to}</span>
      <span class="stn-preview-badge stn-badge-count">🗂 ${total_tables} table${total_tables !== 1 ? 's' : ''}</span>
      <span class="stn-preview-badge stn-badge-count">📊 ${total_rows.toLocaleString()} total rows</span>
    `;
    previewWrap.appendChild(summary);

    if (tables.length === 0) {
      previewWrap.innerHTML += '<p class="stn-preview-empty">No data found.</p>';
      return;
    }

    // ── Table selector tabs (if multiple tables)
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

    // ── Table container
    const tableContainer = document.createElement('div');
    tableContainer.id = 'stn-table-container';
    previewWrap.appendChild(tableContainer);

    // ── Pagination
    const pagination = document.createElement('div');
    pagination.id = 'stn-pagination';
    pagination.className = 'stn-pagination';
    previewWrap.appendChild(pagination);

    renderTable();
  }

  function renderTable() {
    const container  = document.getElementById('stn-table-container');
    const pagination = document.getElementById('stn-pagination');
    if (!container || !previewData) return;

    const tbl     = previewData.tables[currentTableIdx];
    const rows    = tbl.rows;
    const cols    = tbl.columns;
    const start   = currentPage * PAGE_SIZE;
    const end     = Math.min(start + PAGE_SIZE, rows.length);
    const pageRows= rows.slice(start, end);
    const totalPages = Math.ceil(rows.length / PAGE_SIZE);

    // Table info line
    container.innerHTML = `
      <div class="stn-tbl-info">
        <strong>${tbl.schema}.${tbl.table}</strong>
        — showing rows ${start + 1}–${end} of ${tbl.row_count.toLocaleString()}
        ${tbl.row_count > 100 ? '<span class="stn-preview-note">(preview: first 100 rows)</span>' : ''}
      </div>
    `;

    // Scrollable table wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'stn-table-wrap';

    const table = document.createElement('table');
    table.className = 'stn-data-table';

    // Header
    const thead = document.createElement('thead');
    const hrow  = document.createElement('tr');
    hrow.innerHTML = `<th>#</th>` + cols.map(c => `<th>${escHtml(c)}</th>`).join('');
    thead.appendChild(hrow);
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    pageRows.forEach((row, i) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="stn-row-num">${start + i + 1}</td>` +
        row.map(cell => `<td>${cell === null ? '<span class="stn-null">NULL</span>' : escHtml(String(cell))}</td>`).join('');
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);

    // Pagination controls
    pagination.innerHTML = '';
    if (totalPages > 1) {
      const prev = document.createElement('button');
      prev.className = 'stn-page-btn';
      prev.textContent = '← Prev';
      prev.disabled = currentPage === 0;
      prev.addEventListener('click', () => { currentPage--; renderTable(); });

      const info = document.createElement('span');
      info.className = 'stn-page-info';
      info.textContent = `Page ${currentPage + 1} / ${totalPages}`;

      const next = document.createElement('button');
      next.className = 'stn-page-btn';
      next.textContent = 'Next →';
      next.disabled = currentPage >= totalPages - 1;
      next.addEventListener('click', () => { currentPage++; renderTable(); });

      pagination.appendChild(prev);
      pagination.appendChild(info);
      pagination.appendChild(next);
    }
  }

  function clearPreview() {
    previewWrap.innerHTML = '';
    previewWrap.style.display = 'none';
    previewData  = null;
    lastPayload  = null;
    dlBtn.disabled = true;
  }

  /* ── Download ─────────────────────────────────────────────────────────── */
  dlBtn.addEventListener('click', async () => {
    const payload = lastPayload || buildPayload();
    if (!payload) return;

    setStatus('⏳ Generating Excel, please wait…', 'loading');
    dlBtn.disabled = true;

    try {
      const res = await fetch('/api/download-station-data', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Server error ${res.status}`);
      }

      const blob  = await res.blob();
      const url   = URL.createObjectURL(blob);
      const a     = document.createElement('a');
      const disp  = res.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename="?([^"]+)"?/);
      a.download  = match ? match[1] : `${payload.station}_data.xlsx`;
      a.href      = url;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);

      setStatus('✅ Download started!', 'success');
    } catch (err) {
      setStatus(`⚠ ${err.message}`, 'error');
    } finally {
      dlBtn.disabled = false;
    }
  });

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function setStatus(msg, type) {
    statusEl.textContent = msg;
    statusEl.className   = `stn-status${type ? ' stn-status--' + type : ''}`;
  }

  function escHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

})();