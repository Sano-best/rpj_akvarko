"""AquaControl - evidencia meraní kvality vody v akváriu (PyQt6 + SQLite)."""
import json
import math
import os
import sqlite3
import sys
import time
import traceback
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from typing import NamedTuple

from PyQt6.QtCore import QDateTime, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QToolTip, QVBoxLayout, QWidget,
)

try:  # kamera je voliteľná; bez QtMultimedia funguje zvyšok aplikácie
    from PyQt6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
    CAMERA_OK = True
except ImportError:
    CAMERA_OK = False


def data_dir():
    """Priečinok pre databázu a log: vedľa appky (z .exe vedľa .exe, nie do dočasného priečinka PyInstalleru).
    Ak sa tam nedá zapisovať (napr. Program Files), použije sa priečinok AquaControl v domovskom priečinku."""
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    if os.access(base, os.W_OK):
        return base
    fallback = os.path.join(os.path.expanduser("~"), "AquaControl")
    os.makedirs(fallback, exist_ok=True)
    return fallback


DATA_DIR = data_dir()


def resource_path(name):
    """Súbor dodaný spolu s appkou (pri .exe ho PyInstaller rozbalí do dočasného priečinka)."""
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


CATALOG_PATH = resource_path("katalog_ryb.json")
DB_NAME = os.path.join(DATA_DIR, "aquarium.db")
DATE_FMT = "%Y-%m-%d %H:%M:%S"     # formát dátumu v databáze (Python)
QT_DATE_FMT = "yyyy-MM-dd HH:mm:ss"  # ten istý formát pre Qt


class Param(NamedTuple):
    key: str        # názov stĺpca v DB
    name: str
    unit: str
    lo: float       # pod touto hodnotou je výsledok príliš nízky
    note: float     # od tejto hodnoty je „zvýšené, ale ešte v norme“
    warn: float     # od tejto hodnoty sa odporúča zásah (napr. výmena vody)
    hi: float       # od tejto hodnoty je výsledok príliš vysoký (ako „výmena vody od ...“ na obale)
    top: float      # najvyššia hodnota, ktorú vieš zadať
    hint: str       # rada pri „príliš vysoké“
    warn_hint: str  # rada pri „odporúča sa zásah“

    @property
    def title(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name


class Limits(NamedTuple):
    lo: float
    note: float
    warn: float
    hi: float


# Poradie ako na prúžku Tetra Test 6in1. Predvolené hranice vychádzajú z obalu testu (oblasti „O.K.“,
# „Water change“, „Use AquaSafe“) a dajú sa zmeniť v Nastaveniach. Stupeň, ktorý parameter nepotrebuje,
# má rovnakú hodnotu ako „hi“ (potom sa nikdy neuplatní).
PARAMS = [
    Param("no3", "NO₃", "mg/l", 0, 25, 50, 100, 250, "Vymeň časť vody.", "Odporúča sa výmena vody."),
    Param("no2", "NO₂", "mg/l", 0, 1, 1, 5, 250, "Vymeň časť vody a nepridávaj živočíchy.", "Odporúča sa výmena vody."),
    Param("gh", "GH", "°dGH", 4, 20, 20, 20, 250, "", ""),
    Param("kh", "KH", "°dKH", 3, 15, 15, 15, 250, "", ""),
    Param("ph", "pH", "", 6.8, 8.5, 8.5, 8.5, 14, "", ""),
    Param("cl2", "Cl₂", "mg/l", 0, 0.8, 0.8, 0.8, 250, "Použi AquaSafe.", ""),
]
KEYS = [p.key for p in PARAMS]
COLS = ", ".join(KEYS)
SET_COLS = ", ".join(f"{k} = ?" for k in KEYS)
NAMES = {p.key: p.name for p in PARAMS}
NAV = ["Domov", "Zadať merania", "Skenovať test", "História", "Grafy", "Ryby", "Nastavenia"]
PAGE_HOME, PAGE_MANUAL, PAGE_SCAN, PAGE_HISTORY, PAGE_CHARTS, PAGE_FISH, PAGE_SETTINGS = range(7)

# ----- Škála farieb testu Tetra Test 6in1 (hodnota, RGB políčka) -----
# Farby sú odmerané z fotky farebnej škály na obale (po vyrovnaní bielej). Svetlé políčka (NO₃ 0 a 10,
# NO₂ 0 a 1) sú takmer biele, preto sa od seba nedajú spoľahlivo rozlíšiť a appka ich označí ako nejasné.
# Ak chceš škálu doladiť, prepíš farby podľa vlastných skenov.
SCALES = {
    "no3": [(0, (227, 226, 226)), (10, (240, 240, 240)), (25, (210, 187, 191)), (50, (227, 192, 199)), (100, (240, 203, 214)), (250, (233, 145, 188))],
    "no2": [(0, (234, 237, 240)), (1, (240, 232, 230)), (5, (218, 167, 193)), (10, (229, 146, 184))],
    "gh": [(0, (49, 48, 30)), (4, (112, 68, 58)), (8, (154, 46, 36)), (16, (195, 73, 53))],
    "kh": [(0, (148, 124, 39)), (3, (138, 118, 38)), (6, (62, 67, 23)), (10, (49, 64, 24)), (15, (50, 62, 50)), (20, (19, 27, 44))],
    "ph": [(6.4, (207, 164, 51)), (6.8, (223, 132, 47)), (7.2, (198, 68, 33)), (7.6, (226, 58, 43)), (8, (218, 56, 66)), (8.4, (196, 45, 62))],
    "cl2": [(0, (198, 169, 60)), (0.8, (188, 164, 74)), (1.5, (147, 136, 56)), (3, (144, 139, 62))],
}
BRIGHTNESS_WEIGHT = 0.15  # jas farby sa počíta len málo, aby zmena expozície kamery nepokazila výsledok
UNSURE_DISTANCE = 45      # väčší rozdiel farby od škály = hodnota je nejasná
MIN_GAP = 8               # ak je druhý najbližší stupeň takmer rovnako blízko, hodnota je tiež nejasná
DARK_LEVEL, BRIGHT_LEVEL, UNEVEN_RATIO = 70, 230, 0.7  # kontrola osvetlenia

FISH_COLORS = {"ok": "#43a047", "warn": "#e65100", "bad": "#c62828"}
LEVEL_ORDER = {"bad": 0, "warn": 1, "note": 2}
LEVEL_TEXT = {"bad": ("#c62828", "⚠"), "warn": ("#e65100", "⚠"), "note": ("#1e88e5", "ℹ")}   # farba a symbol v texte
LEVEL_CELL = {"bad": ((200, 60, 60), (255, 255, 255)), "warn": ((240, 150, 50), (0, 0, 0)),
              "note": ((255, 236, 160), (0, 0, 0))}                                             # pozadie a písmo v tabuľke

DARK_STYLE = """
QWidget { background-color: #121212; color: #E0E0E0; }
QPushButton { background-color: #1E1E1E; border: 1px solid #444; padding: 8px; }
QPushButton:hover { background-color: #333; }
QLineEdit, QTextEdit, QDoubleSpinBox, QDateTimeEdit, QComboBox, QTableWidget {
    background-color: #1E1E1E; color: white; border: 1px solid #555;
}
QGroupBox { border: 1px solid #444; margin-top: 10px; padding-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; }
"""


# ================= DATABÁZA =================
def db(sql, args=(), fetch=False):
    with closing(sqlite3.connect(DB_NAME)) as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.fetchall() if fetch else None


def db_many(sql, rows):
    """Viac zápisov naraz v jednom pripojení."""
    with closing(sqlite3.connect(DB_NAME)) as conn:
        conn.executemany(sql, rows)
        conn.commit()


def has_measurements():
    return bool(db("SELECT 1 FROM measurements LIMIT 1", fetch=True))


def init_db():
    db("""CREATE TABLE IF NOT EXISTS measurements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
        ph REAL, kh REAL, gh REAL, no2 REAL, no3 REAL, cl2 REAL, note TEXT)""")
    db("""CREATE TABLE IF NOT EXISTS limits (
        key TEXT PRIMARY KEY, min_value REAL, max_value REAL, note_value REAL, warn_value REAL)""")
    db("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    db("""CREATE TABLE IF NOT EXISTS species (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, latin TEXT, grp TEXT,
        temp_min REAL, temp_max REAL, ph_min REAL, ph_max REAL, gh_min REAL, gh_max REAL, kh_min REAL, kh_max REAL,
        no3_max REAL, difficulty INTEGER, note TEXT, source TEXT, custom INTEGER DEFAULT 0)""")
    db("CREATE TABLE IF NOT EXISTS stock (id INTEGER PRIMARY KEY AUTOINCREMENT, species_id TEXT NOT NULL, count INTEGER NOT NULL)")
    import_catalog()
    for col in ("note_value", "warn_value"):  # databáza zo staršej verzie nemá stupne „zvýšené“
        if col not in [r[1] for r in db("PRAGMA table_info(limits)", fetch=True)]:
            db(f"ALTER TABLE limits ADD COLUMN {col} REAL")
    db_many("INSERT OR IGNORE INTO limits (key, min_value, max_value, note_value, warn_value) VALUES (?, ?, ?, ?, ?)",
            [(p.key, p.lo, p.hi, p.note, p.warn) for p in PARAMS])
    limits = get_limits()
    if get_setting("limits_v") != "2":
        # hranice zo starej verzie: horná hranica bola „najviac povolené“, teraz je „od tejto hodnoty je zle“;
        # nezmyselné dvojice (horná nie je nad dolnou, napr. Cl₂ 0 - 0) sa vrátia na predvolené
        db_many("UPDATE limits SET min_value = ?, max_value = ?, note_value = ?, warn_value = ? WHERE key = ?",
                [(p.lo, p.hi, p.note, p.warn, p.key) for p in PARAMS if limits[p.key].hi <= limits[p.key].lo])
        set_setting("limits_v", "2")
        limits = get_limits()
    # stupne pre riadky, ktoré ich ešte nemajú: predvolené, nie však nad vlastnou hornou hranicou
    db_many("UPDATE limits SET note_value = ?, warn_value = ? WHERE key = ?",
            [(min(p.note, min(p.warn, limits[p.key].hi)), min(p.warn, limits[p.key].hi), p.key)
             for p in PARAMS if limits[p.key].note is None or limits[p.key].warn is None])


def get_limits():
    rows = db("SELECT key, min_value, note_value, warn_value, max_value FROM limits", fetch=True)
    return {key: Limits(lo, note, warn, hi) for key, lo, note, warn, hi in rows}


def get_setting(key, default=""):
    rows = db("SELECT value FROM settings WHERE key = ?", (key,), fetch=True)
    return rows[0][0] if rows else default


def set_setting(key, value):
    db("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))


class Finding(NamedTuple):
    level: str  # "bad" = príliš nízke / vysoké, "warn" = odporúča sa zásah, "note" = zvýšené, ale ešte v norme
    text: str
    hint: str


def level(value, lim):
    """Stupeň hodnoty: "ok", "note", "warn" alebo "bad". Hranice „od“ platia vrátane, dolná hranica „pod“."""
    if value < lim.lo or value >= lim.hi:
        return "bad"
    if value >= lim.warn:
        return "warn"
    return "note" if value >= lim.note else "ok"


def check(values, limits):
    """Vráti zoznam Finding pre všetky hodnoty, ktoré nie sú úplne v poriadku (najzávažnejšie prvé)."""
    found = []
    for p in PARAMS:
        lim, v = limits[p.key], values[p.key]
        if v is None:  # chýbajúca hodnota (napr. staršie alebo ručne upravené dáta) sa nevyhodnocuje
            continue
        lv = level(v, lim)
        shown = f"{v:g} {p.unit}".strip()
        if lv == "bad" and v < lim.lo:
            found.append(Finding(lv, f"{p.name} je príliš nízke: {shown} (pod {lim.lo:g} je to už nízke)", ""))
        elif lv == "bad":
            found.append(Finding(lv, f"{p.name} je príliš vysoké: {shown} (od {lim.hi:g} je to už vysoké)", p.hint))
        elif lv == "warn":
            found.append(Finding(lv, f"{p.name} je zvýšené: {shown} (od {lim.warn:g} sa odporúča zásah)", p.warn_hint))
        elif lv == "note":
            found.append(Finding(lv, f"{p.name} je zvýšené, ale ešte v norme: {shown}", ""))
    return sorted(found, key=lambda f: LEVEL_ORDER[f.level])


def fmt(value):
    return "-" if value is None else f"{value:g}"


def write_log(text):
    """Zapíše správu do aquacontroll.log (chyba pri zápise sa ignoruje)."""
    try:
        with open(os.path.join(DATA_DIR, "aquacontroll.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():{DATE_FMT}}\n{text}\n\n")
    except OSError:
        pass


def handle_exception(exc_type, exc, tb):
    """Neočakávaná chyba: zapíše sa do aquacontroll.log a zobrazí sa okno namiesto pádu aplikácie."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    write_log("".join(traceback.format_exception(exc_type, exc, tb)))
    log = os.path.join(DATA_DIR, "aquacontroll.log")
    QMessageBox.critical(None, "Chyba", f"Nastala neočakávaná chyba:\n{exc}\n\nPodrobnosti sú v súbore {log}.")


def days_ago(date_text):
    try:
        days = (datetime.now().date() - datetime.strptime(date_text, DATE_FMT).date()).days
    except ValueError:
        return ""
    return "dnes" if days == 0 else "včera" if days == 1 else f"pred {days} dňami" if days > 1 else ""


# ================= RYBY =================
class Species(NamedTuple):
    id: str
    name: str
    latin: str
    grp: str            # ryba / krevetka ...
    temp: tuple | None  # (od, do) alebo None, ak zdroj hodnotu neuvádza (nekontroluje sa)
    ph: tuple | None
    gh: tuple | None
    kh: tuple | None
    no3_max: float | None
    difficulty: int | None
    note: str
    source: str
    custom: bool


SPECIES_COLS = ("id, name, latin, grp, temp_min, temp_max, ph_min, ph_max, gh_min, gh_max, kh_min, kh_max, "
                "no3_max, difficulty, note, source, custom")
SPECIES_INSERT = f"INSERT OR IGNORE INTO species ({SPECIES_COLS}) VALUES ({', '.join('?' * 17)})"
RANGE_CHECKS = (("temp", "teplota"), ("ph", "pH"), ("gh", "GH"), ("kh", "KH"))  # kľúč v Species, názov
RANGE_UNITS = {"temp": " °C", "ph": "", "gh": " °dGH", "kh": " °dKH"}


def species_values(d):
    """Riadok pre tabuľku species zo záznamu v katalógu (JSON)."""
    def pair(key):
        value = d.get(key)
        return (value[0], value[1]) if value else (None, None)
    return (d["id"], d["name"], d.get("latin", ""), d.get("grp", ""), *pair("temp"), *pair("ph"), *pair("gh"),
            *pair("kh"), d.get("no3_max"), d.get("difficulty"), d.get("note", ""), d.get("source", ""), 0)


def import_catalog(path=None):
    """Doplní do databázy druhy z katalógu; druhy, ktoré v databáze už sú (aj upravené), sa nemenia."""
    try:
        with open(path or CATALOG_PATH, encoding="utf-8") as f:
            items = json.load(f)["druhy"]
        rows = [species_values(d) for d in items]
    except (OSError, ValueError, KeyError, TypeError) as exc:  # appka funguje aj bez katalógu
        write_log(f"Katalóg druhov sa nenačítal: {exc!r}")
        return
    db_many(SPECIES_INSERT, rows)


def get_species():
    def rng(lo, hi):
        return None if lo is None or hi is None else (lo, hi)
    return {r[0]: Species(r[0], r[1], r[2] or "", r[3] or "", rng(r[4], r[5]), rng(r[6], r[7]), rng(r[8], r[9]),
                          rng(r[10], r[11]), r[12], r[13], r[14] or "", r[15] or "", bool(r[16]))
            for r in db(f"SELECT {SPECIES_COLS} FROM species", fetch=True)}


def get_stock():
    """[(id záznamu, Species, počet)] pre druhy v akváriu; druh, ktorý z katalógu zmizol, sa preskočí."""
    species = get_species()
    return [(sid, species[spid], count)
            for sid, spid, count in db("SELECT id, species_id, count FROM stock ORDER BY id", fetch=True)
            if spid in species]


def latest_water():
    """(dátum, hodnoty) posledného merania alebo None."""
    rows = db(f"SELECT date, {COLS} FROM measurements ORDER BY date DESC, id DESC LIMIT 1", fetch=True)
    return (rows[0][0], dict(zip(KEYS, rows[0][1:]))) if rows else None


def species_issues(sp, water):
    """Čo v nameranej vode druhu nevyhovuje (prázdny zoznam = v poriadku; chýbajúce hodnoty sa preskočia)."""
    issues = []
    for key, label in RANGE_CHECKS:
        rng, value = getattr(sp, key), water.get(key)
        if rng is None or value is None:
            continue
        if value < rng[0]:
            issues.append(f"{label} {value:g} je pod {rng[0]:g}")
        elif value > rng[1]:
            issues.append(f"{label} {value:g} je nad {rng[1]:g}")
    nitrate = water.get("no3")
    if sp.no3_max is not None and nitrate is not None and nitrate > sp.no3_max:
        issues.append(f"NO₃ {nitrate:g} je nad {sp.no3_max:g}")
    return issues


def common_ranges(species_list):
    """Pre každý parameter spoločné rozpätie všetkých druhov: {kľúč: (názov, od, do, kto má najvyššie "od", kto najnižšie "do")}.
    Ak je "od" väčšie ako "do", druhy sa v jednom akváriu nezlučujú."""
    out = {}
    for key, label in RANGE_CHECKS:
        items = [(sp, getattr(sp, key)) for sp in species_list if getattr(sp, key) is not None]
        if items:
            lo_sp, lo_rng = max(items, key=lambda i: i[1][0])
            hi_sp, hi_rng = min(items, key=lambda i: i[1][1])
            out[key] = (label, lo_rng[0], hi_rng[1], lo_sp.name, hi_sp.name)
    return out


def fish_lines(species_list, water):
    """Vyhodnotenie vody pre druhy v akváriu: zoznam (stupeň, text), stupeň je "ok", "warn" alebo "bad"."""
    lines = []
    for sp in species_list:
        lines += [("warn", f"{sp.name}: {issue}") for issue in species_issues(sp, water)]
    for label, lo, hi, lo_name, hi_name in common_ranges(species_list).values():
        if lo > hi:
            lines.append(("bad", f"{label}: {lo_name} potrebuje aspoň {lo:g}, ale {hi_name} znesie najviac {hi:g} – "
                                 "tieto druhy sa v jednom akváriu nezlučujú"))
    if not lines and species_list and water:
        lines.append(("ok", "Hodnoty vody vyhovujú všetkým druhom."))
    return lines


def requirement_lines(sp, water):
    """Nároky druhu s aktuálnou hodnotou vody: ["pH: 6 – 8 · teraz 6.4 ⚠", ...]."""
    lines = []
    for key, label in RANGE_CHECKS:
        title = label.capitalize() if label.islower() else label  # „teplota“ -> „Teplota“, „pH“ ostane „pH“
        rng, value = getattr(sp, key), water.get(key)
        if rng is None:
            lines.append(f"{title}: neuvedené")
            continue
        now = "" if value is None else f" · teraz {value:g} {'✔' if rng[0] <= value <= rng[1] else '⚠'}"
        lines.append(f"{title}: {rng[0]:g} – {rng[1]:g}{RANGE_UNITS[key]}{now}")
    if sp.no3_max is not None:
        value = water.get("no3")
        now = "" if value is None else f" · teraz {value:g} {'✔' if value <= sp.no3_max else '⚠'}"
        lines.append(f"NO₃: najviac {sp.no3_max:g} mg/l{now}")
    return lines


def image_path(species_id):
    for ext in ("jpg", "jpeg", "png"):
        path = os.path.join(DATA_DIR, "obrazky", f"{species_id}.{ext}")
        if os.path.exists(path):
            return path
    return None


def save_species_image(species_id, source_path):
    """Uloží fotku druhu zmenšenú na šírku najviac 400 px (JPEG), aby nezaberala veľa miesta. True = uložené."""
    image = QImage(source_path)
    if image.isNull():
        return False
    if image.width() > 400:
        image = image.scaledToWidth(400, Qt.TransformationMode.SmoothTransformation)
    os.makedirs(os.path.join(DATA_DIR, "obrazky"), exist_ok=True)
    return image.save(os.path.join(DATA_DIR, "obrazky", f"{species_id}.jpg"), "JPG", 85)


# ================= SKENOVANIE TESTU (farby) =================
class Reading(NamedTuple):
    key: str
    rgb: tuple      # farba políčka na fotke
    value: float    # odhadnutá hodnota
    ref: tuple      # najbližšia farba zo škály
    sure: bool      # False = farba sa nepodobá stupňu škály alebo sedí na dva stupne naraz


def guide_cells(width, height):
    """Rámik s 6 políčkami vedľa seba (v poradí na prúžku), vycentrovaný v obraze."""
    cell = max(6, int(min(width * 0.84 / 6, height * 0.5)))
    x0, y0 = (width - 6 * cell) // 2, (height - cell) // 2
    return QRect(x0, y0, 6 * cell, cell), [QRect(x0 + i * cell, y0, cell, cell) for i in range(6)]


def center_of(rect):
    return rect.adjusted(rect.width() // 4, rect.height() // 4, -rect.width() // 4, -rect.height() // 4)


def average_color(image, rect):
    small = image.copy(center_of(rect)).scaled(8, 8, Qt.AspectRatioMode.IgnoreAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation)
    colors = [small.pixelColor(x, y) for x in range(8) for y in range(8)]
    return tuple(round(sum(getattr(c, ch)() for c in colors) / 64) for ch in ("red", "green", "blue"))


def color_distance(a, b):
    """Rozdiel dvoch farieb: hlavne odtieň, jas len s malou váhou."""
    sa, sb = sum(a) or 1, sum(b) or 1
    hue = math.dist([255 * x / sa for x in a], [255 * x / sb for x in b])
    return hue + BRIGHTNESS_WEIGHT * abs(sum(a) - sum(b)) / 3


def match_scale(key, rgb):
    """Najbližší stupeň škály: (hodnota, farba stupňa, vzdialenosť, vzdialenosť druhého najbližšieho)."""
    (value, ref), (_, other) = sorted(SCALES[key], key=lambda step: color_distance(step[1], rgb))[:2]
    return value, ref, color_distance(ref, rgb), color_distance(other, rgb)


def analyze_strip(image, keys):
    """Pre každé políčko rámika nájde najbližší stupeň škály. keys = poradie parametrov v rámiku."""
    _, cells = guide_cells(image.width(), image.height())
    readings = {}
    for key, cell in zip(keys, cells):
        rgb = average_color(image, cell)
        value, ref, dist, other = match_scale(key, rgb)
        readings[key] = Reading(key, rgb, value, ref, dist <= UNSURE_DISTANCE and other - dist >= MIN_GAP)
    return readings


def lighting_status(image):
    """(ok, správa): kontrola, či je pri rámiku dosť svetla, nie je odlesk a ani tieň."""
    frame, _ = guide_cells(image.width(), image.height())
    band = frame.adjusted(0, -frame.height(), 0, frame.height()).intersected(image.rect())
    small = image.copy(band).scaled(16, 6, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def lum(x, y):
        c = small.pixelColor(x, y)
        return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()

    left = sum(lum(x, y) for x in range(8) for y in range(6)) / 48
    right = sum(lum(x, y) for x in range(8, 16) for y in range(6)) / 48
    if (left + right) / 2 < DARK_LEVEL:
        return False, "Je tmavo – daj test na viac svetla."
    if (left + right) / 2 > BRIGHT_LEVEL:
        return False, "Je príliš jasno alebo sa v teste odráža svetlo – natoč test inak."
    if min(left, right) < UNEVEN_RATIO * max(left, right):
        return False, "Svetlo je nerovnomerné (tieň) – posuň test alebo svetlo."
    return True, "Osvetlenie je v poriadku."


def draw_guide(image, ok, keys, texts=None):
    """Nakreslí rámik s políčkami a názvami parametrov (zelený = svetlo v poriadku, oranžový = problém)."""
    out = image.copy()
    frame, cells = guide_cells(out.width(), out.height())
    color = QColor("#43a047" if ok else "#ff9800")
    painter = QPainter(out)
    font = QFont()
    font.setPixelSize(max(10, cells[0].height() // 4))
    font.setBold(True)
    painter.setFont(font)
    fh = font.pixelSize() + 6

    def label(rect, text):
        painter.fillRect(rect, QColor(0, 0, 0, 160))
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    painter.setPen(QPen(color, 3))
    painter.drawRect(frame)
    for i, (key, cell) in enumerate(zip(keys, cells)):
        painter.setPen(QPen(color, 2))
        painter.drawRect(center_of(cell))
        label(QRect(cell.x(), cell.y() - fh - 2, cell.width(), fh), NAMES[key])
        if texts:
            label(QRect(cell.x(), cell.bottom() + 3, cell.width(), fh), texts[i])
    painter.end()
    return out


# ================= UI =================
def spin(maximum):
    sb = QDoubleSpinBox()
    sb.setRange(0.0, maximum)
    sb.setDecimals(2)
    sb.setSingleStep(0.1)
    sb.setFixedWidth(120)
    return sb


def swatch(rgb):
    label = QLabel()
    label.setFixedSize(50, 24)
    label.setStyleSheet(f"background-color: rgb{rgb}; border: 1px solid #888;")
    return label


def make_page(title):
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(title)
    label.setStyleSheet("font-size: 22px;")
    layout.addWidget(label)
    return page, layout


class ScanResultDialog(QDialog):
    """Ukáže, ako appka vyhodnotila test, a nechá používateľa hodnoty opraviť."""

    def __init__(self, parent, image, readings, keys, light, note):
        super().__init__(parent)
        self.setWindowTitle("Výsledok skenovania")
        layout = QVBoxLayout(self)

        shown = draw_guide(image.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation), light[0], keys,
                           [f"{readings[k].value:g}" for k in keys])
        pic = QLabel()
        pic.setPixmap(QPixmap.fromImage(shown))
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(pic)

        for text, color in ((light[1], "#43a047" if light[0] else "#ff9800"), (note, None),
                            ("Hodnoty sú odhad z farieb. Skontroluj ich podľa farebnej škály na obale "
                             "a podľa potreby uprav.", None)):
            if text:
                info = QLabel(text)
                info.setWordWrap(True)
                info.setStyleSheet(f"color: {color};" if color else "")
                layout.addWidget(info)

        grid = QGridLayout()
        for col, head in enumerate(("Parameter", "Farba z fotky", "Najbližšia v škále", "Hodnota")):
            grid.addWidget(QLabel(f"<b>{head}</b>"), 0, col)
        self.spins = {}
        for row, p in enumerate(PARAMS, start=1):
            r = readings[p.key]
            self.spins[p.key] = spin(p.top)
            self.spins[p.key].setValue(r.value)
            grid.addWidget(QLabel(p.title), row, 0)
            grid.addWidget(swatch(r.rgb), row, 1)
            grid.addWidget(swatch(r.ref), row, 2)
            grid.addWidget(self.spins[p.key], row, 3)
            if not r.sure:
                grid.addWidget(QLabel("⚠ nejasné – skontroluj"), row, 4)
        layout.addLayout(grid)

        buttons = QDialogButtonBox()
        buttons.addButton("Použiť hodnoty", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Zrušiť", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {key: sb.value() for key, sb in self.spins.items()}


def nice_ticks(low, high, count=6):
    """Okrúhle hodnoty na osi (1, 2, 5 alebo 10 × mocnina desiatky) v rozsahu low až high."""
    raw = (high - low) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 5, 10) if m * magnitude >= raw)
    first = math.ceil(low / step) * step
    return [round(first + i * step, 10) for i in range(int((high - first) / step + 1e-9) + 1)]


def confirm_out_of_range(parent, findings):
    """Ak je niektorá hodnota „príliš nízka / vysoká“, opýta sa, či ju uložiť aj tak. True = pokračovať."""
    bad = [f for f in findings if f.level == "bad"]
    if not bad:
        return True
    text = "\n".join(f"• {f.text}" for f in bad)
    answer = QMessageBox.warning(
        parent, "Hodnota mimo rozsahu", f"{text}\n\nUložiť meranie aj tak?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


class MeasurementForm(QWidget):
    """Formulár merania (dátum a čas, hodnoty, poznámka) pre nové meranie aj pre úpravu."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.date = QDateTimeEdit(QDateTime.currentDateTime())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy HH:mm")
        form.addRow("Dátum a čas:", self.date)
        self.inputs = {p.key: spin(p.top) for p in PARAMS}
        for p in PARAMS:
            form.addRow(f"{p.title}:", self.inputs[p.key])
        layout.addLayout(form)
        self.note = QTextEdit()
        self.note.setPlaceholderText("Poznámka (voliteľné)")
        layout.addWidget(self.note)

    def values(self):
        return {key: sb.value() for key, sb in self.inputs.items()}

    def date_text(self):
        return self.date.dateTime().toString(QT_DATE_FMT)

    def set_measurement(self, date_text, values, note):
        when = QDateTime.fromString(date_text, QT_DATE_FMT)
        self.date.setDateTime(when if when.isValid() else QDateTime.currentDateTime())
        for key, sb in self.inputs.items():
            sb.setValue(values.get(key) or 0)
        self.note.setPlainText(note or "")

    def reset(self):
        self.set_measurement("", {}, "")


class EditDialog(QDialog):
    """Úprava uloženého merania. Pri hodnote mimo hraníc sa pred uložením opýta rovnako ako pri novom meraní."""

    def __init__(self, parent, record):
        super().__init__(parent)
        self.setWindowTitle("Upraviť meranie")
        self.setMinimumWidth(420)
        _, date, *values, note = record
        layout = QVBoxLayout(self)
        self.form = MeasurementForm()
        self.form.set_measurement(date, dict(zip(KEYS, values)), note)
        layout.addWidget(self.form)
        buttons = QDialogButtonBox()
        buttons.addButton("Uložiť zmeny", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Zrušiť", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if confirm_out_of_range(self, check(self.form.values(), get_limits())):
            super().accept()


class LineChart(QWidget):
    """Čiarový graf vykreslený cez QPainter (bez ďalších knižníc). Pozadie tvoria pásma podľa hraníc."""
    ZONES = {"ok": (46, 125, 50, 45), "note": (255, 235, 59, 80), "warn": (255, 152, 0, 70), "bad": (211, 47, 47, 60)}
    POINTS = {"ok": (46, 125, 50), "note": (251, 192, 45), "warn": (245, 124, 0), "bad": (198, 40, 40)}

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 260)
        self.setMouseTracking(True)
        self.points, self.limits, self.unit, self.dark = [], None, "", False
        self.hits = []  # (poloha bodu, text do bubliny)

    def set_data(self, points, limits, unit=""):
        self.points, self.limits, self.unit = points, limits, unit
        self.update()

    def y_range(self):
        values = [v for _, v in self.points]
        low, high = min(values), max(values)
        pad = (high - low) * 0.15 or max(abs(high) * 0.1, 1)
        return (0 if low >= 0 and low - pad < 0 else low - pad), high + pad  # hodnoty nikdy nie sú záporné

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1e1e1e" if self.dark else "white"))
        text = QColor("#e0e0e0" if self.dark else "#222222")
        grid = QColor("#555555" if self.dark else "#d0d0d0")
        self.hits = []
        painter.setPen(text)
        if not self.points:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Pre toto obdobie nie sú žiadne merania.")
            return
        area = QRectF(60, 16, self.width() - 80, self.height() - 56)
        y0, y1 = self.y_range()
        t0, t1 = self.points[0][0], self.points[-1][0]
        span = (t1 - t0).total_seconds()

        def px(t):
            return area.center().x() if span == 0 else area.left() + (t - t0).total_seconds() / span * area.width()

        def py(v):
            return area.bottom() - (v - y0) / (y1 - y0) * area.height()

        lim = self.limits
        for a, b, kind in ((-math.inf, lim.lo, "bad"), (lim.lo, lim.note, "ok"), (lim.note, lim.warn, "note"),
                           (lim.warn, lim.hi, "warn"), (lim.hi, math.inf, "bad")):
            a, b = max(a, y0), min(b, y1)
            if a < b:
                painter.fillRect(QRectF(area.left(), py(b), area.width(), py(a) - py(b)), QColor(*self.ZONES[kind]))

        align = Qt.AlignmentFlag
        for v in nice_ticks(y0, y1):  # vodorovné čiary s okrúhlymi hodnotami
            painter.setPen(grid)
            painter.drawLine(QPointF(area.left(), py(v)), QPointF(area.right(), py(v)))
            painter.setPen(text)
            painter.drawText(QRectF(0, py(v) - 10, area.left() - 6, 20), align.AlignRight | align.AlignVCenter, f"{v:.3g}")
        day_format = "%d.%m." if span >= 2 * 86400 else "%d.%m. %H:%M"
        for i in range(1 if span == 0 else 6):  # popisky času
            t = t0 + (t1 - t0) * i / 5
            painter.drawText(QRectF(px(t) - 45, area.bottom() + 6, 90, 20), align.AlignCenter, t.strftime(day_format))

        points = [QPointF(px(t), py(v)) for t, v in self.points]
        painter.setPen(QPen(QColor(31, 119, 180), 2))
        for a, b in zip(points, points[1:]):
            painter.drawLine(a, b)
        painter.setPen(QPen(QColor("#1e1e1e" if self.dark else "white"), 1))
        for pt, (t, v) in zip(points, self.points):
            painter.setBrush(QColor(*self.POINTS[level(v, lim)]))
            painter.drawEllipse(pt, 5, 5)
            self.hits.append((pt, f"{t:%d.%m.%Y %H:%M} – {v:g} {self.unit}".strip()))

    def mouseMoveEvent(self, event):
        pos = event.position()
        near = min(self.hits, key=lambda hit: (hit[0] - pos).manhattanLength(), default=None)
        if near and (near[0] - pos).manhattanLength() < 16:
            QToolTip.showText(event.globalPosition().toPoint(), near[1], self)
        else:
            QToolTip.hideText()


class AddSpeciesDialog(QDialog):
    """Výber druhu z katalógu (ide písať do poľa a hľadať) a počet kusov."""

    def __init__(self, parent, species):
        super().__init__(parent)
        self.setWindowTitle("Pridať druh")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for sp in sorted(species.values(), key=lambda s: s.name.lower()):
            self.combo.addItem(f"{sp.name} ({sp.latin})" if sp.latin else sp.name, sp.id)
        self.combo.setCurrentIndex(-1)
        self.count = QSpinBox()
        self.count.setRange(1, 9999)
        form.addRow("Druh:", self.combo)
        form.addRow("Počet kusov:", self.count)
        buttons = QDialogButtonBox()
        buttons.addButton("Pridať", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Zrušiť", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def chosen(self):
        """(id druhu, počet) alebo None, ak v poli nie je druh zo zoznamu."""
        index = self.combo.findText(self.combo.currentText())
        return (self.combo.itemData(index), self.count.value()) if index >= 0 else None

    def accept(self):
        if self.chosen() is None:
            QMessageBox.warning(self, "Druh", "Vyber druh zo zoznamu (môžeš začať písať jeho názov).")
            return
        super().accept()


def optional_spin(top):
    """Číselné pole, v ktorom minimum znamená „neuvedené“ (hodnota sa potom nekontroluje)."""
    sb = spin(top)
    sb.setRange(-1.0, top)
    sb.setSpecialValueText("neuvedené")
    sb.setValue(-1.0)
    return sb


class CustomSpeciesDialog(QDialog):
    """Vlastný druh, ktorý nie je v katalógu: názov a rozpätia parametrov."""
    FIELDS = (("temp", "Teplota (°C)", 45), ("ph", "pH", 14), ("gh", "GH (°dGH)", 60), ("kh", "KH (°dKH)", 60))

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Vlastný druh")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name, self.latin = QLineEdit(), QLineEdit()
        self.count = QSpinBox()
        self.count.setRange(1, 9999)
        form.addRow("Názov druhu:", self.name)
        form.addRow("Latinský názov:", self.latin)
        form.addRow("Počet kusov:", self.count)
        self.ranges = {}
        for key, label, top in self.FIELDS:
            row = QHBoxLayout()
            self.ranges[key] = (optional_spin(top), optional_spin(top))
            for text, box in zip(("od", "do"), self.ranges[key]):
                row.addWidget(QLabel(text))
                row.addWidget(box)
            row.addStretch()
            form.addRow(f"{label}:", row)
        layout.addLayout(form)
        layout.addWidget(QLabel("Parameter, ktorý nepoznáš, nechaj „neuvedené“ – nebude sa kontrolovať."))
        buttons = QDialogButtonBox()
        buttons.addButton("Pridať druh", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Zrušiť", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        problem = "" if self.name.text().strip() else "Zadaj názov druhu."
        for key, label, _ in self.FIELDS:
            lo, hi = (box.value() for box in self.ranges[key])
            if (lo < 0) != (hi < 0):
                problem = f"{label}: zadaj „od“ aj „do“, alebo nechaj obe neuvedené."
            elif lo > hi:
                problem = f"{label}: „od“ musí byť menšie alebo rovnaké ako „do“."
        if problem:
            QMessageBox.warning(self, "Vlastný druh", problem)
            return
        super().accept()

    def species_row(self):
        """Riadok pre tabuľku species."""
        def pair(key):
            lo, hi = (box.value() for box in self.ranges[key])
            return (lo, hi) if lo >= 0 else (None, None)
        return (f"vlastny-{uuid.uuid4().hex[:8]}", self.name.text().strip(), self.latin.text().strip(), "vlastný druh",
                *pair("temp"), *pair("ph"), *pair("gh"), *pair("kh"), None, None, "Vlastný druh.", "vlastné údaje", 1)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AquaControl")
        self.setMinimumSize(900, 600)
        self.camera = self.last_frame = None
        self.last_frame_time = 0.0
        self.deleted = []  # vymazané merania, ktoré sa dajú vrátiť (posledné je na konci)
        init_db()
        self.dark = get_setting("dark_mode") == "1"

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        menu = QVBoxLayout()
        self.pages = QStackedWidget()

        builders = (self.home_page, self.manual_page, self.scan_page, self.history_page, self.charts_page,
                    self.fish_page, self.settings_page)
        for i, (text, build) in enumerate(zip(NAV, builders)):
            btn = QPushButton(text)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _, i=i: self.go(i))
            menu.addWidget(btn)
            self.pages.addWidget(build())

        menu.addStretch()
        main_layout.addLayout(menu, 1)
        main_layout.addWidget(self.pages, 4)
        self.apply_theme()
        self.go(PAGE_HOME)

    def go(self, index):
        if index != PAGE_SCAN:
            self.stop_camera()
        if index == PAGE_HOME:
            self.refresh_home()
        elif index in (PAGE_HISTORY, PAGE_CHARTS):
            if not has_measurements() and not (index == PAGE_HISTORY and self.deleted):  # po vymazaní ide vrátiť späť
                QMessageBox.information(self, NAV[index], "Zatiaľ nie sú žiadne merania.")
                return
            if index == PAGE_HISTORY:
                self.load_history()
            else:
                self.refresh_chart()
        elif index == PAGE_FISH:
            self.load_fish()
        elif index == PAGE_SETTINGS:
            self.load_settings_form()
        self.pages.setCurrentIndex(index)

    def closeEvent(self, event):
        self.stop_camera()
        super().closeEvent(event)

    # ----- Domov -----
    def home_page(self):
        page, layout = make_page("Stav akvária")
        self.home_label = QLabel()
        self.home_label.setWordWrap(True)
        self.home_label.setTextFormat(Qt.TextFormat.RichText)
        self.home_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_label.setStyleSheet("font-size: 18px;")
        layout.addWidget(self.home_label, 1)
        return page

    def refresh_home(self):
        latest = latest_water()
        if not latest:
            self.home_label.setText("Zatiaľ nie sú žiadne merania")
            return
        date, water = latest
        findings = check(water, get_limits())
        ago = days_ago(date)
        lines = [f"Posledné meranie: {date}" + (f" ({ago})" if ago else ""),
                 "&nbsp;&nbsp;&nbsp; ".join(f"{p.name} {fmt(water[p.key])} {p.unit}".strip() for p in PARAMS), ""]
        if all(f.level == "note" for f in findings):
            lines.append("<span style='color:#43a047'>✔ Všetky hodnoty sú v norme</span>")
        for f in findings:
            color, icon = LEVEL_TEXT[f.level]
            lines.append(f"<span style='color:{color}'>{icon} {f.text}" + (f" → {f.hint}" if f.hint else "") + "</span>")
        stock = get_stock()
        if stock:  # ryby v akváriu: najviac 4 riadky, zvyšok je na záložke Ryby
            fish = fish_lines([sp for _, sp, _ in stock], water)
            lines.append("")
            for level_, text in fish[:4]:
                lines.append(f"<span style='color:{FISH_COLORS[level_]}'>🐟 {text}</span>")
            if len(fish) > 4:
                lines.append(f"<span style='color:{FISH_COLORS['warn']}'>🐟 …a ďalšie ({len(fish) - 4}), pozri záložku Ryby</span>")
        self.home_label.setText("<br>".join(lines))

    # ----- Zadať merania -----
    def manual_page(self):
        page, layout = make_page("Manuálne zadanie meraní (Tetra Test 6in1)")
        self.form = MeasurementForm()
        self.input_date, self.inputs, self.input_note = self.form.date, self.form.inputs, self.form.note
        layout.addWidget(self.form)
        btn = QPushButton("Uložiť meranie")
        btn.clicked.connect(self.save_measurement)
        layout.addWidget(btn)
        return page

    def save_measurement(self):
        values = self.form.values()
        findings = check(values, get_limits())
        if not confirm_out_of_range(self, findings):
            return
        placeholders = ", ".join("?" * (len(PARAMS) + 2))
        db(f"INSERT INTO measurements (date, {COLS}, note) VALUES ({placeholders})",
           (self.form.date_text(), *(values[k] for k in KEYS), self.form.note.toPlainText()))
        self.form.reset()
        soft = [f"• {f.text}" + (f" → {f.hint}" if f.hint else "") for f in findings if f.level != "bad"]
        QMessageBox.information(self, "Uložené", "Meranie bolo uložené do databázy."
                                + ("\n\nPozor:\n" + "\n".join(soft) if soft else ""))

    # ----- Skenovať test (kamera alebo fotka) -----
    def scan_page(self):
        page, layout = make_page("Skenovanie testového prúžku")
        hint = QLabel("Polož prúžok na biely podklad do rámika tak, aby každé políčko prúžku sedelo na jednom "
                      "poli (NO₃, NO₂, GH, KH, pH, Cl₂). Pred skenovaním počkaj čas uvedený na obale testu.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.preview = QLabel("Kamera je vypnutá")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("font-size: 18px; color: gray; border: 1px solid #888;")
        self.preview.setMinimumSize(480, 300)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.preview, 1)

        self.light_label = QLabel()
        self.light_label.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.light_label)

        row = QHBoxLayout()
        self.btn_camera = QPushButton("📷 Zapnúť kameru")
        self.btn_camera.clicked.connect(self.toggle_camera)
        self.btn_snap = QPushButton("Nasnímať a vyhodnotiť")
        self.btn_snap.setEnabled(False)
        self.btn_snap.clicked.connect(self.scan_snapshot)
        btn_import = QPushButton("🖼 Importovať fotku")
        btn_import.clicked.connect(self.import_photo)
        for b in (self.btn_camera, self.btn_snap, btn_import):
            b.setMinimumHeight(40)
            row.addWidget(b)
        layout.addLayout(row)

        self.chk_reverse = QCheckBox("Obrátiť poradie políčok (prúžok je položený opačne)")
        layout.addWidget(self.chk_reverse)
        if not CAMERA_OK:
            self.btn_camera.setEnabled(False)
            self.light_label.setText("Kamera nie je v tejto inštalácii dostupná – použi import fotky.")
        return page

    def strip_keys(self):
        return KEYS[::-1] if self.chk_reverse.isChecked() else list(KEYS)

    def toggle_camera(self):
        if self.camera:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        device = QMediaDevices.defaultVideoInput()
        if device.isNull():
            QMessageBox.warning(self, "Kamera", "Nenašla sa žiadna kamera. Pripoj kameru alebo použi „Importovať fotku“.")
            return
        self.camera = QCamera(device)
        self.session = QMediaCaptureSession()
        self.sink = QVideoSink()
        self.session.setCamera(self.camera)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self.on_frame)
        self.camera.errorOccurred.connect(self.on_camera_error)
        self.camera.start()
        self.btn_camera.setText("⏹ Vypnúť kameru")
        self.preview.setText("Čakám na obraz z kamery…")

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
            self.camera = None
        self.last_frame = None
        if hasattr(self, "btn_camera"):
            self.btn_camera.setText("📷 Zapnúť kameru")
            self.btn_snap.setEnabled(False)
            self.preview.clear()
            self.preview.setText("Kamera je vypnutá")
            self.light_label.clear()

    def on_camera_error(self, error, text):
        self.stop_camera()
        QMessageBox.warning(self, "Kamera", f"Kameru sa nepodarilo použiť: {text}\n"
                            "Skontroluj, či ju nepoužíva iná aplikácia a či je povolená v nastaveniach Windows.")

    def on_frame(self, frame):
        if time.monotonic() - self.last_frame_time < 0.07:  # približne 14 snímok za sekundu stačí
            return
        self.last_frame_time = time.monotonic()
        image = frame.toImage()
        if not image.isNull():
            self.show_frame(image.convertToFormat(QImage.Format.Format_RGB32))

    def show_frame(self, image):
        """Zobrazí snímku s rámikom a skontroluje osvetlenie."""
        self.last_frame = image
        ok, message = lighting_status(image)
        self.light_label.setText(message)
        self.light_label.setStyleSheet(f"font-size: 15px; color: {'#43a047' if ok else '#ff9800'};")
        guide = draw_guide(image.scaledToWidth(640), ok, self.strip_keys())
        self.preview.setPixmap(QPixmap.fromImage(guide).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        self.btn_snap.setEnabled(True)

    def scan_snapshot(self):
        if self.last_frame is None:
            return
        ok, message = lighting_status(self.last_frame)
        if not ok:
            answer = QMessageBox.question(
                self, "Osvetlenie", f"{message}\n\nVýsledok bude nepresný. Vyhodnotiť aj tak?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.show_scan_result(self.last_frame, "Vyhodnotila sa farba v strede každého políčka rámika.")

    def import_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Vyberte fotku testovacieho prúžku", "", "Obrázky (*.png *.jpg *.jpeg)")
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            QMessageBox.warning(self, "Chyba", "Obrázok sa nepodarilo načítať.")
            return
        self.show_scan_result(image.convertToFormat(QImage.Format.Format_RGB32),
                              "Pri fotke sa vyhodnotil rámik v strede obrázka. Ak políčka nesedia na prúžok, "
                              "hodnoty uprav ručne alebo vyfoť prúžok znova tak, aby bol v strede.")

    def show_scan_result(self, image, note):
        keys = self.strip_keys()
        dialog = ScanResultDialog(self, image, analyze_strip(image, keys), keys, lighting_status(image), note)
        if dialog.exec() == QDialog.DialogCode.Accepted:  # nič sa neukladá, hodnoty sa len predvyplnia
            for key, value in dialog.values().items():
                self.inputs[key].setValue(value)
            self.go(PAGE_MANUAL)
            QMessageBox.information(self, "Hodnoty predvyplnené",
                                    "Hodnoty sú predvyplnené vo formulári. Skontroluj ich a stlač „Uložiť meranie“.")

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
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_selected_measurement())
        layout.addWidget(self.table)

        row = QHBoxLayout()
        btn_edit = QPushButton("✏ Upraviť vybrané meranie")
        btn = QPushButton("🗑 Vymazať vybrané meranie")
        self.btn_undo = QPushButton("↩ Vrátiť posledné vymazanie")
        btn_edit.clicked.connect(self.edit_selected_measurement)
        btn.clicked.connect(self.delete_selected_measurement)
        self.btn_undo.clicked.connect(self.undo_delete)
        self.btn_undo.setEnabled(False)
        for b in (btn_edit, btn, self.btn_undo):
            b.setMinimumHeight(35)
            row.addWidget(b)
        layout.addLayout(row)
        return page

    def load_history(self):
        rows = db(f"SELECT id, date, {COLS}, note FROM measurements ORDER BY date DESC, id DESC", fetch=True)
        limits = get_limits()
        self.table.setUpdatesEnabled(False)  # bez prekresľovania po každej bunke je plnenie rýchlejšie
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else f"{val:g}" if isinstance(val, float) else str(val))
                if 2 <= c < 2 + len(PARAMS) and val is not None:
                    lv = level(val, limits[PARAMS[c - 2].key])
                    if lv != "ok":  # farba bunky podľa stupňa: červená, oranžová, žltá
                        background, foreground = LEVEL_CELL[lv]
                        item.setBackground(QColor(*background))
                        item.setForeground(QColor(*foreground))
                self.table.setItem(r, c, item)
        self.table.setUpdatesEnabled(True)

    def selected_measurement_id(self):
        """ID vybraného merania; ak nie je nič vybrané, upozorní a vráti None."""
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Chyba", "Najprv vyber meranie v tabuľke.")
            return None
        return int(self.table.item(row, 0).text())

    def select_measurement(self, measurement_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == str(measurement_id):
                self.table.selectRow(row)
                return

    def edit_selected_measurement(self):
        measurement_id = self.selected_measurement_id()
        if measurement_id is None:
            return
        record = db(f"SELECT id, date, {COLS}, note FROM measurements WHERE id = ?", (measurement_id,), fetch=True)[0]
        dialog = EditDialog(self, record)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.form.values()
        db(f"UPDATE measurements SET date = ?, {SET_COLS}, note = ? WHERE id = ?",
           (dialog.form.date_text(), *(values[k] for k in KEYS), dialog.form.note.toPlainText(), measurement_id))
        self.load_history()
        self.select_measurement(measurement_id)

    def delete_selected_measurement(self):
        measurement_id = self.selected_measurement_id()
        if measurement_id is None:
            return
        record = db(f"SELECT id, date, {COLS}, note FROM measurements WHERE id = ?", (measurement_id,), fetch=True)[0]
        answer = QMessageBox.question(
            self, "Potvrdenie vymazania", f"Naozaj chceš vymazať meranie z {record[1]}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.deleted.append(record)
            db("DELETE FROM measurements WHERE id = ?", (measurement_id,))
            self.load_history()
            self.btn_undo.setEnabled(True)

    def undo_delete(self):
        if not self.deleted:
            return
        placeholders = ", ".join("?" * (len(PARAMS) + 3))
        db(f"INSERT INTO measurements (id, date, {COLS}, note) VALUES ({placeholders})", self.deleted.pop())
        self.load_history()
        self.btn_undo.setEnabled(bool(self.deleted))

    # ----- Grafy -----
    def charts_page(self):
        page, layout = make_page("Grafy")
        row = QHBoxLayout()
        self.chart_param, self.chart_period = QComboBox(), QComboBox()
        for p in PARAMS:
            self.chart_param.addItem(p.title, p.key)
        for text, days in (("Posledných 7 dní", 7), ("Posledných 30 dní", 30), ("Posledných 90 dní", 90),
                           ("Celá história", None)):
            self.chart_period.addItem(text, days)
        self.chart_period.setCurrentIndex(3)
        for label, box in (("Parameter:", self.chart_param), ("Obdobie:", self.chart_period)):
            row.addWidget(QLabel(label))
            row.addWidget(box)
            box.currentIndexChanged.connect(self.refresh_chart)
        row.addStretch()
        layout.addLayout(row)
        self.chart = LineChart()
        layout.addWidget(self.chart, 1)
        self.chart_stats = QLabel()
        self.chart_stats.setWordWrap(True)
        layout.addWidget(self.chart_stats)
        legend = QLabel("Pozadie: zelená = v norme, žltá = zvýšené, oranžová = odporúča sa zásah, červená = príliš "
                        "nízke alebo vysoké (podľa hraníc v Nastaveniach). Pohni myšou nad bodom pre jeho hodnotu.")
        legend.setWordWrap(True)
        legend.setStyleSheet("color: gray;")
        layout.addWidget(legend)
        return page

    def refresh_chart(self):
        key, days = self.chart_param.currentData(), self.chart_period.currentData()
        param = next(p for p in PARAMS if p.key == key)
        sql, args = f"SELECT date, {key} FROM measurements WHERE {key} IS NOT NULL", ()
        if days:
            sql += " AND date >= ?"
            args = ((datetime.now() - timedelta(days=days)).strftime(DATE_FMT),)
        points = []
        for date, value in db(sql + " ORDER BY date", args, fetch=True):
            try:
                points.append((datetime.strptime(date, DATE_FMT), value))
            except ValueError:  # zlý formát dátumu sa preskočí
                pass
        self.chart.set_data(points, get_limits()[key], param.unit)
        if not points:
            self.chart_stats.clear()
            return
        values, unit = [v for _, v in points], f" {param.unit}" if param.unit else ""
        self.chart_stats.setText(
            f"Meraní: {len(values)}   minimum: {min(values):g}{unit}   maximum: {max(values):g}{unit}   "
            f"priemer: {sum(values) / len(values):.2f}{unit}   posledné: {values[-1]:g}{unit} ({points[-1][0]:%d.%m.%Y})")

    # ----- Ryby -----
    def fish_page(self):
        page, layout = make_page("Ryby v akváriu")
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.fish_table = QTableWidget(0, 4)
        self.fish_table.setHorizontalHeaderLabels(["ID", "Druh", "Počet", "Voda"])
        self.fish_table.setColumnHidden(0, True)
        self.fish_table.verticalHeader().setVisible(False)
        self.fish_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.fish_table.horizontalHeader().setStretchLastSection(True)
        self.fish_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fish_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.fish_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.fish_table.itemSelectionChanged.connect(self.show_fish_detail)
        self.fish_table.cellDoubleClicked.connect(lambda *_: self.change_fish_count())
        left.addWidget(self.fish_table, 1)
        row = QHBoxLayout()
        for text, handler in (("➕ Pridať druh", self.add_fish), ("🔢 Zmeniť počet", self.change_fish_count),
                              ("🗑 Odstrániť", self.remove_fish), ("🆕 Vlastný druh", self.add_custom_fish)):
            btn = QPushButton(text)
            btn.setMinimumHeight(35)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        left.addLayout(row)
        self.fish_summary = QLabel()
        self.fish_summary.setWordWrap(True)
        self.fish_summary.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(self.fish_summary)

        right = QVBoxLayout()
        self.fish_image = QLabel("Bez fotky")
        self.fish_image.setFixedSize(260, 190)
        self.fish_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fish_image.setStyleSheet("color: gray; border: 1px solid #888;")
        self.fish_info = QLabel()
        self.fish_info.setWordWrap(True)
        self.fish_info.setTextFormat(Qt.TextFormat.RichText)
        self.fish_info.setAlignment(Qt.AlignmentFlag.AlignTop)
        btn_photo = QPushButton("📷 Nastaviť fotku")
        btn_photo.clicked.connect(self.set_fish_photo)
        right.addWidget(self.fish_image)
        right.addWidget(btn_photo)
        right.addWidget(self.fish_info, 1)
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        layout.addLayout(body)
        return page

    def load_fish(self):
        stock, latest = get_stock(), latest_water()
        water = latest[1] if latest else {}
        self.fish_table.setRowCount(len(stock))
        for r, (stock_id, sp, count) in enumerate(stock):
            issues = species_issues(sp, water)
            status, color = (("bez merania", None) if not latest else
                             ("; ".join(issues), FISH_COLORS["warn"]) if issues else ("✔ v poriadku", FISH_COLORS["ok"]))
            for c, text in enumerate((str(stock_id), sp.name, str(count), status)):
                item = QTableWidgetItem(text)
                if c == 3 and color:
                    item.setForeground(QColor(color))
                self.fish_table.setItem(r, c, item)
        lines = [f"<span style='color:{FISH_COLORS[lv]}'>{text}</span>" for lv, text in fish_lines([sp for _, sp, _ in stock], water)]
        if len(stock) > 1:
            common = [f"{label} {lo:g} – {hi:g}" for label, lo, hi, _, _ in common_ranges([sp for _, sp, _ in stock]).values() if lo <= hi]
            if common:
                lines.insert(0, "Spoločné rozpätie všetkých druhov: " + ", ".join(common))
        if stock and not latest:
            lines.append("Zatiaľ nie je žiadne meranie – vodu nie je s čím porovnať.")
        elif latest:
            lines.append(f"<small>Podľa merania z {latest[0]}</small>")
        self.fish_summary.setText("<br>".join(lines) if stock else "Zatiaľ si nepridal žiadny druh. Použi „Pridať druh“.")
        self.show_fish_detail()

    def selected_fish(self):
        """(id záznamu, Species) vybraného riadku alebo None."""
        row = self.fish_table.currentRow()
        if row < 0:
            return None
        stock_id = int(self.fish_table.item(row, 0).text())
        return next(((sid, sp) for sid, sp, _ in get_stock() if sid == stock_id), None)

    def show_fish_detail(self):
        chosen = self.selected_fish()
        if not chosen:
            self.fish_image.clear()
            self.fish_image.setText("Bez fotky")
            self.fish_info.setText("Vyber druh v tabuľke.")
            return
        sp = chosen[1]
        latest = latest_water()
        path = image_path(sp.id)
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.fish_image.clear()
            self.fish_image.setText("Bez fotky")
        else:
            self.fish_image.setPixmap(pixmap.scaled(self.fish_image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                    Qt.TransformationMode.SmoothTransformation))
        hard = f"<br>Náročnosť chovu: {sp.difficulty} z 5" if sp.difficulty else ""
        self.fish_info.setText(
            f"<b>{sp.name}</b><br><i>{sp.latin}</i>{hard}<br><br>"
            + "<br>".join(requirement_lines(sp, latest[1] if latest else {}))
            + f"<br><br><small>{sp.note}<br>Zdroj: {sp.source}</small>")

    def add_fish(self):
        species = get_species()
        if not species:
            QMessageBox.information(self, "Ryby", "Katalóg druhov je prázdny. Pridaj vlastný druh.")
            return
        dialog = AddSpeciesDialog(self, species)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        species_id, count = dialog.chosen()
        have = db("SELECT count FROM stock WHERE species_id = ?", (species_id,), fetch=True)
        if have:
            QMessageBox.information(self, "Ryby", f"Tento druh už máš v zozname ({have[0][0]} ks). "
                                    "Počet zmeníš tlačidlom „Zmeniť počet“.")
            return
        db("INSERT INTO stock (species_id, count) VALUES (?, ?)", (species_id, count))
        self.load_fish()

    def change_fish_count(self):
        chosen = self.selected_fish()
        if not chosen:
            QMessageBox.warning(self, "Chyba", "Najprv vyber druh v tabuľke.")
            return
        stock_id, sp = chosen
        current = db("SELECT count FROM stock WHERE id = ?", (stock_id,), fetch=True)[0][0]
        count, ok = QInputDialog.getInt(self, "Zmeniť počet", f"Počet kusov ({sp.name}):", current, 1, 9999)
        if ok:
            db("UPDATE stock SET count = ? WHERE id = ?", (count, stock_id))
            self.load_fish()

    def remove_fish(self):
        chosen = self.selected_fish()
        if not chosen:
            QMessageBox.warning(self, "Chyba", "Najprv vyber druh v tabuľke.")
            return
        answer = QMessageBox.question(self, "Odstrániť druh", f"Odstrániť {chosen[1].name} zo zoznamu rýb v akváriu?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            db("DELETE FROM stock WHERE id = ?", (chosen[0],))
            self.load_fish()

    def add_custom_fish(self):
        dialog = CustomSpeciesDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = dialog.species_row()
        db(SPECIES_INSERT, row)
        db("INSERT INTO stock (species_id, count) VALUES (?, ?)", (row[0], dialog.count.value()))
        self.load_fish()

    def set_fish_photo(self):
        chosen = self.selected_fish()
        if not chosen:
            QMessageBox.warning(self, "Chyba", "Najprv vyber druh v tabuľke.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Vyberte fotku druhu", "", "Obrázky (*.png *.jpg *.jpeg)")
        if not path:
            return
        if not save_species_image(chosen[1].id, path):
            QMessageBox.warning(self, "Chyba", "Obrázok sa nepodarilo načítať.")
            return
        self.show_fish_detail()

    # ----- Nastavenia -----
    def settings_page(self):
        page, layout = make_page("Nastavenia")

        look = QGroupBox("Vzhľad")
        look_layout = QVBoxLayout(look)
        self.btn_theme = QPushButton()
        self.btn_theme.setMinimumHeight(40)
        self.btn_theme.clicked.connect(self.toggle_theme)
        hint = QLabel("Režim sa prepne hneď. Tlačidlom „Uložiť nastavenia“ sa zapamätá aj pre ďalšie spustenie.")
        hint.setWordWrap(True)
        btn_prefs = QPushButton("Uložiť nastavenia")
        btn_prefs.clicked.connect(self.save_settings)
        look_layout.addWidget(self.btn_theme)
        look_layout.addWidget(hint)
        look_layout.addWidget(btn_prefs)
        layout.addWidget(look)

        limits = QGroupBox("Hranice hodnôt (kedy appka upozorní)")
        limits_layout = QVBoxLayout(limits)
        explain = QLabel("Pod „Nízke pod“ je hodnota príliš nízka. Od „Zvýšené od“ je zvýšená, ale ešte v norme, od "
                         "„Odporúča sa zásah od“ sa odporúča zasiahnuť (napr. vymeniť vodu) a od „Príliš vysoké od“ je "
                         "už príliš vysoká. Stupeň, ktorý nepotrebuješ, nastav rovnako ako „Príliš vysoké od“.")
        explain.setWordWrap(True)
        limits_layout.addWidget(explain)
        grid = QGridLayout()
        self.limit_inputs = {}
        for col, head in enumerate(("Nízke pod", "Zvýšené od", "Odporúča sa zásah od", "Príliš vysoké od"), start=1):
            label = QLabel(f"<b>{head}</b>")
            label.setWordWrap(True)
            grid.addWidget(label, 0, col)
        for row, p in enumerate(PARAMS, start=1):
            grid.addWidget(QLabel(p.title), row, 0)
            self.limit_inputs[p.key] = {name: spin(p.top) for name in Limits._fields}
            for col, name in enumerate(Limits._fields, start=1):
                grid.addWidget(self.limit_inputs[p.key][name], row, col)
        limits_layout.addLayout(grid)
        btn_limits = QPushButton("Uložiť hranice")
        btn_limits.clicked.connect(self.save_limits)
        limits_layout.addWidget(btn_limits)
        layout.addWidget(limits)
        layout.addStretch()
        return page

    def load_settings_form(self):
        for key, lim in get_limits().items():
            for name, box in self.limit_inputs[key].items():
                box.setValue(getattr(lim, name))

    def apply_theme(self):
        self.setStyleSheet(DARK_STYLE if self.dark else "")
        self.btn_theme.setText("☀ Svetlý režim" if self.dark else "🌙 Tmavý režim")
        self.chart.dark = self.dark
        self.chart.update()

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()

    def save_settings(self):
        set_setting("dark_mode", "1" if self.dark else "0")
        QMessageBox.information(self, "Uložené", "Nastavenia boli uložené.")

    def save_limits(self):
        new = {key: Limits(*(boxes[name].value() for name in Limits._fields)) for key, boxes in self.limit_inputs.items()}
        bad = [p.name for p in PARAMS
               if not (new[p.key].lo <= new[p.key].note <= new[p.key].warn <= new[p.key].hi
                       and new[p.key].lo < new[p.key].hi)]
        if bad:
            QMessageBox.warning(self, "Neplatné hranice",
                                "Hranice musia ísť od najnižšej po najvyššiu (nízke pod ≤ zvýšené od ≤ odporúča sa "
                                "zásah od ≤ príliš vysoké od) a „nízke pod“ musí byť menšie ako „príliš vysoké od“: "
                                + ", ".join(bad))
            return
        db_many("UPDATE limits SET min_value = ?, note_value = ?, warn_value = ?, max_value = ? WHERE key = ?",
                [(lim.lo, lim.note, lim.warn, lim.hi, key) for key, lim in new.items()])
        QMessageBox.information(self, "Uložené", "Hranice boli uložené.")


if __name__ == "__main__":
    sys.excepthook = handle_exception
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
