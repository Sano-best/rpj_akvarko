"""Automatické testy AquaControl (PyQt6, bez zobrazenia okna).

Spustenie:  py -m pip install PyQt6   a potom   py test_aquacontroll.py
Skript vypíše výsledok každého testu a uloží ho do test_results.json.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "04_Implementacia", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QDateTime  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

import aquacontroll as aq  # noqa: E402

app = QApplication.instance() or QApplication([])
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
OK = QMessageBox.StandardButton.Ok

popups = []       # zaznamenané popup okná: (druh, nadpis, text)
answer = [YES]    # čo "klikne" používateľ v otázke / upozornení


def fake(kind):
    def _show(parent, title, text, *args):
        popups.append((kind, title, text))
        return OK if kind == "information" else answer[0]
    return staticmethod(_show)


QMessageBox.warning = fake("warning")
QMessageBox.information = fake("information")
QMessageBox.question = fake("question")


def fresh():
    """Nová prázdna databáza a nové okno."""
    popups.clear()
    answer[0] = YES
    aq.DB_NAME = os.path.join(tempfile.mkdtemp(), "test.db")
    return aq.MainWindow()


def fill(w, **vals):
    for key, value in vals.items():
        w.inputs[key].setValue(value)


def measurements():
    return aq.db("SELECT id, date, no3, ph, note FROM measurements ORDER BY id", fetch=True)


GOOD = dict(no3=20, no2=0, gh=8, kh=6, ph=7.2, cl2=0)
BAD = dict(no3=120, no2=0, gh=8, kh=6, ph=5.0, cl2=0)


def tc_001():
    w = fresh()
    assert w.home_label.text() == "Zatiaľ nie sú žiadne merania"


def tc_002():
    w = fresh()
    fill(w, **GOOD)
    w.save_measurement()
    assert len(measurements()) == 1
    assert not [p for p in popups if p[0] == "warning"], "nemal sa zobraziť popup s upozornením"
    w.go(0)
    assert "✔ Všetky hodnoty sú v norme" in w.home_label.text()
    assert all(sb.value() == 0 for sb in w.inputs.values()), "formulár sa mal vynulovať"


def tc_003():
    w = fresh()
    answer[0] = NO
    fill(w, **BAD)
    w.save_measurement()
    warnings = [p for p in popups if p[0] == "warning"]
    assert len(warnings) == 1
    assert "NO₃ je príliš vysoké" in warnings[0][2] and "pH je príliš nízke" in warnings[0][2]
    assert len(measurements()) == 0, "pri odpovedi Nie sa nemalo nič uložiť"


def tc_004():
    w = fresh()
    fill(w, **BAD)
    w.save_measurement()
    assert len(measurements()) == 1
    w.go(0)
    text = w.home_label.text()
    assert "⚠ NO₃ je príliš vysoké" in text and "Vymeň časť vody." in text and "pH je príliš nízke" in text


def tc_005():
    w = fresh()
    aq.db("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)",
          ("2026-10-01 08:00:00", 7.2, 6, 8, 0, 20, 0, "stare"))
    aq.db("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)",
          ("2026-10-02 08:00:00", 7.2, 6, 8, 0, 120, 0, "nove"))
    w.go(3)
    t = w.table
    assert t.rowCount() == 2
    assert t.item(0, 1).text() == "2026-10-02 08:00:00", "najnovšie meranie má byť prvé"
    assert t.isColumnHidden(0)
    assert t.horizontalHeaderItem(2).text() == "NO₃ (mg/l)"
    red = QColor(200, 60, 60)
    assert t.item(0, 2).background().color() == red, "NO₃ = 120 má byť zvýraznené"
    assert t.item(1, 2).background().color() != red, "NO₃ = 20 nemá byť zvýraznené"


def tc_006():
    w = fresh()
    for note in ("prve", "druhe"):  # rovnaký dátum, rôzne ID
        aq.db("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)",
              ("2026-10-01 08:00:00", 7, 6, 8, 0, 20, 0, note))
    w.go(3)
    w.table.selectRow(0)
    w.delete_selected_measurement()
    left = measurements()
    assert len(left) == 1, f"zostať mal 1 záznam, zostalo {len(left)}"


def tc_007():
    w = fresh()
    aq.db("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)",
          ("2026-10-01 08:00:00", 7, 6, 8, 0, 20, 0, ""))
    w.go(3)
    w.table.clearSelection()
    w.table.setCurrentCell(-1, -1)
    w.delete_selected_measurement()
    assert any("Najprv vyber meranie" in p[2] for p in popups)
    assert len(measurements()) == 1


def tc_008():
    w = fresh()
    aq.db("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)",
          ("2026-10-01 08:00:00", 7, 6, 8, 0, 20, 0, ""))
    w.go(3)
    w.table.selectRow(0)
    answer[0] = NO
    w.delete_selected_measurement()
    assert len(measurements()) == 1


def tc_009():
    w = fresh()
    w.go(4)
    lo, hi = w.limit_inputs["no3"]
    lo.setValue(30)
    hi.setValue(10)
    w.save_limits()
    assert any(p[0] == "warning" and "Minimum nesmie byť väčšie" in p[2] for p in popups)
    assert aq.get_limits()["no3"] == (0, 50), "neplatné hranice sa nemali uložiť"
    lo.setValue(0)
    hi.setValue(150)
    w.save_limits()
    assert aq.get_limits()["no3"] == (0, 150)
    popups.clear()
    fill(w, **GOOD)
    w.inputs["no3"].setValue(120)
    w.save_measurement()
    assert not [p for p in popups if p[0] == "warning"], "pri maxime 150 už 120 nemá upozorniť"


def tc_010():
    w = fresh()
    fill(w, **GOOD)
    w.input_date.setDateTime(QDateTime(2026, 10, 1, 8, 30, 0))
    w.save_measurement()
    assert measurements()[0][1] == "2026-10-01 08:30:00"


def tc_011():
    w = fresh()
    w.toggle_dark_mode()
    assert w.styleSheet() != "" and "Svetlý" in w.btn_theme.text()
    w.toggle_dark_mode()
    assert w.styleSheet() == "" and "Tmavý" in w.btn_theme.text()


def tc_012():
    w = fresh()
    tmp = tempfile.mkdtemp()
    bad = os.path.join(tmp, "zle.png")
    with open(bad, "w") as f:
        f.write("toto nie je obrázok")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (bad, ""))
    w.open_photo()
    assert any("nepodarilo načítať" in p[2] for p in popups)
    good = os.path.join(tmp, "dobre.png")
    img = QImage(100, 50, QImage.Format.Format_RGB32)
    img.fill(QColor("green"))
    img.save(good)
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (good, ""))
    w.open_photo()
    assert not w.photo.pixmap().isNull()


def tc_013():
    w = fresh()
    fill(w, **GOOD)
    w.save_measurement()
    w2 = aq.MainWindow()  # simulácia opätovného spustenia appky
    w2.go(3)
    assert w2.table.rowCount() == 1


def tc_014():
    w = fresh()
    w.inputs["ph"].setValue(20)
    assert w.inputs["ph"].value() == 14, "pH nemá ísť nad 14"
    w.inputs["no3"].setValue(-5)
    assert w.inputs["no3"].value() == 0, "záporná hodnota nie je povolená"


def tc_015():
    w = fresh()
    rows = [(f"2026-01-01 00:{i // 60 % 60:02d}:{i % 60:02d}", 7.0, 6, 8, 0, 20, 0, "") for i in range(10000)]
    conn = sqlite3.connect(aq.DB_NAME)
    conn.executemany("INSERT INTO measurements (date, ph, kh, gh, no2, no3, cl2, note) VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    start = time.perf_counter()
    w.go(0)
    assert time.perf_counter() - start < 3, "Domov musí byť pripravený do 3 s (NFR-P-01)"
    start = time.perf_counter()
    w.go(3)
    assert time.perf_counter() - start < 5, "História 10 000 záznamov do 5 s"
    assert w.table.rowCount() == 10000


TESTS = {name.upper().replace("_", "-"): fn for name, fn in globals().items() if name.startswith("tc_")}

if __name__ == "__main__":
    results = {}
    for tc_id, fn in sorted(TESTS.items()):
        try:
            fn()
            results[tc_id] = "Prejde"
        except Exception:
            results[tc_id] = "Neprejde: " + traceback.format_exc().strip().splitlines()[-1]
        print(f"{tc_id}: {results[tc_id]}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    sys.exit(0 if all(r == "Prejde" for r in results.values()) else 1)
