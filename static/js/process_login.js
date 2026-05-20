// process_login.js
const btnLogin      = document.getElementById('btn-login');
const loginKeNo     = document.getElementById('login-ke-no');
const loginPassword = document.getElementById('login-password');
const loginError    = document.getElementById('login-error');

function setLoginError(msg) {
    loginError.textContent = msg;
    loginError.className = 'status-msg error';
}

async function attemptLogin() {
    const keNo     = loginKeNo.value.trim();
    const password = loginPassword.value.trim();

    if (!keNo || !password) {
        setLoginError('Please enter both KE No. and password.');
        return;
    }

    btnLogin.disabled    = true;
    btnLogin.textContent = 'Signing in…';
    loginError.className = 'status-msg hidden';

    try {
        const res  = await fetch('/api/process-login', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ ke_no: keNo, password }),
        });
        const data = await res.json();

        if (!res.ok || !data.success) {
            setLoginError(data.message || 'Invalid credentials.');
            return;
        }

        // Redirect to the transaction form — session is set server-side
        window.location.href = '/process-new-transaction';

    } catch (err) {
        console.error('Login error:', err);
        setLoginError('Could not reach the server. Please try again.');
    } finally {
        btnLogin.disabled    = false;
        btnLogin.textContent = 'Sign In';
    }
}

btnLogin?.addEventListener('click', attemptLogin);
loginPassword?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') attemptLogin();
});