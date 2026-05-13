"""
This file is used to get the model of a ticket.
"""
import pymysql

class Model:
    def __init__(self):
        self.config = {
            "host": "192.168.1.38",
            "user": "readonly_user",
            "password": "kts@tsd2025",
            "cursorclass": pymysql.cursors.DictCursor
        }

    def get_models_for_customer(self, schemadb):
        """
        List models for a customer by connecting directly to their schema
        and running SHOW TABLES. The 'model' is the unique first word
        before the first underscore in each table name.
        e.g. tables ['evo_repair', 'evo_history', 'titan_log'] → ['evo', 'titan']
        """
        connection = None
        try:
            # Connect directly to the customer's schema so SHOW TABLES works
            # even when readonly_user has no information_schema row-level access.
            config = {**self.config, "database": schemadb}
            connection = pymysql.connect(**config)
            with connection.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                rows = cursor.fetchall()

            if not rows:
                return []

            # Each DictCursor row from SHOW TABLES looks like:
            # {"Tables_in_<schemadb>": "table_name"}
            table_names = [list(row.values())[0] for row in rows]

            # Extract unique prefix before the first underscore as the model name
            models = list(set(name.split('_')[0] for name in table_names))
            return sorted(models)

        except Exception as e:
            print(f"[Model] Error loading models for schema '{schemadb}': {e}")
            return []
        finally:
            if connection:
                connection.close()
