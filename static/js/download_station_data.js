/**
 * static/js/download_station_data.js
 *
 * Station Data modal — filter → Preview table → AI Summarize → Download Excel
 *
 * AI flow:
 *   1. User enters Anthropic API key in #stn-api-key
 *   2. User types a prompt in #stn-prompt-input  (e.g. "compute yield, input vs output")
 *   3. Click "Summarize Data" → calls Anthropic /v1/messages directly from the browser
 *      with ALL rows from all tables serialised as CSV-like text
 *   4. AI response rendered in #stn-ai-result-wrap (markdown-lite rendering)
 *   5. "Download Excel" → POST /api/download-station-data with { ...payload, ai_summary }
 *      so the backend can append an "AI Analysis" sheet
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
  let previewData     = null;   // full /api/preview-station-data response (has ALL rows)
  let currentPage     = 0;
  let aiSummary       = null;   // latest AI text — sent with download
  const PAGE_SIZE     = 20;

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
      stationSel.innerHTML = `
        <option value="">— Select station —</option>
        <option value="__all__" title="May be slow for large date ranges">★ All Stations</option>
      `;
      data.forEach(s => {
        const opt = document.createElement('option');
        opt.value = opt.textContent = s;
        stationSel.appendChild(opt);
      });
    } catch (err) {
      stationSel.innerHTML = '<option value="">Error loading stations</option>';
      setStatus(`⚠ ${err.message}`, 'error');
    }
  }

  /* ── Build payload ────────────────────────────────────────────────────── */
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
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);

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

  /* ── Render preview panel ─────────────────────────────────────────────── */
  function renderPreview() {
    if (!previewData) return;
    const { station, date_from, date_to, total_rows, total_tables, tables } = previewData;

    previewWrap.innerHTML = '';
    previewWrap.style.display = 'block';

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

    if (tables.length === 0) {
      previewWrap.innerHTML += '<p class="stn-preview-empty">No data found.</p>';
      return;
    }

    // Table selector tabs (multiple tables)
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

    // AI result area (hidden until AI runs)
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

    // Pagination
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

    promptBtn.disabled   = true;
    promptBtn.textContent = '⏳ Analyzing…';
    setStatus('🤖 AI is analyzing your data…', 'loading');

    // Hide old AI result
    const aiWrap = document.getElementById('stn-ai-result-wrap');
    if (aiWrap) aiWrap.style.display = 'none';

    try {
      const dataText = buildDataTextForAI();
      const fullPrompt = buildFullPrompt(prompt, dataText);

      const res = await fetch('/api/ai-summarize', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: apiKey,
        prompt:  fullPrompt,
      }),
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
      promptBtn.disabled   = false;
      promptBtn.textContent = 'Summarize Data';
    }
  });

  /**
   * Serialise ALL rows from ALL tables into a compact text block for the AI.
   * Each table is represented as a header + CSV-like rows.
   */
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
 
  /**
   * Render AI text with simple markdown-lite formatting inside the modal.
   */
  function renderAIResult(text) {
    const aiWrap = document.getElementById('stn-ai-result-wrap');
    if (!aiWrap) return;

    // Simple markdown-lite: bold, headers, lists, line breaks
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

    // Smooth scroll to AI result
    aiWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  /* ── Download ─────────────────────────────────────────────────────────── */
  dlBtn.addEventListener('click', async () => {
    const payload = lastPayload || buildPayload();
    if (!payload) return;

    // Attach AI summary if available so backend can add "AI Analysis" sheet
    const downloadPayload = { ...payload };
    if (aiSummary) {
      downloadPayload.ai_summary = aiSummary;
      downloadPayload.ai_prompt  = (promptInput?.value || '').trim();
    }

    setStatus('⏳ Generating Excel, please wait…', 'loading');
    dlBtn.disabled = true;

    try {
      const res = await fetch('/api/download-station-data', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(downloadPayload),
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

      const label = aiSummary ? '✅ Downloaded with AI Analysis sheet!' : '✅ Download started!';
      setStatus(label, 'success');
    } catch (err) {
      setStatus(`⚠ ${err.message}`, 'error');
    } finally {
      dlBtn.disabled = false;
    }
  });

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