# ui/main_window.py
from collections import defaultdict
import os

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QMessageBox, QSizePolicy,
    QFrame, QScrollArea, QListView, QCompleter
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor, QPalette

from core.io_csv import load_events_csv
from .styles import STYLE_LIGHT
from .timeline_canvas import TimelineCanvas
from .finance_chart import FinanceChart
from .compound_interest import CompoundInterestWidget
from .font_utils import load_lato_family


# ------ Chip layout constants ------
CHIP_HEIGHT = 56
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
    lay = QHBoxLayout(chip)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(8)
    lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(inner, 0, Qt.AlignmentFlag.AlignVCenter)
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
        self.resize(1200, 980)

        # === Font Lato (se disponibile) ===
        self.font_family, _ = load_lato_family(fallback_family="Arial")
        self.setFont(QFont(self.font_family, 10))

        # === Percorso asset icone (chevron giù per combo Persona) ===
        assets_icons = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "icons")
        chevron_down_path = os.path.abspath(os.path.join(assets_icons, "chevron-down.svg")).replace('\\', '/')

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
                border-radius: {CHIP_RADIUS}px;
                padding: 8px 36px 8px 12px;
                color: #111;
                min-height: 20px;
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
            QComboBox#PersonCombo::drop-down {{
                border: none;
                width: 28px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }}
            QComboBox#PersonCombo::down-arrow {{
                image: url("{chevron_down_path}");
                width: 14px; height: 14px;
                margin-right: 10px;
            }}
            /* Popup del combo */
            QComboBox#PersonCombo QAbstractItemView {{
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 4px 0;
                outline: none;
                selection-background-color: #eef2f7;
                selection-color: #111;
            }}
            QComboBox#PersonCombo QAbstractItemView::item {{
                min-height: 34px;
                padding: 8px 12px;
            }}
            QComboBox#PersonCombo QLineEdit {{
                padding-top: 2px; padding-bottom: 2px;
                margin: 0px;
            }}

            /* ===== SCROLLBAR VERTICALE (solo area centrale) ===== */
            QScrollArea#MainScroll QScrollBar:vertical {{
                background: transparent;
                width: 12px;
                margin: 8px 4px 8px 4px;
                border: none;
            }}
            QScrollArea#MainScroll QScrollBar::handle:vertical {{
                background: #cbd5e1;  /* slate-300 */
                min-height: 40px;
                border-radius: 6px;
            }}
            QScrollArea#MainScroll QScrollBar::handle:vertical:hover  {{ background: #b6c2cf; }}
            QScrollArea#MainScroll QScrollBar::handle:vertical:pressed{{ background: #94a3b8; }}
            QScrollArea#MainScroll QScrollBar::add-line:vertical,
            QScrollArea#MainScroll QScrollBar::sub-line:vertical {{ height: 0; border: none; background: transparent; }}
            QScrollArea#MainScroll QScrollBar::add-page:vertical,
            QScrollArea#MainScroll QScrollBar::sub-page:vertical {{ background: transparent; }}
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
        # Allinea l'altezza del combo all'interno del chip
        try:
            self.person_combo.setFixedHeight(CHIP_HEIGHT - 16)  # chip margins top+bottom = 8+8
        except Exception:
            pass
        self.person_combo.setMinimumContentsLength(18)
        self.person_combo.setToolTip("Seleziona la persona")
        self.person_combo.setView(QListView())  # popup arrotondato
        self.person_combo.setEditable(True)
        self.person_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line_edit = self.person_combo.lineEdit()
        # Rimuovi la X di cancellazione dal campo di ricerca
        line_edit.setClearButtonEnabled(False)
        line_edit.setPlaceholderText("Cerca persona…")
        self.person_completer = QCompleter(self.person_combo.model(), self.person_combo)
        self.person_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.person_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.person_combo.setCompleter(self.person_completer)
        # Popup del completer con stile moderno coerente
        comp_popup = QListView()
        comp_popup.setObjectName("PersonPopup")
        comp_popup.setStyleSheet(
            """
            QListView#PersonPopup {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 10px;
                padding: 4px 0;
                outline: none;
                color: #111111; /* testo visibile */
            }
            QListView#PersonPopup::item {
                min-height: 34px;
                padding: 8px 12px;
                color: #111111;
            }
            QListView#PersonPopup::item:selected {
                background: #eef2f7;
                color: #111;
            }
            QListView#PersonPopup::item:hover {
                background: #f5f7fb;
            }
            """
        )
        pal = comp_popup.palette()
        pal.setColor(QPalette.ColorRole.Text, QColor("#111111"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        comp_popup.setPalette(pal)
        self.person_completer.setPopup(comp_popup)
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

        # ---------- Timeline ----------
        self.canvas = TimelineCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(520)
        canvas_card = make_content_card(self.canvas, radius=16)

        # ---------- Finance Chart ----------
        self.finance_chart = FinanceChart()
        self.finance_chart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.finance_chart.setMinimumHeight(520)
        finance_card = make_content_card(self.finance_chart, radius=16)

        # ---------- Compound Interest (terzo widget, PIÙ GRANDE) ----------
        self.compound = CompoundInterestWidget()
        self.compound.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.compound.setMinimumHeight(950)  # più grande degli altri due
        compound_card = make_content_card(self.compound, radius=16)

        # (opzionale) icone categoria per la timeline
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
        root.addWidget(compound_card)

        scroll = QScrollArea()
        scroll.setObjectName("MainScroll")  # per lo stile della scrollbar
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
            self.events, self.people = load_events_csv(path)
        except Exception as e:
            QMessageBox.critical(self, "Errore", str(e))
            return

        if not self.events:
            QMessageBox.information(self, "Info", "Nessun evento valido trovato.")
            self.person_combo.setEnabled(False)
            self.status_badge.setText("Caricato: 0 persone")
            self.finance_chart.set_event_dates([])
            self.compound.set_event_points([])
            self.compound.set_start_date(None)
            return

        per_persona = defaultdict(int)
        for ev in self.events:
            per_persona[ev.nome] += 1
        persone = sorted(per_persona.keys())

        self.person_combo.blockSignals(True)
        self.person_combo.clear()
        self.person_combo.addItems(persone)
        self.person_combo.setEnabled(True)
        self.person_combo.lineEdit().clear()
        if self.person_combo.completer() is not None:
            self.person_combo.completer().setModel(self.person_combo.model())
        self.person_combo.blockSignals(False)

        self.person_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.person_combo.setMinimumContentsLength(max(18, max(len(p) for p in persone)))
        # tooltip con numero eventi
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
            self.compound.set_event_points([])
            self.compound.set_start_date(None)
            return

        # Timeline
        self.canvas.set_events(sub)
        # Imposta marker aspettativa di vita se disponibile per la persona
        birth_dt = None
        sex = ""
        if hasattr(self, 'people') and self.people:
            info = self.people.get(person)
            if info:
                birth_dt = getattr(info, 'nascita', None)
                sex = getattr(info, 'sesso', '')
        self.canvas.set_expectancy(birth_dt, sex)
        # Finance chart
        self.finance_chart.set_event_dates([e.dt for e in sub])
        # Compound interest: (data, titolo) per marker/etichette + data di partenza
        self.compound.set_event_points([(e.dt, e.titolo or "") for e in sub])
        self.compound.set_start_date(sub[0].dt)
