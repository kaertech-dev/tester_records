# database.py
import pymysql
import bcrypt
from dotenv import load_dotenv
import os

load_dotenv()  # Load environment variables from .env file

class Database:
    def __init__(self):
        self.connection = pymysql.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            db=os.getenv("DB_NAME"),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    # ── Auth ──────────────────────────────────────────────────────────────────

    def verify_user(self, employee_num: str, badge: str):
        """Returns the user row if credentials match, else None."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    'SELECT employee_num, badge FROM user WHERE employee_num = %s',
                    (employee_num,)
                )
                row = cursor.fetchone()
            if row and bcrypt.checkpw(badge.encode('utf-8'), row['badge'].encode('utf-8')):
                return row
            return None
        except Exception as e:
            print("Database Error (verify_user):", e)
            return None

    # ── Operator registration ─────────────────────────────────────────────────

    def signin_new_user(self, operator_en, employee_name,
                        date_hired, status, contact, process):
        try:
            with self.connection.cursor() as cursor:
                sql = """
                    INSERT INTO main
                        (operator_en, employee_name, date_hired,
                         status, contact, process)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (operator_en, employee_name,
                                     date_hired, status, contact, process))
            self.connection.commit()
            return True
        except Exception as e:
            print("Database Error (signin_new_user):", e)
            return False

    # ── Admin: user management ────────────────────────────────────────────────

    def get_all_users(self):
        """Returns list of all rows in the user table (no badge)."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                'SELECT employee_num, employee_name FROM user ORDER BY employee_num'
            )
            return cursor.fetchall()

    def add_user(self, employee_num: str, employee_name: str, badge: str):
        """
        Insert a new authorized user with a hashed badge.
        Returns True on success, 'duplicate' if employee_num already exists,
        False on other errors.
        """
        try:
            hashed = bcrypt.hashpw(badge.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            with self.connection.cursor() as cursor:
                cursor.execute(
                    'INSERT INTO user (employee_num, employee_name, badge) VALUES (%s, %s, %s)',
                    (employee_num, employee_name, hashed)
                )
            self.connection.commit()
            return True
        except pymysql.err.IntegrityError:
            return 'duplicate'
        except Exception as e:
            print("Database Error (add_user):", e)
            return False

    def delete_user(self, employee_num: str):
        """Delete a user by employee_num. Returns True if a row was deleted."""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    'DELETE FROM user WHERE employee_num = %s',
                    (employee_num,)
                )
            self.connection.commit()
            return self.connection.affected_rows() > 0
        except Exception as e:
            print("Database Error (delete_user):", e)
            return False
    
    def show_all_user(self):
        """Returns list of all rows in the main table (no badge)."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                'SELECT operator_en, employee_name, date_hired, status, contact, process FROM main ORDER BY employee_name'
            )
            return cursor.fetchall()