// new_transaction.js
const productSelect = document.getElementById('product');
const modelSelect = document.getElementById('model');
const stationSelect = document.getElementById('station');

function clearSelect(select, placeholder) {
    select.innerHTML = '';
    const option = document.createElement('option');
    option.value = '';
    option.disabled = true;
    option.selected = true;
    option.textContent = placeholder;
    select.appendChild(option);
    select.disabled = true;
}

function populateSelect(select, items, placeholder) {
    clearSelect(select, placeholder);
    if (!items || items.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.disabled = true;
        option.textContent = 'No options found';
        select.appendChild(option);
        return;
    }

    items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = item.name;
        select.appendChild(option);
    });
    select.disabled = false;
}

async function fetchModels(schemaName) {
    const response = await fetch(`/traceability/api/models/${encodeURIComponent(schemaName)}`);
    if (!response.ok) throw new Error('Failed to load models');
    return response.json();
}

async function fetchStations(schemaName, modelName) {
    const response = await fetch(`/traceability/api/stations/${encodeURIComponent(schemaName)}/${encodeURIComponent(modelName)}`);
    if (!response.ok) throw new Error('Failed to load stations');
    return response.json();
}

productSelect.addEventListener('change', async () => {
    const schemaName = productSelect.value;
    clearSelect(stationSelect, 'Select model first…');
    if (!schemaName) {
        clearSelect(modelSelect, 'Select product first…');
        return;
    }
    try {
        const models = await fetchModels(schemaName);
        populateSelect(modelSelect, models, 'Select a model/table…');
    } catch (error) {
        populateSelect(modelSelect, []);
        console.error(error);
    }
});

modelSelect.addEventListener('change', async () => {
    const schemaName = productSelect.value;
    const modelName = modelSelect.value;
    if (!schemaName || !modelName) {
        clearSelect(stationSelect, 'Select model first…');
        return;
    }
    try {
        const stations = await fetchStations(schemaName, modelName);
        populateSelect(stationSelect, stations, 'Select a station/field…');
    } catch (error) {
        populateSelect(stationSelect, []);
        console.error(error);
    }
});

// ── Fixture Look Up ──────────────────────────────────────────────────────────
const fixtureInput = document.getElementById('fixture_asset_no');
const btnLookup    = document.getElementById('btn-lookup-fixture');
const testerCodeEl = document.getElementById('tester_code');
const testerNameEl = document.getElementById('tester_name');

async function lookUpFixture() {
    const assetNo = fixtureInput.value.trim();
    if (!assetNo) {
        alert('Please enter a fixture asset number first.');
        return;
    }

    btnLookup.disabled = true;
    btnLookup.textContent = 'Looking…';
    testerCodeEl.value = '';
    testerNameEl.value = '';

    try {
        const res = await fetch('/traceability/api/fixture-lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fixture_asset_no: assetNo })
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
            alert(data.message || 'No tester found for that fixture asset number.');
            return;
        }

        testerCodeEl.value = data.tester_code;
        testerNameEl.value = data.tester_name;
    } catch (err) {
        console.error('Fixture lookup error:', err);
        alert('Could not reach the server. Please try again.');
    } finally {
        btnLookup.disabled = false;
        btnLookup.textContent = 'Look Up';
    }
}

btnLookup?.addEventListener('click', lookUpFixture);

// Trigger lookup on Enter key inside the fixture input
fixtureInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); lookUpFixture(); }
});

// ── Init ─────────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    clearSelect(modelSelect, 'Select product first…');
    clearSelect(stationSelect, 'Select model first…');
});
async function loadClassifications() {
        const select = document.getElementById('classification');
        try {
            const res  = await fetch('/traceability/api/classifications');
            const data = await res.json();
            select.innerHTML = '<option value="" disabled selected>Select a classification…</option>';
            data.forEach(c => {
                const opt   = document.createElement('option');
                opt.value   = c;
                opt.textContent = c;
                select.appendChild(opt);
            });
        } catch (err) {
            console.error('Failed to load classifications:', err);
            select.innerHTML = '<option value="" disabled selected>Failed to load…</option>';
        }
    }

    window.addEventListener('DOMContentLoaded', () => {
        clearSelect(modelSelect, 'Select product first…');
        clearSelect(stationSelect, 'Select model first…');
        loadClassifications();  // ← add this
    });