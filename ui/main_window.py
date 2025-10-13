# ui/main_window.py
from collections import defaultdict
import os
from .font_utils import load_lato_family
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QMessageBox, QSizePolicy,
    QFrame, QScrollArea, QListView
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase

from core.io_csv import load_events_csv
from .styles import STYLE_LIGHT
from .timeline_canvas import TimelineCanvas
from .finance_chart import FinanceChart


# ------ Chip layout constants ------
CHIP_HEIGHT = 42
CHIP_RADIUS = 12


def make_chip(inner: QWidget) -> QFrame:
    """Chip bianco con bordo sottile (flat)."""
    chip = QFrame()
    chip.setObjectName("Chip")
    chip.setStyleSheet(f"""
        QFrame#Chip {{
            background: #ffffff;
            border: 1px solid #e9eef5;
            border-radius: {CHIP_RADIUS}px;
        }}
    """)
    lay_chip = QHBoxLayout(chip)
    lay_chip.setContentsMargins(12, 6, 12, 6)
    lay_chip.setSpacing(8)
    lay_chip.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    lay_chip.addWidget(inner, 0, Qt.AlignmentFlag.AlignVCenter)
    chip.setMinimumHeight(CHIP_HEIGHT)
    chip.setMaximumHeight(CHIP_HEIGHT)
    return chip


def make_content_card(widget: QWidget, radius: int = 16) -> QFrame:
    """Card bianca flat per timeline/grafici."""
    card = QFrame()
    card.setObjectName("ContentCard")
    card.setStyleSheet(f"""
        QFrame#ContentCard {{
            background: #ffffff;
            border: 1px solid #e6e6e6;
            border-radius: {radius}px;
        }}
    """)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    lay.addWidget(widget)
    return card


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Timeline App — Qt Canvas (no HTML)")
        self.resize(1200, 900)

        # === Font Lato (se disponibile) ===
        self.font_family, _ = load_lato_family(fallback_family="Arial")
        self.setFont(QFont(self.font_family, 10))

        # === Stile globale (combo moderno + scrollbar verticale moderna) ===
        self.setStyleSheet(STYLE_LIGHT + f"""
            QMainWindow, QWidget {{ background-color: #ffffff; font-family: "{self.font_family}"; }}

            QLabel#SectionTitle {{
                font-weight: 700;
                font-size: 18px;
                margin-top: 6px;
                color: #111;
            }}

            QPushButton#Primary {{
                background: transparent;
                border: none;
                border-radius: {CHIP_RADIUS - 2}px;
                padding: 8px 12px;
                color: #111;
                font-weight: 600;
            }}
            QPushButton#Primary:hover  {{ background: #f7f9fc; }}
            QPushButton#Primary:pressed{{ background: #eef3f9; }}

            /* ===== COMBO PERSONA (moderno, grigio, stondato) ===== */
            QComboBox#PersonCombo {{
                background: #fcfcfd;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 8px 36px 8px 12px;
                color: #111;
            }}
            QComboBox#PersonCombo:hover {{
                background: #f7f7f9;
                border-color: #dfe3ea;
            }}
            QComboBox#PersonCombo:focus {{
                border-color: #c3c9d4;
            }}
            QComboBox#PersonCombo:disabled {{
                color: #9aa3af;
                background: #f3f4f6;
            }}
            QComboBox#PersonCombo::drop-down {{ border: none; width: 28px; }}
            QComboBox#PersonCombo::down-arrow {{
                image: none; width: 0; height: 0;
                border-left: 6px solid transparent;
                border-right: 6px solid transparent;
                border-top: 7px solid #6b7280;
                margin-right: 10px;
            }}
            /* Popup del combo */
            QComboBox#PersonCombo QAbstractItemView {{
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 6px 0;
                outline: none;
                selection-background-color: #eef2f7;
                selection-color: #111;
            }}
            QComboBox#PersonCombo QAbstractItemView::item {{
                min-height: 28px;
                padding: 6px 10px;
            }}

            /* ===== SCROLLBAR VERTICALE MODERNA (solo per l'area centrale) ===== */
            QScrollArea#MainScroll QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 8px 4px 8px 4px;
                border: none;
            }}
            QScrollArea#MainScroll QScrollBar::handle:vertical {{
                background: #cbd5e1;      /* slate-300 */
                min-height: 40px;
                border-radius: 6px;
            }}
            QScrollArea#MainScroll QScrollBar::handle:vertical:hover  {{ background: #b6c2cf; }}
            QScrollArea#MainScroll QScrollBar::handle:vertical:pressed{{ background: #94a3b8; }}
            QScrollArea#MainScroll QScrollBar::add-line:vertical,
            QScrollArea#MainScroll QScrollBar::sub-line:vertical {{
                height: 0; border: none; background: transparent;
            }}
            QScrollArea#MainScroll QScrollBar::add-page:vertical,
            QScrollArea#MainScroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

        # ===== Stato dati =====
        self.events = []

        # ---------- CHIP: controlli ----------
        self.btn_load = QPushButton("📂 Carica CSV Eventi")
        self.btn_load.setObjectName("Primary")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        chip_load = make_chip(self.btn_load)

        self.status_badge = QLabel("Caricato: —")
        self.status_badge.setStyleSheet("color:#111111; font-weight: 400;")
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        chip_status = make_chip(self.status_badge)

        person_wrap = QWidget()
        pw = QHBoxLayout(person_wrap)
        pw.setContentsMargins(0, 0, 0, 0)
        pw.setSpacing(8)
        pw.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lbl_person = QLabel("Persona:")
        lbl_person.setStyleSheet("color:#374151; font-weight: 400;")
        lbl_person.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.person_combo = QComboBox()
        self.person_combo.setObjectName("PersonCombo")
        self.person_combo.setEnabled(False)
        self.person_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.person_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.person_combo.setMinimumContentsLength(18)
        self.person_combo.setToolTip("Seleziona la persona")
        self.person_combo.setView(QListView())  # popup personalizzabile (rounded)
        pw.addWidget(lbl_person, 0, Qt.AlignmentFlag.AlignVCenter)
        pw.addWidget(self.person_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_person = make_chip(person_wrap)

        # ---------- Top row ----------
        top_row = QWidget()
        row = QHBoxLayout(top_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(chip_load)
        row.addWidget(chip_status, 1)
        row.addWidget(chip_person)

        # ---------- Timeline (alta) ----------
        self.canvas = TimelineCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(520)  # aumenta per maggiore leggibilità
        canvas_card = make_content_card(self.canvas, radius=16)

        # ---------- Finance Chart (alto) ----------
        self.finance_chart = FinanceChart()
        self.finance_chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.finance_chart.setMinimumHeight(520)
        finance_card = make_content_card(self.finance_chart, radius=16)

        # (opzionale) icone categoria
        icon_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icons")
        self.canvas.set_icon_map({
            "famiglia":  os.path.join(icon_base, "famiglia.png"),
            "acquisti":  os.path.join(icon_base, "acquisti.png"),
            "obiettivi": os.path.join(icon_base, "obiettivi.png"),
            "lavoro":    os.path.join(icon_base, "lavoro.png"),
            "studio":    os.path.join(icon_base, "studio.png"),
            "salute":    os.path.join(icon_base, "salute.png"),
        })

        # ---------- Contenuto scrollabile ----------
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(top_row)
        title = QLabel("Timeline")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        root.addWidget(canvas_card)
        root.addWidget(finance_card)

        scroll = QScrollArea()
        scroll.setObjectName("MainScroll")  # per stilizzare solo questa scrollbar
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)

        self.setCentralWidget(scroll)

        # Signals
        self.btn_load.clicked.connect(self.on_load_csv)
        self.person_combo.currentTextChanged.connect(self.on_person_changed)

    # ===== Actions =====
    def on_load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona CSV Eventi", "", "CSV (*.csv)")
        if not path:
            return
        try:
            self.events = load_events_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))
            return

        if not self.events:
            QMessageBox.information(self, "Info", "Nessun evento valido trovato.")
            self.person_combo.setEnabled(False)
            self.status_badge.setText("Caricato: 0 persone")
            self.finance_chart.set_event_dates([])
            return

        per_persona = defaultdict(int)
        for ev in self.events:
            per_persona[ev.nome] += 1
        persone = sorted(per_persona.keys())

        self.person_combo.blockSignals(True)
        self.person_combo.clear()
        self.person_combo.addItems(persone)
        self.person_combo.setEnabled(True)
        self.person_combo.blockSignals(False)

        self.person_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.person_combo.setMinimumContentsLength(max(18, max(len(p) for p in persone)))
        for i, p in enumerate(persone):
            self.person_combo.setItemData(i, f"{p} — {per_persona[p]} eventi", Qt.ItemDataRole.ToolTipRole)

        self.status_badge.setText(f"Caricato: {len(persone)} persone, {len(self.events)} eventi validi")

        if self.person_combo.count() > 0:
            self.person_combo.setCurrentIndex(0)
            self.render_timeline()

    def on_person_changed(self, _):
        self.render_timeline()

    # ===== Helpers =====
    def events_for_person(self, person: str):
        p = (person or "").strip()
        return [e for e in self.events if e.nome.strip() == p]

    def render_timeline(self):
        person = (self.person_combo.currentText() or "").strip()
        if not person:
            return
        sub = self.events_for_person(person)
        if not sub:
            self.status_badge.setText("Caricato: 0 eventi per questa persona")
            self.canvas.set_events([])
            self.finance_chart.set_event_dates([])
            return

        # Timeline
        self.canvas.set_events(sub)
        # Finance chart
        self.finance_chart.set_event_dates([e.dt for e in sub])

    # ===== Font helpers =====
    