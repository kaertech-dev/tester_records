import pymysql

class Customer:
    def __init__(self):
        self.config = {
            "host": "192.168.1.38",
            "user": "readonly_user",
            "password": "kts@tsd2025",
            "database": "projectsdb",
            "cursorclass": pymysql.cursors.DictCursor
        }

    def get_active_customer(self):
        connection = None
        try:
            connection = pymysql.connect(**self.config)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT schemadb
                    FROM projects
                    WHERE status = "ACTIVE"
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return []
        finally:
            if connection:
                connection.close()