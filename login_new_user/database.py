# database.py
import pymysql


class Database:
    def __init__(self):
        self.connection = pymysql.connect(
            host='192.168.1.38',
            port=3306,
            user='testing',
            password='testing',
            db='operators'
        )

    def signin_new_user(
        self,
        operator_en,
        employee_name,
        date_hired,
        status,
        contact,
        process
    ):

        try:
            with self.connection.cursor() as cursor:

                sql = """
                    INSERT INTO main
                    (operator_en, employee_name, date_hired,
                     status, contact, process)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """

                values = (
                    operator_en,
                    employee_name,
                    date_hired,
                    status,
                    contact,
                    process
                )

                cursor.execute(sql, values)

            self.connection.commit()
            return True

        except Exception as e:
            print("Database Error:", e)
            return False