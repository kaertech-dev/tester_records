// download_data.js

(function () {
    'use strict';

    /* ── DOM refs ──────────────────────────────────────────────── */
    const overlay  = document.getElementById('download-overlay');
    const tabs     = document.querySelectorAll('.dl-tab');
    const panels   = document.querySelectorAll('.dl-panel');
    const dlBtn    = document.getElementById('dl-btn-download');
    const status   = document.getElementById('dl-status');

    /* ── Open / close ──────────────────────────────────────────── */
    function openModal() {
        overlay.classList.add('active');
        clearStatus();
    }

    function closeModal() {
        overlay.classList.remove('active');
    }

    document.getElementById('dl-open-btn')?.addEventListener('click', openModal);
    document.getElementById('dl-close-btn')?.addEventListener('click', closeModal);
    document.getElementById('dl-cancel-btn')?.addEventListener('click', closeModal);

    // Close on backdrop click
    overlay?.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && overlay?.classList.contains('active')) closeModal();
    });

    /* ── Tab switching ─────────────────────────────────────────── */
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById('panel-' + tab.dataset.mode);
            if (target) target.classList.add('active');
            clearStatus();
        });
    });

    /* ── Helpers ───────────────────────────────────────────────── */
    function activeMode() {
        return document.querySelector('.dl-tab.active')?.dataset.mode || 'today';
    }

    function val(id) {
        return document.getElementById(id)?.value?.trim() || '';
    }

    function setStatus(msg, isError = false) {
        if (!status) return;
        status.textContent = msg;
        status.className   = 'dl-status' + (isError ? ' error' : '');
    }

    function clearStatus() {
        setStatus('');
    }

    /* ── Build query string ────────────────────────────────────── */
    function buildParams() {
        const mode   = activeMode();
        const params = new URLSearchParams({ mode });

        if (mode === 'day') {
            const d = val('dl-date');
            if (!d) return null;
            params.set('date', d);
        } else if (mode === 'week') {
            const y = val('dl-week-year');
            const w = val('dl-week-num');
            if (!y || !w) return null;
            params.set('year', y);
            params.set('week', w);
        } else if (mode === 'month') {
            const y = val('dl-month-year');
            const m = val('dl-month-num');
            if (!y || !m) return null;
            params.set('year', y);
            params.set('month', m);
        } else if (mode === 'range') {
            const s = val('dl-range-start');
            const e = val('dl-range-end');
            if (!s || !e) return null;
            if (s > e) return null;
            params.set('start', s);
            params.set('end',   e);
        }

        return params;
    }

    /* ── Download ──────────────────────────────────────────────── */
    dlBtn?.addEventListener('click', async () => {
        clearStatus();

        const params = buildParams();
        if (!params) {
            setStatus('Please fill in all required fields.', true);
            return;
        }

        dlBtn.disabled   = true;
        dlBtn.textContent = 'Downloading…';

        try {
            const res = await fetch(`/traceability/api/download-records?${params}`);

            if (!res.ok) {
                const text = await res.text();
                setStatus(`Error: ${text || res.statusText}`, true);
                return;
            }

            const count    = res.headers.get('X-Record-Count') || '?';
            const blob     = await res.blob();
            const url      = URL.createObjectURL(blob);
            const filename = res.headers.get('Content-Disposition')
                ?.match(/filename="([^"]+)"/)?.[1]
                || 'tester_records.csv';

            const a   = document.createElement('a');
            a.href    = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);

            setStatus(`✓ Downloaded ${count} record(s).`);
        } catch (err) {
            setStatus(`Network error: ${err.message}`, true);
        } finally {
            dlBtn.disabled   = false;
            dlBtn.innerHTML  = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download CSV';
        }
    });

    /* ── Seed default values ───────────────────────────────────── */
    (function seedDefaults() {
        const now   = new Date();
        const yyyy  = now.getFullYear();
        const today = now.toISOString().slice(0, 10);

        // Day panel
        const dayEl = document.getElementById('dl-date');
        if (dayEl) dayEl.value = today;

        // Week panel
        const weekYearEl = document.getElementById('dl-week-year');
        const weekNumEl  = document.getElementById('dl-week-num');
        if (weekYearEl) weekYearEl.value = yyyy;
        if (weekNumEl) {
            // ISO week number
            const startOfYear = new Date(yyyy, 0, 1);
            const weekNo      = Math.ceil(((now - startOfYear) / 86400000 + startOfYear.getDay() + 1) / 7);
            weekNumEl.value   = weekNo;
            weekNumEl.max     = 53;
            weekNumEl.min     = 1;
        }

        // Month panel
        const monthYearEl = document.getElementById('dl-month-year');
        const monthNumEl  = document.getElementById('dl-month-num');
        if (monthYearEl) monthYearEl.value = yyyy;
        if (monthNumEl)  monthNumEl.value  = now.getMonth() + 1;

        // Range panel
        const startEl = document.getElementById('dl-range-start');
        const endEl   = document.getElementById('dl-range-end');
        if (startEl) startEl.value = today;
        if (endEl)   endEl.value   = today;
    })();

})();