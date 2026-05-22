""" 
This file is used to get the classification of a ticket.
"""

import pymysql

class Classification:
    def __init__(self):
        self.config = {
            "host": "192.168.2.5",# change the .1.38 to 2.5
            "user": "readonly_user",
            "password": "kts@tsd2025",
            "database": "engineering",
            "cursorclass": pymysql.cursors.DictCursor
        }
    
    def get_classification(self, classification_id):
        connection = None
        try:
            connection = pymysql.connect(**self.config)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT *
                    FROM classifications
                    WHERE classification = %s
                """, (classification_id,))
                return cursor.fetchone()
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return None
        finally:
            if connection:
                connection.close()

    def get_all_classifications(self):
        connection = None
        try:
            connection = pymysql.connect(**self.config)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT classification
                    FROM classifications
                    ORDER BY classification
                """)
                results = cursor.fetchall()
                # Extract just the classification names
                return [row['classification'] for row in results]
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return []
        finally:
            if connection:
                connection.close()

    def get_classifications_for_model(self, models):
        connection = None
        try:
            connection = pymysql.connect(**self.config)
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT classification
                    FROM classifications
                    ORDER BY classification
                """)
                results = cursor.fetchall()
                # Extract just the classification names
                return [row['classification'] for row in results]
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return []
        finally:
            if connection:
                connection.close()