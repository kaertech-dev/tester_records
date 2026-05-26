# main.py
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from functools import wraps
import secrets
from database import Database

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)   # Change to a fixed value in production
db = Database()

ADMINS = {'KE0412', 'KE0030'}


# ── Auth decorators ───────────────────────────────────────────────────────────

def login_required(f):
    """Redirect to /login if the user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Return 403 if the logged-in user is not an admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        if session.get('employee_num') not in ADMINS:
            return jsonify({'success': False, 'message': 'Access denied.'}), 403
        return f(*args, **kwargs)
    return decorated


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route('/login')
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/')
@login_required
def index():
    return render_template('signin_user.html')


@app.route('/admin/users')
@admin_required
def manage_users_page():
    return render_template(
        'manage_users.html',
        session_user=session.get('employee_num', '')
    )


# ── API: Login ────────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
def api_login():
    data         = request.get_json()
    employee_num = data.get('employee_num', '').strip()
    badge        = data.get('badge', '').strip()

    if not employee_num or not badge:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    try:
        row = db.verify_user(employee_num, badge)
        if row:
            session['logged_in']    = True
            session['employee_num'] = row['employee_num']
            is_admin  = row['employee_num'] in ADMINS
            redirect_url = '/admin/users' if is_admin else '/'
            return jsonify({'success': True, 'message': 'Login successful.', 'redirect': redirect_url})
        return jsonify({'success': False, 'message': 'Invalid employee number or badge.'}), 401
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


# ── API: Logout ───────────────────────────────────────────────────────────────

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out.'})


# ── API: Register new operator ────────────────────────────────────────────────

@app.route('/api/signin', methods=['POST'])
@login_required
def signin_new_user():
    data = request.get_json()

    operator_en   = data.get('operator_en', '').strip()
    employee_name = data.get('employee_name', '').strip()
    date_hired    = data.get('date_hired', '').strip()
    status        = data.get('status', '').strip()
    contact       = data.get('contact', '').strip()
    process       = data.get('process', '').strip()

    if not all([operator_en, employee_name, date_hired, status, contact, process]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    success = db.signin_new_user(operator_en, employee_name,
                                  date_hired, status, contact, process)
    if success:
        return jsonify({'success': True, 'message': 'New operator registered successfully!'})
    return jsonify({'success': False, 'message': 'Database error. Please try again.'}), 500


# ── API: Admin — list users ───────────────────────────────────────────────────

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_list_users():
    try:
        users = db.get_all_users()
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ── API: Admin — add user ─────────────────────────────────────────────────────

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def api_add_user():
    data          = request.get_json()
    employee_num  = data.get('employee_num', '').strip()
    employee_name = data.get('employee_name', '').strip()
    badge         = data.get('badge', '').strip()

    if not all([employee_num, employee_name, badge]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    result = db.add_user(employee_num, employee_name, badge)
    if result == 'duplicate':
        return jsonify({'success': False, 'message': f'{employee_num} already exists.'}), 409
    if result:
        return jsonify({'success': True, 'message': 'User added successfully.'})
    return jsonify({'success': False, 'message': 'Database error.'}), 500


# ── API: Admin — delete user ──────────────────────────────────────────────────

@app.route('/api/admin/users/<employee_num>', methods=['DELETE'])
@admin_required
def api_delete_user(employee_num):
    if employee_num in ADMINS:
        return jsonify({'success': False, 'message': 'Cannot remove an admin account.'}), 403

    success = db.delete_user(employee_num)
    if success:
        return jsonify({'success': True, 'message': 'User removed.'})
    return jsonify({'success': False, 'message': 'User not found or database error.'}), 500

@app.route('/api/me')
@login_required
def api_me():
    emp = session.get('employee_num', '')
    return jsonify({'employee_num': emp, 'is_admin': emp in ADMINS})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)