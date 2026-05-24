from flask import Flask, request, jsonify, render_template
import pymysql

app = Flask(__name__)

DB_CONFIG = {
    'host': '192.168.1.38',
    'port': 3306,
    'user': 'testing',
    'password': 'testing',
    'db': 'operators',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


def get_connection():
    return pymysql.connect(**DB_CONFIG)


@app.route('/')
def index():
    return render_template('signin_user.html')


@app.route('/api/signin', methods=['POST'])
def signin_new_user():
    data = request.get_json()

    operator_en    = data.get('operator_en', '').strip()
    employee_name  = data.get('employee_name', '').strip()
    date_hired     = data.get('date_hired', '').strip()
    status         = data.get('status', '').strip()
    contact        = data.get('contact', '').strip()
    process        = data.get('process', '').strip()

    # Basic validation
    if not all([operator_en, employee_name, date_hired, status, contact, process]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO main
                    (operator_en, employee_name, date_hired, status, contact, process)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (operator_en, employee_name, date_hired,
                                 status, contact, process))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'New user registered successfully!'})

    except Exception as e:
        print('Database Error:', e)
        return jsonify({'success': False, 'message': f'Database error: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
