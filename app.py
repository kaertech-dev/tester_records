# app.py
from flask import Flask, request, render_template, redirect, url_for, jsonify, session, send_file
from backend.new_transaction.connect_db import ensure_indexes
from backend.query import ActiveProjects, TesterRecords, UserAuth, ProcessRecords
from backend.database import get_te_session, get_pe_session
from backend.excel_form import build_downtime_report
import io
import os
from backend.download_data import download_bp
from backend.download_station_data import station_bp
import requests as http_requests

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.register_blueprint(station_bp)
app.register_blueprint(download_bp)

active_projects  = ActiveProjects()
tester_records   = TesterRecords()
user_auth        = UserAuth()
process_records  = ProcessRecords()

# ─────────────────────────────────────────────
# Landing Page
# ─────────────────────────────────────────────

@app.route('/traceability')
def index():
    # If already logged in, send straight to the right window
    if session.get('system_type') == 'te':
        return redirect(url_for('test_window'))
    if session.get('system_type') == 'pe':
        return redirect(url_for('process_window'))
    return render_template('selection_window.html')

# this route directed to tester side
@app.route('/traceability/first-window')
def test_window():
    if session.get('system_type') != 'te':
        return redirect(url_for('index'))
    return render_template('test_window.html')

# # this route directed to process side
@app.route('/traceability/second-window')
def process_window():
    if session.get('system_type') != 'pe':
        return redirect(url_for('index'))
    return render_template('process_window.html')

# ─────────────────────────────────────────────
# Unified Login / Logout
# ─────────────────────────────────────────────

@app.route('/traceability/api/login', methods=['POST'])
def api_login():
    payload      = request.get_json() or {}
    employee_num = (payload.get('employee_num') or '').strip()
    password     = (payload.get('password') or payload.get('badge') or '').strip()

    if not employee_num or not password:
        return jsonify({'success': False, 'message': 'Employee number and password/badge are required.'}), 400

    # Try TE first
    te_user = user_auth.authenticate(employee_num, password)
    if te_user:
        session['system_type'] = 'te'
        session['te_user'] = {
            'name':         te_user.get('name', employee_num),
            'employee_num': te_user.get('employee_num'),
            'group':        te_user.get('group', employee_num),
        }
        session.pop('pe_user', None)
        return jsonify({'success': True, 'redirect': url_for('test_window')})

    # Try PE — use UserAuth (bcrypt-aware) against the PE session
    pe_user_data = user_auth.authenticate_with_session(employee_num, password, get_pe_session)
    if pe_user_data:
        session['system_type'] = 'pe'
        session['pe_user'] = pe_user_data
        session.pop('te_user', None)
        return jsonify({'success': True, 'redirect': url_for('process_window')})

    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401

@app.route('/traceability/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True, 'redirect': url_for('index')})

# ─────────────────────────────────────────────
# New Transaction   - te side
# ─────────────────────────────────────────────

@app.route('/traceability/new-transaction', methods=['GET', 'POST'])
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
    # Pass the logged-in user to the template
    te_user = session.get('te_user', {})
    return render_template('new_transaction.html', products=products, te_user=te_user)

# ─────────────────────────────────────────────
# Close Transaction
# ─────────────────────────────────────────────

@app.route('/traceability/close-transaction')
def close_transaction():
    try:
        open_txns = tester_records.get_open_transactions()
    except Exception:
        open_txns = []
    return render_template('close_transaction.html', transactions=open_txns)


@app.route('/traceability/close-transaction/submit', methods=['POST'])
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

@app.route('/traceability/api/auth-user', methods=['POST'])
def auth_user():
    payload = request.get_json() or {}
    identity = (payload.get('employee_num') or payload.get('group') or payload.get('email') or '').strip()
    password = (payload.get('password') or '').strip()
    if not identity or not password:
        return jsonify({'success': False, 'message': 'Employee number/group and password are required.'}), 400
    user = user_auth.authenticate(identity, password)
    if user:
        return jsonify({
            'success':      True,
            'name':         user.get('name', identity),
            'employee_num': user.get('employee_num')
        })
    return jsonify({'success': False, 'message': 'Invalid credentials.'}), 401

# ─────────────────────────────────────────────
# Change Password
# ─────────────────────────────────────────────

@app.route('/traceability/change-password')
def change_password_page():
    te_user = session.get('te_user')
    pe_user = session.get('pe_user')
    if not te_user and not pe_user:
        return redirect(url_for('index'))
    current_user = te_user or pe_user
    system = 'te' if te_user else 'pe'
    return render_template('change_password.html', current_user=current_user, system=system)


@app.route('/traceability/change-password', methods=['POST'])
def api_change_password():
    te_user = session.get('te_user')
    pe_user = session.get('pe_user')
    if not te_user and not pe_user:
        return jsonify({'success': False, 'message': 'Not logged in.'}), 401

    payload      = request.get_json() or {}
    old_password = (payload.get('old_password') or '').strip()
    new_password = (payload.get('new_password') or '').strip()
    confirm      = (payload.get('confirm_password') or '').strip()

    if not old_password or not new_password or not confirm:
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    if new_password != confirm:
        return jsonify({'success': False, 'message': 'New passwords do not match.'}), 400

    if te_user:
        identity = te_user['employee_num']
        ok, msg = user_auth.change_password(identity, old_password, new_password,
                                             db_session_fn=get_te_session)
    else:
        identity = pe_user['employee_num']
        ok, msg = user_auth.change_password(identity, old_password, new_password,
                                             db_session_fn=get_pe_session)

    return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)

# ─────────────────────────────────────────────
# Cascading Dropdown APIs
# ─────────────────────────────────────────────

@app.route('/traceability/api/models/<product_id>')
def api_models(product_id):
    try:
        models = active_projects.get_models_by_product(product_id)
        return jsonify(models)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/traceability/api/stations/<product_id>/<model_name>')
def api_stations(product_id, model_name):
    try:
        stations = active_projects.get_stations_by_model(product_id, model_name)
        return jsonify(stations)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/traceability/api/tester-codes')
def api_tester_codes():
    fixture = request.args.get('fixture', '').strip()
    if not fixture:
        return jsonify([])
    try:
        codes = tester_records.get_tester_codes_by_fixture(fixture)
        return jsonify(codes)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/traceability/api/tester-name')
def api_tester_name():
    code = request.args.get('code', '').strip()
    if not code:
        return jsonify({'tester_name': ''})
    try:
        name = tester_records.get_tester_name_by_code(code)
        return jsonify({'tester_name': name or ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/traceability/api/fixture-lookup', methods=['POST'])
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
# ─────────────────────────────────────────────
#               Process Side
# ─────────────────────────────────────────────
@app.route('/traceability/process-login', methods=['GET'])
def process_login_page():
    if session.get('pe_user'):
        return redirect(url_for('process_new_transaction'))
    return render_template('process_login.html')


@app.route('/traceability/api/process-login', methods=['POST'])
def process_login():
    payload  = request.get_json() or {}
    ke_no    = (payload.get('ke_no') or '').strip()
    password = (payload.get('password') or '').strip()

    if not ke_no or not password:
        return jsonify({'success': False, 'message': 'KE No. and password are required.'}), 400

    pe_user_data = user_auth.authenticate_with_session(ke_no, password, get_pe_session)
    if pe_user_data:
        session['pe_user'] = pe_user_data
        return jsonify({'success': True, 'user': pe_user_data})

    return jsonify({'success': False, 'message': 'Invalid KE No. or password.'}), 401

@app.route('/traceability/api/process-logout', methods=['POST'])
def process_logout():
    session.pop('pe_user', None)
    return jsonify({'success': True})

@app.route('/traceability/process-new-transaction', methods=['GET', 'POST'])
def process_new_transaction():
    # Guard — redirect to login if not authenticated
    if not session.get('pe_user'):
        return redirect(url_for('process_login_page'))
    
    if request.method == 'POST':
        data = {
            'asset_id':            request.form.get('asset_id', '').strip(),
            'asset_name':          request.form.get('asset_name', '').strip(),
            'line_no':             request.form.get('line_no', '').strip(),
            'classification':         request.form.get('classification', '').strip(),
            'equip_down':          request.form.get('equip_down', '').strip(),
            'datetime_start':        request.form.get('datetime_start', '').strip(),
            'datetime_end':          request.form.get('datetime_end', '').strip(),
            'description':    request.form.get('description', '').strip(),
            'action_taken':   request.form.get('action_taken', '').strip(),
            'remarks': request.form.get('remarks', '').strip(),
            'pic':     request.form.get('pic', '').strip(),
            'logged_by':           session['pe_user'].get('employee_num', ''),
        }

        # Read optional image uploads (kept in memory only — never saved to disk)
        # NEW — multi-image reader
        def _read_images(field_name: str) -> list[bytes]:
            files = request.files.getlist(field_name)
            return [f.read() for f in files if f and f.filename]

        analysis_imgs          = _read_images('analysis_images')
        corrective_action_imgs = _read_images('corrective_action_images')
        verification_imgs      = _read_images('verification_images')

        try:
            xlsx_bytes = build_downtime_report(
                data,
                analysis_imgs=analysis_imgs,
                corrective_action_imgs=corrective_action_imgs,
                verification_imgs=verification_imgs,
            )
        except Exception as e:
            return jsonify({'error': f'Excel generation failed: {str(e)}'}), 500

        asset_id_safe = data['asset_id'].replace('/', '-').replace('\\', '-') or 'report'
        filename = f"downtime_report_{asset_id_safe}.xlsx"

        return send_file(
            io.BytesIO(xlsx_bytes),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename,
        )

    return render_template('process_new_transaction.html')

@app.route('/traceability/process-close-transaction')
def process_close_transaction():
    return render_template('process_close_transaction.html')

# ── Process-side API endpoints ────────────────────────────────────────────────

@app.route('/traceability/api/process-asset-lookup', methods=['POST'])
def process_asset_lookup():
    body     = request.get_json(force=True)
    asset_id = (body.get('asset_id') or '').strip()

    if not asset_id:
        return jsonify({'success': False, 'message': 'Asset ID is required.'}), 400
    try:
        row = process_records.get_asset_by_id(asset_id)
    except Exception as e:
        print(f"[process_asset_lookup] Unhandled exception: {e}")
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

    if not row:
        return jsonify({'success': False, 'message': f'No asset found for "{asset_id}".'}), 404

    return jsonify({
        'success':    True,
        'asset_id':   row['asset_id'],
        'asset_name': row['asset_name'],
    })
 
@app.route('/traceability/api/pe-users')
def pe_users_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    try:
        users = process_records.search_pe_users(query)
        return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/traceability/api/process-submit-data', methods=['POST'])
def process_submit_data():
    data = {
            'asset_id':            request.form.get('asset_id', '').strip(),
            'asset_name':          request.form.get('asset_name', '').strip(),
            'line_no':             request.form.get('line_no', '').strip(),
            'classification':         request.form.get('classification', '').strip(),
            'equip_down':          request.form.get('equip_down', '').strip(),
            'datetime_start':        request.form.get('datetime_start', '').strip(),
            'datetime_end':          request.form.get('datetime_end', '').strip(),
            'description':    request.form.get('description', '').strip(),
            'action_taken':   request.form.get('action_taken', '').strip(),
            'remarks': request.form.get('remarks', '').strip(),
            'pic':     request.form.get('pic', '').strip(),
            'logged_by':           session['pe_user'].get('employee_num', ''),
        }
    try:
        process_records.create_transaction(data)
        return jsonify({'success': True, 'message': 'Transaction saved successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/traceability/api/ai-summarize', methods=['POST'])
def ai_summarize():
    body    = request.get_json(force=True) or {}
    api_key = (body.get('api_key') or '').strip()
    prompt  = (body.get('prompt')  or '').strip()

    if not api_key:
        return jsonify({'error': 'API key is required.'}), 400
    if not prompt:
        return jsonify({'error': 'Prompt is required.'}), 400

    # Safety: truncate if prompt is extremely large (~180k chars ≈ ~50k tokens)
    MAX_CHARS = 180_000
    if len(prompt) > MAX_CHARS:
        prompt = prompt[:MAX_CHARS] + '\n\n[... data truncated due to size ...]'

    try:
        res = http_requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'Content-Type':      'application/json',
                'x-api-key':         api_key,
                'anthropic-version': '2023-06-01',
            },
            json={
                'model':      'claude-sonnet-4-20250514',
                'max_tokens': 2048,
                'messages':   [{'role': 'user', 'content': prompt}],
            },
            timeout=120,
        )
        data = res.json()

        # Bubble up Anthropic's own error message clearly
        if not res.ok:
            err_msg = data.get('error', {}).get('message', res.text)
            return jsonify({'error': err_msg}), res.status_code

        return jsonify(data), res.status_code

    except http_requests.exceptions.Timeout:
        return jsonify({'error': 'Request timed out — try a smaller date range.'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/traceability/api/classifications')
def api_classifications():
    try:
        classifications = tester_records.get_classifications()
        return jsonify(classifications)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
if __name__ == '__main__':
    try:
        ensure_indexes()
    except Exception:
        pass
    app.run(host='0.0.0.0', port=5050, debug=True, use_reloader=False)