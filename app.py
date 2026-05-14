# app.py
from flask import Flask, request, render_template, redirect, url_for, jsonify, session
from backend.new_transaction.connect_db import ensure_indexes
from backend.query import ActiveProjects, TesterRecords, UserAuth
import os
from backend.download_data import download_bp

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.register_blueprint(download_bp)

active_projects = ActiveProjects()
tester_records  = TesterRecords()
user_auth       = UserAuth()

# ─────────────────────────────────────────────
# Landing Page
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('first_window.html')

# ─────────────────────────────────────────────
# New Transaction
# ─────────────────────────────────────────────

@app.route('/new-transaction', methods=['GET', 'POST'])
def new_transaction():
    if request.method == 'POST':
        data = {
            'product':          request.form.get('product'),
            'model':            request.form.get('model'),
            'station':          request.form.get('station'),
            'classification':   request.form.get('classification'),
            'person_in_charge': request.form.get('person_in_charge', '').strip()[:50],
            'fixture_asset_no': request.form.get('fixture_asset_no'),
            'tester_code':      request.form.get('tester_code'),
            'tester_name':      request.form.get('tester_name'),
            'issues':           request.form.get('issues', '').strip(),
        }
        try:
            tester_records.create_transaction(data)
            return redirect(url_for('index'))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    try:
        products = active_projects.get_active_products()
    except Exception:
        products = []

    return render_template('new_transaction.html', products=products)

# ─────────────────────────────────────────────
# Close Transaction
# ─────────────────────────────────────────────

@app.route('/close-transaction')
def close_transaction():
    try:
        open_txns = tester_records.get_open_transactions()
    except Exception:
        open_txns = []
    return render_template('close_transaction.html', transactions=open_txns)


@app.route('/close-transaction/submit', methods=['POST'])
def close_transaction_submit():
    transaction_id = request.form.get('transaction_id')
    if not transaction_id:
        return jsonify({'success': False, 'message': 'No transaction ID provided.'}), 400
    try:
        action_taken = request.form.get('action_taken', '').strip()
        ok, message = tester_records.close_transaction(int(transaction_id), action_taken)
        if ok:
            return jsonify({'success': True, 'message': message})
        return jsonify({'success': False, 'message': message}), 404
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────
# User Authentication (Person in Charge)
# ─────────────────────────────────────────────

@app.route('/api/auth-user', methods=['POST'])
def auth_user():
    payload = request.get_json() or {}
    group    = payload.get('group') or payload.get('email', '')
    password = payload.get('password', '').strip()
    group    = (group or '').strip()
    if not group or not password:
        return jsonify({'success': False, 'message': 'Group and password required.'}), 400
    user = user_auth.authenticate(group, password)
    if user:
        return jsonify({
            'success':      True,
            'name':         user.get('name', group),
            'employee_num': user.get('employee_num')
        })
    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401


# ─────────────────────────────────────────────
# Cascading Dropdown APIs
# ─────────────────────────────────────────────

@app.route('/api/models/<product_id>')
def api_models(product_id):
    try:
        models = active_projects.get_models_by_product(product_id)
        return jsonify(models)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stations/<product_id>/<model_name>')
def api_stations(product_id, model_name):
    try:
        stations = active_projects.get_stations_by_model(product_id, model_name)
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tester-codes')
def api_tester_codes():
    fixture = request.args.get('fixture', '').strip()
    if not fixture:
        return jsonify([])
    try:
        codes = tester_records.get_tester_codes_by_fixture(fixture)
        return jsonify(codes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tester-name')
def api_tester_name():
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'tester_name': ''})
    try:
        name = tester_records.get_tester_name_by_code(code)
        return jsonify({'tester_name': name or ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fixture-lookup', methods=['POST'])
def fixture_lookup():
    body     = request.get_json(force=True)
    asset_no = (body.get('fixture_asset_no') or '').strip()

    if not asset_no:
        return jsonify({'success': False, 'message': 'Fixture asset number is required.'}), 400

    row = tester_records.get_tester_by_fixture(asset_no)

    if not row:
        return jsonify({'success': False, 'message': f'No tester found for fixture "{asset_no}".'}), 404

    return jsonify({
        'success':     True,
        'tester_code': row['tester_code'],
        'tester_name': row['tester_name'],
    })


if __name__ == '__main__':
    try:
        ensure_indexes()
    except Exception:
        pass
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)