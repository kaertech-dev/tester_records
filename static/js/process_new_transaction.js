// process_new_transaction.js
// ── Login Gate ────────────────────────────────────────────────────────────────
// const loginGate      = document.getElementById('login-gate');
// const mainFormArea   = document.getElementById('main-form-area');
// const btnLogin       = document.getElementById('btn-login');
// const loginKeNo      = document.getElementById('login-ke-no');
// const loginPassword  = document.getElementById('login-password');
// const loginError     = document.getElementById('login-error');

// function setLoginError(msg) {
//     loginError.textContent = msg;
//     loginError.className = 'status-msg error';
// }

// async function attemptLogin() {
//     const keNo     = loginKeNo.value.trim();
//     const password = loginPassword.value.trim();

//     if (!keNo || !password) {
//         setLoginError('Please enter both KE No. and password.');
//         return;
//     }

//     btnLogin.disabled = true;
//     btnLogin.textContent = 'Signing in…';
//     loginError.className = 'status-msg hidden';

//     try {
//         const res  = await fetch('/api/process-login', {
//             method:  'POST',
//             headers: { 'Content-Type': 'application/json' },
//             body:    JSON.stringify({ ke_no: keNo, password }),
//         });
//         const data = await res.json();

//         if (!res.ok || !data.success) {
//             setLoginError(data.message || 'Invalid credentials.');
//             return;
//         }

//         // Unlock the form
//         loginGate.style.display    = 'none';
//         mainFormArea.style.display = 'block';

//     } catch (err) {
//         console.error('Login error:', err);
//         setLoginError('Could not reach the server. Please try again.');
//     } finally {
//         btnLogin.disabled    = false;
//         btnLogin.textContent = 'Sign In';
//     }
// }

// btnLogin?.addEventListener('click', attemptLogin);
// loginPassword?.addEventListener('keydown', (e) => {
//     if (e.key === 'Enter') attemptLogin();
// });
// Show logged-in user name passed via session (optional)
document.getElementById('btn-logout')?.addEventListener('click', async () => {
    await fetch('/api/process-logout', { method: 'POST' });
    window.location.href = '/process-login';
});

// ── Asset ID Look Up ──────────────────────────────────────────────────────────
const assetIdInput = document.getElementById('asset_id');
const assetNameInput = document.getElementById('asset_name');
const btnLookupAsset = document.getElementById('btn-lookup-asset');
const assetStatus = document.getElementById('asset-status');

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
        const res = await fetch('/api/process-asset-lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ asset_id: assetId })
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


// ── Troubleshoot By — searchable PE user ──────────────────────────────────────
const troubleshootSearch = document.getElementById('troubleshoot_search');
const troubleshootHidden = document.getElementById('troubleshoot_by');
const troubleshootDropdown = document.getElementById('troubleshoot-dropdown');
const troubleshootStatus = document.getElementById('troubleshoot-status');

let searchTimeout = null;

function setTroubleshootStatus(message, type) {
    troubleshootStatus.textContent = message;
    troubleshootStatus.className = `status-msg ${type}`;
}

function renderDropdown(users) {
    troubleshootDropdown.innerHTML = '';

    if (!users || users.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'dropdown-empty';
        empty.textContent = 'No users found.';
        troubleshootDropdown.appendChild(empty);
        troubleshootDropdown.classList.remove('hidden');
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
            troubleshootSearch.value = `${u.name} (${u.group})`;
            troubleshootHidden.value = u.employee_num || u.group;
            troubleshootDropdown.classList.add('hidden');
            setTroubleshootStatus(`Selected: ${u.name}`, 'success');
        });
        troubleshootDropdown.appendChild(item);
    });

    troubleshootDropdown.classList.remove('hidden');
}

async function searchPeUsers(query) {
    if (!query || query.length < 2) {
        troubleshootDropdown.classList.add('hidden');
        return;
    }

    try {
        const res = await fetch(`/api/pe-users?q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error('Search failed');
        const users = await res.json();
        renderDropdown(users);
    } catch (err) {
        console.error('PE user search error:', err);
        troubleshootDropdown.classList.add('hidden');
    }
}

troubleshootSearch?.addEventListener('input', () => {
    troubleshootHidden.value = '';
    troubleshootStatus.className = 'status-msg hidden';
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        searchPeUsers(troubleshootSearch.value.trim());
    }, 300);
});

troubleshootSearch?.addEventListener('blur', () => {
    setTimeout(() => troubleshootDropdown.classList.add('hidden'), 200);
});


// ── Multi-Image Upload ────────────────────────────────────────────────────────
/**
 * MultiImageUpload
 *
 * Manages an ordered list of File objects for one upload zone.
 * When files are added or removed it re-syncs a DataTransfer into the real
 * <input type="file" multiple> so the multipart POST picks them up natively.
 *
 * @param {string} inputId   – id of the hidden <input type="file" multiple>
 * @param {string} stripId   – id of the thumbnail strip container
 */
class MultiImageUpload {
    constructor(inputId, stripId) {
        this.input = document.getElementById(inputId);
        this.strip = document.getElementById(stripId);
        this.files = [];   // ordered array of File objects

        if (!this.input || !this.strip) return;

        // When user picks files from the OS dialog, APPEND them (don't replace)
        this.input.addEventListener('change', () => {
            const chosen = Array.from(this.input.files);
            chosen.forEach(f => this.files.push(f));
            this._sync();
            this._render();
            // Reset the real input so picking the same file again still fires 'change'
            this.input.value = '';
        });
    }

    // Write this.files back into the input via DataTransfer
    _sync() {
        try {
            const dt = new DataTransfer();
            this.files.forEach(f => dt.items.add(f));
            this.input.files = dt.files;
        } catch (_) {
            // DataTransfer not available in very old browsers — silently ignore;
            // FormData below will still work because we pass files explicitly.
        }
    }

    // Rebuild the thumbnail strip
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

    /** Returns a plain array of File objects (used when building FormData) */
    getFiles() { return [...this.files]; }
}

// Instantiate for each section
const analysisUpload = new MultiImageUpload('analysis_images_input', 'analysis-strip');
const correctiveUpload = new MultiImageUpload('corrective_images_input', 'corrective-strip');
const verificationUpload = new MultiImageUpload('verification_images_input', 'verification-strip');


// ── Form submission — fetch + blob download ───────────────────────────────────
const form = document.getElementById('process-transaction-form');
const downloadOverlay = document.getElementById('download-overlay');

form?.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Validate asset lookup
    if (!assetNameInput.value.trim()) {
        setAssetStatus('Please look up a valid asset ID before submitting.', 'error');
        assetIdInput.focus();
        return;
    }

    // Validate troubleshoot user selection
    if (!troubleshootHidden.value.trim()) {
        setTroubleshootStatus('Please select a PE user from the search results.', 'error');
        troubleshootSearch.focus();
        return;
    }

    // Validate repair time order
    const equipDown = document.getElementById('equip_down').value;
    const repairStart = document.getElementById('repair_start').value;
    const repairEnd = document.getElementById('repair_end').value;

    if (equipDown && repairStart && repairStart < equipDown) {
        alert('Repair Start cannot be before Equipment Down time.');
        return;
    }
    if (repairStart && repairEnd && repairEnd < repairStart) {
        alert('Repair End cannot be before Repair Start time.');
        return;
    }

    // Show loading overlay
    downloadOverlay?.classList.remove('hidden');
    const btnCreate = document.getElementById('btn-create');
    if (btnCreate) { btnCreate.disabled = true; }

    try {
        // Build FormData from the form, then manually append multi-image files
        // (needed in case DataTransfer sync isn't supported by the browser)
        const formData = new FormData(form);

        // Remove any auto-included file inputs (they may be empty or partial)
        formData.delete('analysis_images');
        formData.delete('corrective_action_images');
        formData.delete('verification_images');

        // Re-append from our managed arrays
        analysisUpload.getFiles().forEach(f => formData.append('analysis_images', f));
        correctiveUpload.getFiles().forEach(f => formData.append('corrective_action_images', f));
        verificationUpload.getFiles().forEach(f => formData.append('verification_images', f));

        const response = await fetch(form.action, {
            method: 'POST',
            body: formData,
            // Do NOT set Content-Type — browser sets it with the correct boundary
        });

        if (!response.ok) {
            let errMsg = 'Server error generating the report.';
            try {
                const errData = await response.json();
                errMsg = errData.error || errMsg;
            } catch (_) { /* ignore parse errors */ }
            alert(`Error: ${errMsg}`);
            return;
        }

        // Receive the xlsx blob and auto-download it
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);

        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename="?([^";\n]+)"?/);
        const filename = match ? match[1] : 'downtime_report.xlsx';

        const anchor = document.createElement('a');
        anchor.href = url;
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
        if (btnCreate) { btnCreate.disabled = false; }
    }
});

// ── Submit Data button ────────────────────────────────────────────────────────
const btnSubmitData = document.getElementById('submit-data');

btnSubmitData?.addEventListener('click', async () => {

    // Same validation as the download flow
    if (!assetNameInput.value.trim()) {
        setAssetStatus('Please look up a valid asset ID before submitting.', 'error');
        assetIdInput.focus();
        return;
    }
    if (!troubleshootHidden.value.trim()) {
        setTroubleshootStatus('Please select a PE user from the search results.', 'error');
        troubleshootSearch.focus();
        return;
    }

    const equipDown   = document.getElementById('equip_down').value;
    const repairStart = document.getElementById('repair_start').value;
    const repairEnd   = document.getElementById('repair_end').value;

    if (equipDown && repairStart && repairStart < equipDown) {
        alert('Repair Start cannot be before Equipment Down time.');
        return;
    }
    if (repairStart && repairEnd && repairEnd < repairStart) {
        alert('Repair End cannot be before Repair Start time.');
        return;
    }

    btnSubmitData.disabled = true;
    btnSubmitData.textContent = 'Submitting…';

    try {
        const formData = new FormData(form);

        const response = await fetch('/api/process-submit-data', {
            method: 'POST',
            body: formData,
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            alert(`Error: ${result.error || result.message || 'Submission failed.'}`);
            return;
        }

        alert('Transaction submitted successfully!');
        form.reset();
        assetNameInput.value = '';
        assetStatus.className = 'status-msg hidden';
        troubleshootStatus.className = 'status-msg hidden';

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