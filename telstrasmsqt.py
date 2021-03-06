import sys
import os
import re
import json
import requests
import inspect
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QPushButton,
    QGridLayout,
    QLineEdit,
    QSizePolicy,
    QInputDialog,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
)
from PyQt5.QtGui import QIcon

import api
from message import *


class App(QMainWindow):
    """Main GUI for app"""

    WIDTH = 640
    HEIGHT = 480

    def __init__(self):
        super().__init__()

        self.bearer = None
        self.phone_number = None
        self.received_messages = []
        self.num_label = QLabel()
        self.num_text = QLineEdit()
        self.msg_text = QLineEdit()
        self.msg_table = QTableWidget()

        self.keys = []
        self.load_keys()

        self.init_ui()

    @staticmethod
    def get_path_to(filename):
        return os.path.join(os.path.abspath(os.path.dirname(__file__)), filename)

    def load_keys(self):
        try:
            with open(App.get_path_to("keys.json")) as f:
                self.keys = json.load(f)
        except FileNotFoundError:
            self.show_message(
                "No existing keys.json file found",
                "Manually add keys and the program will create a new config file.",
                QMessageBox.Warning,
            )
        except json.JSONDecodeError:
            self.show_message(
                "Error parsing keys.json",
                "Check that the file is formatted as per the example.",
                QMessageBox.Critical,
            )

    def save_keys(self):
        try:
            with open(App.get_path_to("keys.json"), "w") as f:
                json.dump(self.keys, f, indent=4)
        except Exception as e:
            self.show_message(
                "Could not write to keys.json file", e, QMessageBox.Critical
            )

    def init_ui(self):
        self.setWindowTitle("Telstra SMS")
        self.resize(self.WIDTH, self.HEIGHT)
        self.set_status("Ready")

        main_widget = QWidget()
        grid = QGridLayout()

        self.num_label.setText("Num: N/A (request token)")

        bearer_button = QPushButton("Get token")
        bearer_button.clicked.connect(self.choose_bearer)

        self.num_text.setPlaceholderText("Dest. number")

        self.msg_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.msg_text.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self.msg_text.setPlaceholderText("Message")

        send_button = QPushButton("Send")
        send_button.clicked.connect(self.send_message)

        fetch_button = QPushButton("Receive")
        fetch_button.clicked.connect(self.get_message)

        # self.msg_table.setRowCount(10)
        self.msg_table.setColumnCount(3)
        self.msg_table.setHorizontalHeaderLabels(["Sender", "Time", "Message"])
        self.msg_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )

        grid.addWidget(bearer_button, 0, 3)
        grid.addWidget(self.num_label, 0, 0)
        grid.addWidget(self.num_text, 1, 0, 1, 4)
        grid.addWidget(self.msg_text, 2, 0, 1, 4)
        grid.addWidget(send_button, 3, 3)
        grid.addWidget(fetch_button, 3, 0)
        grid.addWidget(self.msg_table, 4, 0, 1, 4)

        main_widget.setLayout(grid)
        self.setCentralWidget(main_widget)

        self.show()

    def set_status(self, message):
        self.statusBar().showMessage(message)

    def show_message(self, title, message, icon=QMessageBox.Information):
        dlg = QMessageBox(parent=self)
        dlg.setWindowTitle(title)
        dlg.setIcon(icon)
        dlg.setText(message)
        dlg.exec_()

    def api_request(self, f, *args, **kwargs):
        try:
            response = f(*args, **kwargs)
        except requests.exceptions.Timeout:
            self.show_message(
                "Request timed out",
                "Check connection and try again",
                QMessageBox.Critical,
            )
        except requests.exceptions.ConnectionError:
            self.show_message(
                "Network problem",
                "Check connection and try again",
                QMessageBox.Critical,
            )
        except Exception as e:
            self.show_message(
                f"Error calling {f.__name__}, report bug", e, QMessageBox.Critical
            )
        else:
            return response

    def check_response(self, response, success_code):
        if response is None:
            return False
        elif response.status_code == success_code:
            return True
        else:
            caller = inspect.stack()[1][3]
            self.set_status(
                f"Request method {caller} failed with code {response.status_code}, check logs"
            )
            print(f"{caller}: {response} {response.text}", file=sys.stderr)
            return False

    def choose_bearer(self):
        chosen, ok_pressed = QInputDialog.getItem(
            self,
            "Keys",
            "Choose key (last known number and bearer shown below).\nAlternatively enter a new key pair (format: [key] [secret])",
            [
                f"{i}. {k.get('number') or '[unknown number]'} {k['key']}"
                for i, k in enumerate(self.keys, start=1)
                if ('key' in k) and ('secret' in k)
            ],
        )

        if not (chosen and ok_pressed):
            return

        parts = chosen.split()
        key_index = -1
        if (len(parts) == 2):
            key, secret = parts
            if len(key) != 32 or len(secret) != 16:
                self.show_message("Invalid key", "Key must be of length 32 & secret of length 16.", QMessageBox.Critical)
                return
        else:
            key_index = int(parts[0].replace('.', '')) - 1
            key, secret = self.keys[key_index]["key"], self.keys[key_index]["secret"]

        response = self.api_request(api.get_bearer, key, secret)
        if self.check_response(response, 200):
            self.bearer = response.json()["access_token"]
            self.set_status("Success! Token valid for one hour")

            phone_number = self.api_request(api.get_number, self.bearer)
            if not phone_number:
                self.show_message(
                    "No number",
                    "This bearer has no number associated. Will request a new one.",
                )
                phone_number = self.api_request(api.new_number, self.bearer)
            self.phone_number = phone_number.json()["destinationAddress"]

            # Save phone number and new key pair (if applicable)
            if key_index == -1:
                key_index = len(self.keys)
                self.keys.append({'key': key, 'secret': secret})
            self.keys[key_index]['number'] = self.phone_number
            self.save_keys()

            self.num_label.setText(f"Num: {self.phone_number}")

    def get_message(self):
        if self.bearer is None:
            return self.set_status("Request bearer first")

        self.set_status("Fetching messages...")
        while True:
            response = self.api_request(api.get_message, self.bearer)
            if self.check_response(response, 200):
                j = response.json()
                if j["status"] == "EMPTY":
                    break

                time = datetime.fromisoformat(j["sentTimestamp"])
                message = Message(
                    msg_type=MessageType.INCOMING,
                    sender=j["senderAddress"],
                    destination=self.phone_number,
                    text=j["message"],
                    msg_id=j["messageId"],
                    timestamp=time,
                )
                self.received_messages.append(message)

                i = len(self.received_messages) - 1
                self.msg_table.setRowCount(i + 1)
                self.msg_table.setItem(i, 0, QTableWidgetItem(message.sender))
                self.msg_table.setItem(
                    i,
                    1,
                    QTableWidgetItem(
                        datetime.strftime(message.timestamp, "%d/%m %H:%M:%S")
                    ),
                )
                self.msg_table.setItem(i, 2, QTableWidgetItem(message.text))
        self.set_status("Fetched all messages")

    def send_message(self):
        if self.bearer is None:
            return self.set_status("Request bearer first")

        message = Message(
            msg_type=MessageType.OUTGOING,
            sender=self.phone_number,
            destination=self.num_text.text(),
            text=self.msg_text.text(),
        )
        if len(message.destination) == 0:
            return self.set_status("Number cannot be blank")

        if len(message.text) == 0:
            return self.set_status("Message cannot be blank")

        self.set_status(f"Sending message to {message.destination}")
        response = self.api_request(
            api.send_message, self.bearer, message.destination, message.text
        )
        if self.check_response(response, 201):
            self.set_status("Request to send message successful")
            self.num_text.setText("")
            self.msg_text.setText("")
        else:
            self.set_status("Request to send message failed")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = App()
    app.exec_()
