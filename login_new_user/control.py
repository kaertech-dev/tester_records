# control.py
from PyQt5.uic import loadUi
from PyQt5.QtWidgets import QMainWindow, QMessageBox
from database import Database


class signin_new_user(QMainWindow):
    def __init__(self):
        super(signin_new_user, self).__init__()
        loadUi("signin_new_user.ui", self)
        print(self.__dict__.keys())

        # Connect button
        self.signin_button.clicked.connect(self.signin_new_user)

    def signin_new_user(self):

        operator_en = self.operator_en.text()
        employee_name = self.employee_name.text()

        # Get date from calendar widget
        date_hired = self.date_hired.date().toString("yyyy-MM-dd")

        status = self.status.text()
        contact = self.contact.text()
        process = self.process.text()

        db = Database()

        result = db.signin_new_user(
            operator_en,
            employee_name,
            date_hired,
            status,
            contact,
            process
        )