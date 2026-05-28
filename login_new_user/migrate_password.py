# migrate_passwords.py  — run ONCE, then delete this file
import pymysql
import bcrypt

conn = pymysql.connect(
    host='192.168.1.38', port=3306,
    user='testing', password='testing',
    db='operators', charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)

with conn.cursor() as cursor:
    cursor.execute('SELECT employee_num, badge FROM user')
    users = cursor.fetchall()

for u in users:
    plain = u['badge']
    # Skip already-hashed values (bcrypt hashes start with $2b$)
    if plain.startswith('$2b$') or plain.startswith('$2a$'):
        print(f"  Skipping {u['employee_num']} — already hashed")
        continue
    hashed = bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    with conn.cursor() as cursor:
        cursor.execute('UPDATE user SET badge = %s WHERE employee_num = %s',
                       (hashed, u['employee_num']))
    conn.commit()
    print(f"  Hashed badge for {u['employee_num']}")

conn.close()
print("Migration complete.")