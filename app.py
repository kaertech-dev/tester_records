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

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.register_blueprint(station_bp)

active_projects  = ActiveProjects()
tester_records   = TesterRecords()
user_auth        = UserAuth()
process_records  = ProcessRecords()

# ─────────────────────────────────────────────
# Landing Page
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('selection_window.html')

# this route directed to tester side
@app.route('/first-window')
def first_window():
    return render_template('first_window.html')

# this route directed to process side
@app.route('/second-window')
def second_window():
    return render_template('second_window.html')

# ─────────────────────────────────────────────
# New Transaction   - te side
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
# ─────────────────────────────────────────────
#               Process Side
# ─────────────────────────────────────────────
@app.route('/process-login', methods=['GET'])
def process_login_page():
    if session.get('pe_user'):
        return redirect(url_for('process_new_transaction'))
    return render_template('process_login.html')


@app.route('/api/process-login', methods=['POST'])
def process_login():
    payload  = request.get_json() or {}
    ke_no    = (payload.get('ke_no') or '').strip()
    password = (payload.get('password') or '').strip()

    if not ke_no or not password:
        return jsonify({'success': False, 'message': 'KE No. and password are required.'}), 400

    try:
        from backend.orm_models import User
        user_data = None
        with get_pe_session() as db:
            user = db.query(User).filter(
                User.employee_num == ke_no,
                User.badge == password
            ).first()
            if user:
                user_data = {
                    'name':         user.name,
                    'employee_num': user.employee_num,
                    'group':        user.group,
                }

        if user_data:
            session['pe_user'] = user_data          # ← persist across refreshes
            return jsonify({'success': True, 'user': user_data})
        return jsonify({'success': False, 'message': 'Invalid KE No. or password.'}), 401

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/process-logout', methods=['POST'])
def process_logout():
    session.pop('pe_user', None)
    return jsonify({'success': True})

@app.route('/process-new-transaction', methods=['GET', 'POST'])
def process_new_transaction():
    # Guard — redirect to login if not authenticated
    if not session.get('pe_user'):
        return redirect(url_for('process_login_page'))
    
    if request.method == 'POST':
        data = {
            'asset_id':            request.form.get('asset_id', '').strip(),
            'asset_name':          request.form.get('asset_name', '').strip(),
            'line_no':             request.form.get('line_no', '').strip(),
            'description':         request.form.get('description', '').strip(),
            'analysis':            request.form.get('analysis', '').strip(),
            'corrective_action':   request.form.get('corrective_action', '').strip(),
            'verification_result': request.form.get('verification_result', '').strip(),
            'equip_down':          request.form.get('equip_down', '').strip(),
            'repair_start':        request.form.get('repair_start', '').strip(),
            'repair_end':          request.form.get('repair_end', '').strip(),
            'troubleshoot_by':     request.form.get('troubleshoot_by', '').strip(),
            'retention_period':    request.form.get('retention_period', '').strip(),
            'effective_date':      request.form.get('effective_date', '').strip(),
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

@app.route('/process-close-transaction')
def process_close_transaction():
    return render_template('process_close_transaction.html')

# ── Process-side API endpoints ────────────────────────────────────────────────

@app.route('/api/process-asset-lookup', methods=['POST'])
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

@app.route('/api/pe-users')
def pe_users_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    try:
        users = process_records.search_pe_users(query)
        return jsonify(users)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/process-submit-data', methods=['POST'])
def process_submit_data():
    data = {
        'asset_id':            request.form.get('asset_id', '').strip(),
        'asset_name':          request.form.get('asset_name', '').strip(),
        'line_no':             request.form.get('line_no', '').strip(),
        'description':         request.form.get('description', '').strip(),
        'analysis':            request.form.get('analysis', '').strip(),
        'corrective_action':   request.form.get('corrective_action', '').strip(),
        'verification_result': request.form.get('verification_result', '').strip(),
        'equip_down':          request.form.get('equip_down', '').strip(),
        'repair_start':        request.form.get('repair_start', '').strip(),
        'repair_end':          request.form.get('repair_end', '').strip(),
        'troubleshoot_by':     request.form.get('troubleshoot_by', '').strip(),
        'retention_period':    request.form.get('retention_period', '').strip(),
        'effective_date':      request.form.get('effective_date', '').strip(),
        'logged_by':           session['pe_user'].get('employee_num', ''),
    }
    try:
        process_records.create_transaction(data)
        return jsonify({'success': True, 'message': 'Transaction saved successfully.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
if __name__ == '__main__':
    try:
        ensure_indexes()
    except Exception:
        pass
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)