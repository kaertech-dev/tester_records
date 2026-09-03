// process_new_transaction.js

// ── Logout ────────────────────────────────────────────────────────────────────
document.getElementById('btn-logout')?.addEventListener('click', async () => {
    await fetch('/traceability/api/logout', { method: 'POST' });
    window.location.href = '/traceability';
});

// ── Asset ID Look Up ──────────────────────────────────────────────────────────
const assetIdInput   = document.getElementById('asset_id');
const assetNameInput = document.getElementById('asset_name');
const btnLookupAsset = document.getElementById('btn-lookup-asset');
const assetStatus    = document.getElementById('asset-status');

function setAssetStatus(message, type) {
    assetStatus.textContent = message;
    assetStatus.className = `status-msg ${type}`;
}

async function lookUpAsset() {
    const assetId = assetIdInput.value.trim();
    if (!assetId) {
        setAssetStatus('Please enter an asset ID first.', 'error');
        return;
    }

    btnLookupAsset.disabled = true;
    btnLookupAsset.textContent = 'Looking…';
    assetNameInput.value = '';
    assetStatus.className = 'status-msg hidden';

    try {
        const res  = await fetch('/traceability/api/process-asset-lookup', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ asset_id: assetId }),
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
            setAssetStatus(data.message || `No asset found for "${assetId}".`, 'error');
            return;
        }

        assetNameInput.value = data.asset_name;
        setAssetStatus(`Found: ${data.asset_name}`, 'success');
    } catch (err) {
        console.error('Asset lookup error:', err);
        setAssetStatus('Could not reach the server. Please try again.', 'error');
    } finally {
        btnLookupAsset.disabled = false;
        btnLookupAsset.textContent = 'Look Up';
    }
}

btnLookupAsset?.addEventListener('click', lookUpAsset);
assetIdInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); lookUpAsset(); }
});


// ── Troubleshoot By (pic) — searchable PE user ────────────────────────────────
const picSearch   = document.getElementById('pic_search');
const picHidden   = document.getElementById('pic');
const picDropdown = document.getElementById('pic-dropdown');
const picStatus   = document.getElementById('pic-status');

let searchTimeout = null;

function setPicStatus(message, type) {
    picStatus.textContent = message;
    picStatus.className = `status-msg ${type}`;
}

function renderDropdown(users) {
    picDropdown.innerHTML = '';

    if (!users || users.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'dropdown-empty';
        empty.textContent = 'No users found.';
        picDropdown.appendChild(empty);
        picDropdown.classList.remove('hidden');
        return;
    }

    users.forEach(u => {
        const item = document.createElement('div');
        item.className = 'dropdown-item';
        item.innerHTML = `
            <span class="di-name">${u.name}</span>
            <span class="di-sub">${u.group} · ${u.employee_num || ''}</span>
        `;
        item.addEventListener('mousedown', (e) => {
            e.preventDefault();
            picSearch.value  = `${u.name} (${u.group})`;
            picHidden.value  = u.employee_num || u.group;
            picDropdown.classList.add('hidden');
            setPicStatus(`Selected: ${u.name}`, 'success');
        });
        picDropdown.appendChild(item);
    });

    picDropdown.classList.remove('hidden');
}

async function searchPeUsers(query) {
    if (!query || query.length < 2) {
        picDropdown.classList.add('hidden');
        return;
    }
    try {
        const res = await fetch(`/api/pe-users?q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error('Search failed');
        const users = await res.json();
        renderDropdown(users);
    } catch (err) {
        console.error('PE user search error:', err);
        picDropdown.classList.add('hidden');
    }
}

picSearch?.addEventListener('input', () => {
    picHidden.value = '';
    picStatus.className = 'status-msg hidden';
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        searchPeUsers(picSearch.value.trim());
    }, 300);
});

picSearch?.addEventListener('blur', () => {
    setTimeout(() => picDropdown.classList.add('hidden'), 200);
});


// ── Multi-Image Upload ────────────────────────────────────────────────────────
class MultiImageUpload {
    constructor(inputId, stripId) {
        this.input = document.getElementById(inputId);
        this.strip = document.getElementById(stripId);
        this.files = [];
        if (!this.input || !this.strip) return;
        this.input.addEventListener('change', () => {
            Array.from(this.input.files).forEach(f => this.files.push(f));
            this._sync();
            this._render();
            this.input.value = '';
        });
    }
    _sync() {
        try {
            const dt = new DataTransfer();
            this.files.forEach(f => dt.items.add(f));
            this.input.files = dt.files;
        } catch (_) {}
    }
    _render() {
        this.strip.innerHTML = '';
        this.files.forEach((file, idx) => {
            const wrap = document.createElement('div');
            wrap.className = 'img-thumb';
            const img = document.createElement('img');
            img.alt = file.name;
            const reader = new FileReader();
            reader.onload = e => { img.src = e.target.result; };
            reader.readAsDataURL(file);
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn-rm';
            btn.textContent = '✕';
            btn.setAttribute('aria-label', `Remove ${file.name}`);
            btn.addEventListener('click', () => this._remove(idx));
            wrap.appendChild(img);
            wrap.appendChild(btn);
            this.strip.appendChild(wrap);
        });
    }
    _remove(idx) {
        this.files.splice(idx, 1);
        this._sync();
        this._render();
    }
    getFiles() { return [...this.files]; }
}

const analysisUpload = new MultiImageUpload('analysis_images_input', 'analysis-strip');


// ── Shared validation ─────────────────────────────────────────────────────────
function validateForm() {
    if (!assetNameInput.value.trim()) {
        setAssetStatus('Please look up a valid asset ID before submitting.', 'error');
        assetIdInput.focus();
        return false;
    }
    if (!picHidden.value.trim()) {
        setPicStatus('Please select a PE user from the search results.', 'error');
        picSearch.focus();
        return false;
    }
    const equipDown    = document.getElementById('equip_down').value;
    const datetimeStart = document.getElementById('datetime_start').value;
    const datetimeEnd   = document.getElementById('datetime_end').value;

    if (equipDown && datetimeStart && datetimeStart < equipDown) {
        alert('Repair Start cannot be before Equipment Down time.');
        return false;
    } 
    if (datetimeStart && datetimeEnd && datetimeEnd < datetimeStart) {
        alert('Repair End cannot be before Repair Start time.');
        return false;
    }
    return true;
}


// ── Download Report (form submit) ─────────────────────────────────────────────
const form            = document.getElementById('process-transaction-form');
const downloadOverlay = document.getElementById('download-overlay');

form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateForm()) return;

    downloadOverlay?.classList.remove('hidden');
    const btnCreate = document.getElementById('btn-create');
    if (btnCreate) btnCreate.disabled = true;

    try {
        const formData = new FormData(form);
        formData.delete('analysis_images');
        analysisUpload.getFiles().forEach(f => formData.append('analysis_images', f));

        const response = await fetch(form.action, {
            method: 'POST',
            body:   formData,
        });

        if (!response.ok) {
            let errMsg = 'Server error generating the report.';
            try { const d = await response.json(); errMsg = d.error || errMsg; } catch (_) {}
            alert(`Error: ${errMsg}`);
            return;
        }

        const blob = await response.blob();
        const url  = URL.createObjectURL(blob);
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";\n]+)"?/);
        const filename = match ? match[1] : 'downtime_report.xlsx';

        const anchor = document.createElement('a');
        anchor.href     = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        setTimeout(() => URL.revokeObjectURL(url), 5000);

    } catch (err) {
        console.error('Download error:', err);
        alert('Could not reach the server. Please try again.');
    } finally {
        downloadOverlay?.classList.add('hidden');
        if (btnCreate) btnCreate.disabled = false;
    }
});


// ── Submit Data ───────────────────────────────────────────────────────────────
const btnSubmitData = document.getElementById('submit-data');

btnSubmitData?.addEventListener('click', async () => {
    if (!validateForm()) return;

    btnSubmitData.disabled = true;
    btnSubmitData.textContent = 'Submitting…';

    try {
        const formData = new FormData(form);

        const response = await fetch('/traceability/api/process-submit-data', {
            method: 'POST',
            body:   formData,
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            alert(`Error: ${result.error || result.message || 'Submission failed.'}`);
            return;
        }

        alert('Transaction submitted successfully!');
        form.reset();
        assetNameInput.value    = '';
        assetStatus.className   = 'status-msg hidden';
        picStatus.className     = 'status-msg hidden';

    } catch (err) {
        console.error('Submit error:', err);
        alert('Could not reach the server. Please try again.');
    } finally {
        btnSubmitData.disabled = false;
        btnSubmitData.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 9 23 4 18 4"/>
                <path d="M23 9L17 3"/>
                <path d="M4 15v4a2 2 0 0 0 2 2h9"/>
                <polyline points="21 15 16 10 5 21"/>
            </svg>
            Submit Data`;
    }
});