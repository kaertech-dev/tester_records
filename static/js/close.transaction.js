// close_transaction.js

(function () {
    'use strict';
    
    // ── Element refs ─────────────────────────────────────────────
    const searchInput     = document.getElementById('search-input');
    const modalOverlay    = document.getElementById('modal-overlay');
    const btnCancelModal  = document.getElementById('btn-cancel-modal');
    const btnConfirm      = document.getElementById('btn-confirm-close');
    const modalMessage    = document.getElementById('modal-message');

    // Summary spans inside the modal
    const sumId           = document.getElementById('sum-id');
    const sumTesterCode   = document.getElementById('sum-tester-code');
    const sumTesterName   = document.getElementById('sum-tester-name');
    const sumClass        = document.getElementById('sum-classification');
    const sumDueDate      = document.getElementById('sum-due-date');
    const sumDatetimeStart = document.getElementById('sum-datetime-start');
    const sumPic          = document.getElementById('sum-pic');
    const sumIssues       = document.getElementById('sum-issues');
    const sumActionTaken  = document.getElementById('sum-action-taken');

    // Track which transaction is being confirmed
    let activeTransactionId = null;
    let activeRow           = null;

    // ── Live search / filter ──────────────────────────────────────
    searchInput?.addEventListener('input', function () {
        const query = this.value.toLowerCase().trim();
        document.querySelectorAll('.txn-row').forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
    });

    // ── Open modal when a Close button is clicked ─────────────────
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.btn-close-txn');
        if (!btn) return;

        const row = btn.closest('.txn-row');
        if (!row) return;

        activeTransactionId = row.dataset.id;
        activeRow           = row;

        // Populate summary modal from data attributes (all match actual DB columns)
        sumId.textContent           = row.dataset.id             || '—';
        sumTesterCode.textContent   = row.dataset.testerCode     || '—';
        sumTesterName.textContent   = row.dataset.testerName     || '—';
        sumClass.textContent        = row.dataset.classification  || '—';
        sumDueDate.textContent      = row.dataset.dueDate        || '—';
        sumDatetimeStart.textContent = row.dataset.datetimeStart || '—';
        sumPic.textContent          = row.dataset.pic            || '—';
        sumActionTaken.textContent  = row.dataset.actionTaken    || '—';

        // Issues badge styling
        const hasIssues = row.dataset.issues === 'Yes';
        sumIssues.textContent = hasIssues ? '⚠ Yes' : '✔ No';
        sumIssues.className   = 'summary-value';
        sumIssues.style.color = hasIssues ? '#633806' : '#27500A';

        // Reset message and button state
        hideMessage();
        btnConfirm.disabled = false;
        btnConfirm.textContent = '✔ Confirm & Submit';

        // Show modal
        modalOverlay.classList.remove('hidden');
    });

    // ── Cancel — close modal ──────────────────────────────────────
    btnCancelModal?.addEventListener('click', closeModal);

    // Close modal when clicking the dark overlay background
    modalOverlay?.addEventListener('click', function (e) {
        if (e.target === modalOverlay) closeModal();
    });

    // Close modal on Escape key
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modalOverlay.classList.contains('hidden')) {
            closeModal();
        }
    });

    function closeModal() {
        modalOverlay.classList.add('hidden');
        activeTransactionId = null;
        activeRow           = null;
        hideMessage();
        btnConfirm.disabled = false;
        btnConfirm.textContent = '✔ Confirm & Submit';
        const inputActionTaken = document.getElementById('input-action-taken');
        if (inputActionTaken) inputActionTaken.value = '';
    }

    // ── Confirm & Submit ──────────────────────────────────────────
    btnConfirm?.addEventListener('click', async function () {
        if (!activeTransactionId) return;

        const actionTaken = document.getElementById('input-action-taken')?.value.trim() ?? '';
        
        btnConfirm.disabled = true;
        btnConfirm.textContent = 'Submitting…';
        hideMessage();

        try {
            const response = await fetch('/close-transaction/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `transaction_id=${encodeURIComponent(activeTransactionId)}&action_taken=${encodeURIComponent(actionTaken)}`
            });

            const result = await response.json();

            if (response.ok && result.success) {
                showMessage(result.message || 'Transaction closed successfully.', 'success');

                // Fade out and remove the row from the table after a short delay
                if (activeRow) {
                    activeRow.style.transition = 'opacity 0.4s ease';
                    activeRow.style.opacity = '0';
                    setTimeout(() => {
                        activeRow.remove();
                        checkEmptyTable();
                    }, 400);
                }

                // Auto-close modal after showing success
                setTimeout(closeModal, 1200);
            } else {
                showMessage(result.message || 'Failed to close transaction.', 'error');
                btnConfirm.disabled = false;
                btnConfirm.textContent = '✔ Confirm & Submit';
            }
        } catch (err) {
            console.error('[close_transaction] Submit error:', err);
            showMessage('Network error — please try again.', 'error');
            btnConfirm.disabled = false;
            btnConfirm.textContent = '✔ Confirm & Submit';
        }
    });

    // ── Helpers ───────────────────────────────────────────────────

    function showMessage(text, type) {
        modalMessage.textContent = text;
        modalMessage.classList.remove('hidden');
        if (type === 'success') {
            modalMessage.style.background = '#EAF3DE';
            modalMessage.style.color      = '#27500A';
        } else {
            modalMessage.style.background = '#FCEBEB';
            modalMessage.style.color      = '#791F1F';
        }
    }

    function hideMessage() {
        modalMessage.classList.add('hidden');
        modalMessage.textContent = '';
    }

    /**
     * If all rows have been closed, replace the table with the empty-state
     * block so the user sees the correct "no open transactions" message.
     */
    function checkEmptyTable() {
        const remaining = document.querySelectorAll('.txn-row');
        if (remaining.length === 0) {
            const tableWrap = document.querySelector('.table-wrap');
            if (tableWrap) {
                tableWrap.innerHTML = `
                    <div class="empty-state">
                        <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                            <circle cx="32" cy="32" r="32" fill="#f0fdf4"/>
                            <path d="M22 32h20M22 24h20M22 40h14" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round"/>
                        </svg>
                        <p>No open transactions found.</p>
                        <a href="/new-transaction" class="btn-new">Create a New Transaction</a>
                    </div>`;
            }
        }
    }

})();