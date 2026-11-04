import sys
import sqlite3
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget,
    QFormLayout, QTextEdit, QDoubleSpinBox,
    QFileDialog, QMessageBox, QTableWidget,
    QTableWidgetItem
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt


APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(APP_DIR, "aquarium.db")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AquaControl")
        self.setMinimumSize(900, 600)

        self.init_db()
        self.dark_mode = False
        # ===== CENTRAL =====
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ===== LEFT MENU =====
        menu_layout = QVBoxLayout()

        self.btn_home = QPushButton("Domov")
        self.btn_manual = QPushButton("Zadať merania")
        self.btn_import = QPushButton("Importovať fotku")
        self.btn_history = QPushButton("História")
        self.btn_settings = QPushButton("Nastavenia")

        for btn in (
            self.btn_home,
            self.btn_manual,
            self.btn_import,
            self.btn_history,
            self.btn_settings
        ):
            btn.setMinimumHeight(40)
            menu_layout.addWidget(btn)

        menu_layout.addStretch()
        main_layout.addLayout(menu_layout, 1)

        # ===== STACKED PAGES =====
        self.pages = QStackedWidget()
        main_layout.addWidget(self.pages, 4)

        # ===== PAGES =====
        self.page_home = self.create_home_page()
        self.page_manual = self.create_manual_page()
        self.page_import = self.create_import_page()
        self.page_history = self.create_history_page()
        self.page_settings = self.create_settings_page()

        for p in (
            self.page_home,
            self.page_manual,
            self.page_import,
            self.page_history,
            self.page_settings
        ):
            self.pages.addWidget(p)

        # ===== BUTTON CONNECTIONS =====
        self.btn_home.clicked.connect(self.show_home)
        self.btn_manual.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        self.btn_import.clicked.connect(self.import_photo_choice)
        self.btn_history.clicked.connect(self.show_history)
        self.btn_settings.clicked.connect(lambda: self.pages.setCurrentIndex(4))

        self.btn_save.clicked.connect(self.save_measurement)

        self.update_recommendation()

    # ================= DATABASE =================
    def init_db(self):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            ph REAL,
            kh REAL,
            gh REAL,
            no2 REAL,
            no3 REAL,
            cl2 REAL,
            note TEXT
        )
        """)

        conn.commit()
        conn.close()

    def save_measurement(self):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO measurements
        (date, ph, kh, gh, no2, no3, cl2, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            self.input_ph.value(),
            self.input_kh.value(),
            self.input_gh.value(),
            self.input_no2.value(),
            self.input_no3.value(),
            self.input_cl2.value(),
            self.input_note.toPlainText()
        ))

        conn.commit()
        conn.close()

        QMessageBox.information(self, "Uložené", "Meranie bolo uložené do databázy.")
        self.load_history()
        self.update_recommendation()

    # ================= HOME =================
    def create_home_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("Stav akvária")
        title.setStyleSheet("font-size: 26px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.db_status = QLabel()
        self.db_status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.recommendation_label = QLabel("Žiadne dáta")
        self.recommendation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recommendation_label.setStyleSheet("font-size: 18px;")

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(self.db_status)
        layout.addSpacing(20)
        layout.addWidget(self.recommendation_label)
        layout.addStretch()
        return page

    def show_home(self):
        self.update_recommendation()
        self.pages.setCurrentIndex(0)

    def update_recommendation(self):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT no2, no3, cl2
        FROM measurements
        ORDER BY date DESC
        LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if not row:
            self.recommendation_label.setText("Zatiaľ nie sú žiadne merania")
            return

        no2, no3, cl2 = row
        messages = []

        if 100 <= no3 <= 250:
            messages.append("⚠ NO₃ vysoké → Odporúčaná výmena vody")

        if 5 <= no2 <= 10:
            messages.append("⚠ NO₂ vysoké → Odporúčaná výmena vody a nepridávať živočíchy")

        if 1.5 <= cl2 <= 3:
            messages.append("⚠ Cl₂ vysoké → Použi AquaSafe")

        if not messages:
            self.recommendation_label.setText("Hodnoty sú v norme")
        else:
            self.recommendation_label.setText("\n".join(messages))

    # ================= OSTATNÉ PAGES =================
    def create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("Nastavenia")
        title.setStyleSheet("font-size: 22px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_theme = QPushButton("🌙 Tmavý režim")
        self.btn_theme.setMinimumHeight(40)
        self.btn_theme.clicked.connect(self.toggle_dark_mode)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(self.btn_theme)
        layout.addStretch()

        return page

    def create_manual_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("Manuálne zadanie meraní (Terra 6 in 1)")
        title.setStyleSheet("font-size: 22px;")
        layout.addWidget(title)

        form = QFormLayout()

        def spinbox():
            sb = QDoubleSpinBox()
            sb.setRange(0.0, 250.0)
            sb.setDecimals(2)
            sb.setSingleStep(0.1)
            sb.setFixedWidth(120)
            return sb

        self.input_ph = spinbox()
        self.input_kh = spinbox()
        self.input_gh = spinbox()
        self.input_no2 = spinbox()
        self.input_no3 = spinbox()
        self.input_cl2 = spinbox()

        form.addRow("NO₃:", self.input_no3)
        form.addRow("NO₂:", self.input_no2)
        form.addRow("GH:", self.input_gh)
        form.addRow("KH:", self.input_kh)
        form.addRow("pH:", self.input_ph)
        form.addRow("Cl₂:", self.input_cl2)

        layout.addLayout(form)

        self.input_note = QTextEdit()
        layout.addWidget(self.input_note)

        self.btn_save = QPushButton("Uložiť meranie")
        layout.addWidget(self.btn_save)

        layout.addStretch()
        return page

    def create_history_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Dátum", "pH", "KH", "GH", "NO₂", "NO₃", "Cl₂", "Poznámka"
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout.addWidget(self.table)

        self.btn_delete = QPushButton("🗑 Vymazať vybrané meranie")
        self.btn_delete.setMinimumHeight(35)
        self.btn_delete.clicked.connect(self.delete_selected_measurement)

        layout.addWidget(self.btn_delete)
        return page

    def load_history(self):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT date, ph, kh, gh, no2, no3, cl2, note
        FROM measurements
        ORDER BY date DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(str(val)))

    def show_history(self):
        self.load_history()
        self.pages.setCurrentIndex(3)

    # ================= IMPORT =================
    def create_import_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.import_label = QLabel("Zatiaľ nie je vybraná žiadna fotka")
        self.import_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_label.setStyleSheet("font-size: 18px; color: gray;")

        layout.addStretch()
        layout.addWidget(self.import_label)
        layout.addStretch()

        return page
    def open_image_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Vyberte fotku testovacieho prúžku",
            "",
            "Images (*.png *.jpg *.jpeg)"
        )

        if file_path:
            pixmap = QPixmap(file_path)
            self.import_label.setPixmap(
                pixmap.scaled(
                    600, 400,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

            # 👉 TU PRIDAJ:
            self.analyze_test_strip(file_path)




    def import_photo_choice(self):
        self.pages.setCurrentIndex(2)

        msg = QMessageBox(self)
        msg.setWindowTitle("Import obrázka")
        msg.setText("Ako chcete získať obrázok testovacieho prúžku?")
        msg.setIcon(QMessageBox.Icon.Question)

        btn_file = msg.addButton("Vybrať súbor", QMessageBox.ButtonRole.AcceptRole)
        btn_camera = msg.addButton("Použiť kameru", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Zrušiť", QMessageBox.ButtonRole.RejectRole)

        msg.exec()
        clicked = msg.clickedButton()

        if clicked == btn_file:
            self.open_image_file()
        elif clicked == btn_camera:
            self.open_camera()

    def open_camera(self):
        QMessageBox.information(
            self,
            "Kamera",
            "Kamera zatiaľ nie je implementovaná.\n"
            "Neskôr tu bude OpenCV snímanie."
        )

    def toggle_dark_mode(self):
        if not self.dark_mode:
            self.setStyleSheet("""
            QWidget {
                background-color: #121212;
                color: #E0E0E0;
            }
            QPushButton {
                background-color: #1E1E1E;
                border: 1px solid #444;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #333;
            }
            QLineEdit, QTextEdit, QDoubleSpinBox, QTableWidget {
                background-color: #1E1E1E;
                color: white;
                border: 1px solid #555;
            }
        """)
            self.btn_theme.setText("☀ Svetlý režim")
        else:
            self.setStyleSheet("")
            self.btn_theme.setText("🌙 Tmavý režim")

        self.dark_mode = not self.dark_mode

    def delete_selected_measurement(self):
        selected = self.table.currentRow()

        if selected < 0:
            QMessageBox.warning(self, "Chyba", "Najprv vyber meranie v tabuľke.")
            return

        date_value = self.table.item(selected, 0).text()

        reply = QMessageBox.question(
            self,
            "Potvrdenie vymazania",
            f"Naozaj chceš vymazať meranie z dátumu:\n{date_value}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM measurements WHERE date = ?",
            (date_value,)
        )

        conn.commit()
        conn.close()

        self.load_history()
        self.update_recommendation()

        QMessageBox.information(self, "Hotovo", "Meranie bolo vymazané.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
