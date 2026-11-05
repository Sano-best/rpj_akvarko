"""AquaControl - evidencia meraní kvality vody v akváriu (PyQt6 + SQLite)."""
import os
import sqlite3
import sys
from contextlib import closing
from typing import NamedTuple

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDateTimeEdit, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

# Z .exe (PyInstaller) sa DB ukladá vedľa .exe, inak by sa strácala v dočasnom priečinku.
BASE_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "aquarium.db")


class Param(NamedTuple):
    key: str    # názov stĺpca v DB
    name: str
    unit: str
    lo: float   # predvolené minimum
    hi: float   # predvolené maximum
    top: float  # najvyššia hodnota, ktorú vieš zadať
    hint: str   # rada pri prekročení maxima

    @property
    def title(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name


# Poradie ako na prúžku Terra 6 in 1. Predvolené hranice sú všeobecné pre sladkovodné akvárium
# a dajú sa zmeniť v Nastaveniach.
PARAMS = [
    Param("no3", "NO₃", "mg/l", 0, 50, 250, "Vymeň časť vody."),
    Param("no2", "NO₂", "mg/l", 0, 0.5, 250, "Vymeň časť vody a nepridávaj živočíchy."),
    Param("gh", "GH", "°dGH", 4, 14, 250, ""),
    Param("kh", "KH", "°dKH", 3, 10, 250, ""),
    Param("ph", "pH", "", 6.5, 8.0, 14, ""),
    Param("cl2", "Cl₂", "mg/l", 0, 0, 250, "Použi AquaSafe."),
]
COLS = ", ".join(p.key for p in PARAMS)
NAV = ["Domov", "Zadať merania", "Importovať fotku", "História", "Nastavenia"]

DARK_STYLE = """
QWidget { background-color: #121212; color: #E0E0E0; }
QPushButton { background-color: #1E1E1E; border: 1px solid #444; padding: 8px; }
QPushButton:hover { background-color: #333; }
QLineEdit, QTextEdit, QDoubleSpinBox, QDateTimeEdit, QTableWidget {
    background-color: #1E1E1E; color: white; border: 1px solid #555;
}
"""


# ================= DATABÁZA =================
def db(sql, args=(), fetch=False):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.fetchall() if fetch else None


def init_db():
    db("""CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
        ph REAL, kh REAL, gh REAL, no2 REAL, no3 REAL, cl2 REAL, note TEXT)""")
    db("CREATE TABLE IF NOT EXISTS limits (key TEXT PRIMARY KEY, min_value REAL, max_value REAL)")
    for p in PARAMS:
        db("INSERT OR IGNORE INTO limits VALUES (?, ?, ?)", (p.key, p.lo, p.hi))


def get_limits():
    return {key: (lo, hi) for key, lo, hi in db("SELECT key, min_value, max_value FROM limits", fetch=True)}


def check(values, limits):
    """Vráti zoznam (text, rada) pre každú hodnotu mimo hraníc."""
    problems = []
    for p in PARAMS:
        lo, hi = limits[p.key]
        v = values[p.key]
        if lo <= v <= hi:
            continue
        shown = f"{v:g} {p.unit}".strip()
        word = "nízke" if v < lo else "vysoké"
        problems.append((f"{p.name} je príliš {word}: {shown} (povolené {lo:g} - {hi:g})",
                         p.hint if v > hi else ""))
    return problems


# ================= UI =================
def spin(maximum):
    sb = QDoubleSpinBox()
    sb.setRange(0.0, maximum)
    sb.setDecimals(2)
    sb.setSingleStep(0.1)
    sb.setFixedWidth(120)
    return sb


def make_page(title):
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(title)
    label.setStyleSheet("font-size: 22px;")
    layout.addWidget(label)
    return page, layout


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AquaControl")
        self.setMinimumSize(900, 600)
        self.dark = False
        init_db()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        menu = QVBoxLayout()
        self.pages = QStackedWidget()

        builders = (self.home_page, self.manual_page, self.import_page, self.history_page, self.settings_page)
        for i, (text, build) in enumerate(zip(NAV, builders)):
            btn = QPushButton(text)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _, i=i: self.go(i))
            menu.addWidget(btn)
            self.pages.addWidget(build())

        menu.addStretch()
        main_layout.addLayout(menu, 1)
        main_layout.addWidget(self.pages, 4)
        self.go(0)

    def go(self, index):
        if index == 0:
            self.refresh_home()
        elif index == 3:
            self.load_history()
        elif index == 4:
            self.load_limits_form()
        self.pages.setCurrentIndex(index)

    # ----- Domov -----
    def home_page(self):
        page, layout = make_page("Stav akvária")
        self.home_label = QLabel()
        self.home_label.setWordWrap(True)
        self.home_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_label.setStyleSheet("font-size: 18px;")
        layout.addWidget(self.home_label, 1)
        return page

    def refresh_home(self):
        rows = db(f"SELECT date, {COLS} FROM measurements ORDER BY date DESC, id DESC LIMIT 1", fetch=True)
        if not rows:
            self.home_label.setText("Zatiaľ nie sú žiadne merania")
            return
        date, *vals = rows[0]
        problems = check(dict(zip((p.key for p in PARAMS), vals)), get_limits())
        lines = [f"Posledné meranie: {date}",
                 "   ".join(f"{p.name} {v:g} {p.unit}".strip() for p, v in zip(PARAMS, vals)), ""]
        if problems:
            lines += [f"⚠ {text}" + (f" → {hint}" if hint else "") for text, hint in problems]
        else:
            lines.append("✔ Všetky hodnoty sú v norme")
        self.home_label.setText("\n".join(lines))

    # ----- Zadať merania -----
    def manual_page(self):
        page, layout = make_page("Manuálne zadanie meraní (Terra 6 in 1)")
        form = QFormLayout()

        self.input_date = QDateTimeEdit(QDateTime.currentDateTime())
        self.input_date.setCalendarPopup(True)
        self.input_date.setDisplayFormat("dd.MM.yyyy HH:mm")
        form.addRow("Dátum a čas:", self.input_date)

        self.inputs = {}
        for p in PARAMS:
            self.inputs[p.key] = spin(p.top)
            form.addRow(f"{p.title}:", self.inputs[p.key])
        layout.addLayout(form)

        self.input_note = QTextEdit()
        self.input_note.setPlaceholderText("Poznámka (voliteľné)")
        layout.addWidget(self.input_note)

        btn = QPushButton("Uložiť meranie")
        btn.clicked.connect(self.save_measurement)
        layout.addWidget(btn)
        return page

    def save_measurement(self):
        values = {key: sb.value() for key, sb in self.inputs.items()}
        problems = check(values, get_limits())
        if problems:
            text = "\n".join(f"• {t}" for t, _ in problems)
            answer = QMessageBox.warning(
                self, "Hodnota mimo rozsahu", f"{text}\n\nUložiť meranie aj tak?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return

        placeholders = ", ".join("?" * (len(PARAMS) + 2))
        db(f"INSERT INTO measurements (date, {COLS}, note) VALUES ({placeholders})",
           (self.input_date.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            *(values[p.key] for p in PARAMS), self.input_note.toPlainText()))

        for sb in self.inputs.values():
            sb.setValue(0)
        self.input_note.clear()
        self.input_date.setDateTime(QDateTime.currentDateTime())
        QMessageBox.information(self, "Uložené", "Meranie bolo uložené do databázy.")

    # ----- Import fotky -----
    def import_page(self):
        page, layout = make_page("Import fotky testovacieho prúžku")
        self.photo = QLabel("Zatiaľ nie je vybraná žiadna fotka")
        self.photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo.setStyleSheet("font-size: 18px; color: gray;")
        btn = QPushButton("Vybrať fotku")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.open_photo)
        note = QLabel("Automatické rozpoznanie hodnôt z fotky pribudne v ďalšej verzii.")
        layout.addWidget(self.photo, 1)
        layout.addWidget(btn)
        layout.addWidget(note)
        return page

    def open_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Vyberte fotku testovacieho prúžku", "", "Obrázky (*.png *.jpg *.jpeg)")
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Chyba", "Obrázok sa nepodarilo načítať.")
            return
        self.photo.setPixmap(pixmap.scaled(
            600, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    # ----- História -----
    def history_page(self):
        page, layout = make_page("História meraní")
        headers = ["ID", "Dátum"] + [p.title for p in PARAMS] + ["Poznámka"]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setColumnHidden(0, True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

        btn = QPushButton("🗑 Vymazať vybrané meranie")
        btn.setMinimumHeight(35)
        btn.clicked.connect(self.delete_selected_measurement)
        layout.addWidget(btn)
        return page

    def load_history(self):
        rows = db(f"SELECT id, date, {COLS}, note FROM measurements ORDER BY date DESC, id DESC", fetch=True)
        limits = get_limits()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else f"{val:g}" if isinstance(val, float) else str(val))
                if 2 <= c < 2 + len(PARAMS) and val is not None:
                    lo, hi = limits[PARAMS[c - 2].key]
                    if not lo <= val <= hi:  # hodnota mimo hraníc -> červené pozadie
                        item.setBackground(QColor(200, 60, 60))
                        item.setForeground(QColor("white"))
                self.table.setItem(r, c, item)

    def delete_selected_measurement(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Chyba", "Najprv vyber meranie v tabuľke.")
            return
        measurement_id = int(self.table.item(row, 0).text())
        date = self.table.item(row, 1).text()
        answer = QMessageBox.question(
            self, "Potvrdenie vymazania", f"Naozaj chceš vymazať meranie z {date}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            db("DELETE FROM measurements WHERE id = ?", (measurement_id,))
            self.load_history()

    # ----- Nastavenia -----
    def settings_page(self):
        page, layout = make_page("Nastavenia")
        self.btn_theme = QPushButton("🌙 Tmavý režim")
        self.btn_theme.setMinimumHeight(40)
        self.btn_theme.clicked.connect(self.toggle_dark_mode)
        layout.addWidget(self.btn_theme)

        layout.addWidget(QLabel("\nPovolené hranice hodnôt (mimo nich appka upozorní):"))
        form = QFormLayout()
        self.limit_inputs = {}
        for p in PARAMS:
            lo, hi = spin(p.top), spin(p.top)
            row = QHBoxLayout()
            for text, widget in (("min", lo), ("max", hi)):
                row.addWidget(QLabel(text))
                row.addWidget(widget)
            row.addStretch()
            form.addRow(f"{p.title}:", row)
            self.limit_inputs[p.key] = (lo, hi)
        layout.addLayout(form)

        btn = QPushButton("Uložiť hranice")
        btn.clicked.connect(self.save_limits)
        layout.addWidget(btn)
        layout.addStretch()
        return page

    def load_limits_form(self):
        for key, (lo, hi) in get_limits().items():
            self.limit_inputs[key][0].setValue(lo)
            self.limit_inputs[key][1].setValue(hi)

    def save_limits(self):
        new = {key: (lo.value(), hi.value()) for key, (lo, hi) in self.limit_inputs.items()}
        bad = [p.name for p in PARAMS if new[p.key][0] > new[p.key][1]]
        if bad:
            QMessageBox.warning(self, "Neplatné hranice",
                                "Minimum nesmie byť väčšie ako maximum: " + ", ".join(bad))
            return
        for key, (lo, hi) in new.items():
            db("UPDATE limits SET min_value = ?, max_value = ? WHERE key = ?", (lo, hi, key))
        QMessageBox.information(self, "Uložené", "Hranice boli uložené.")

    def toggle_dark_mode(self):
        self.dark = not self.dark
        self.setStyleSheet(DARK_STYLE if self.dark else "")
        self.btn_theme.setText("☀ Svetlý režim" if self.dark else "🌙 Tmavý režim")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
