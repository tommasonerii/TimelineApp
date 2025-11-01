from __future__ import annotations
from .font_utils import load_lato_family
from typing import Dict, List, Optional, Literal
from datetime import datetime, timedelta, date

from PyQt6.QtCore import Qt, QRectF, QStandardPaths, QMarginsF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPainterPath,
    QTextOption, QFontDatabase, QPageLayout, QPageSize, QGuiApplication,
    QTextCharFormat
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsPathItem,
    QToolButton, QFileDialog
)
from PyQt6.QtPrintSupport import QPrinter

from core.models import Event
from core.pdf_exporter import default_pdf_filename, paint_timeline_to_printer

# ===========================
#  PALETTE & COSTANTI
# ===========================
CATEGORY_COLORS: Dict[str, str] = {
    # Nuove categorie principali
    "bisogno":  "#ef4444",  # red-500
    "progetto":  "#3b82f6",  # blue-500
    "desiderio": "#10b981",  # emerald-500
    # Retrocompatibilità (se arrivano ancora eventi legacy)
    "famiglia":  "#fa9f42",
    "finanze":   "#2b4162",
    "sogni":   "#0b6e4f",
    "carriera":  "#814342",
    "istruzione": "#e0e0e2",
    "salute":   "#f71735",
}
DEFAULT_COLOR = "#C7884A"
TODAY_COLOR  = QColor("#0f172a")
EXPECTANCY_COLOR = QColor("#6366f1")  # viola
BIRTH_COLOR = QColor("#0891b2")      # cyan-600

# Aspettativa di vita (anni) modificabili
LIFE_EXPECTANCY_YEARS_MALE   = 82
LIFE_EXPECTANCY_YEARS_FEMALE = 86
LIFE_EXPECTANCY_YEARS_OTHER  = 84

# Font (scaling relativo all’altezza viewport)
LABEL_VH_SCALE = 0.023
DATE_VH_SCALE  = 0.020

# Margini
SIDE_PAD_RATIO = 0.03  # padding per asse in X (oltre al safe_pad)

# Gap verticali rispetto all’asse
LABEL_GAP_VH_RATIO = 0.170  # pallino <-> ETICHETTA
DATE_GAP_VH_RATIO  = 0.010  # pallino <-> DATA

# Larghezza massima etichette (frazione della larghezza view)
LABEL_MAX_W_VW_RATIO = 0.14

# Sfondo colorato delle bubble (trasparenza)
BUBBLE_BG_ALPHA = 0.16

# Distanza minima in pixel tra i pallini (centro-centro)
MIN_DOT_SPACING_PX = 40


def color_for(cat: str | None) -> QColor:
    key = (cat or "").strip().lower()
    return QColor(CATEGORY_COLORS.get(key, DEFAULT_COLOR))


class BubbleItem(QGraphicsPathItem):
    """Etichetta con sfondo del colore della categoria (trasparente), senza bordo."""
    def __init__(self, rect: QRectF, radius: float, bg_color: QColor, alpha: float):
        super().__init__()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        self.setPath(path)

        fill = QColor(bg_color)
        fill.setAlphaF(max(0.0, min(1.0, alpha)))
        self.setBrush(QBrush(fill))

        no_pen = QPen()
        no_pen.setStyle(Qt.PenStyle.NoPen)
        self.setPen(no_pen)

        self.setZValue(0.95)  # sotto il testo, sopra le linee


class TimelineCanvas(QGraphicsView):
    """
    - Coordinate fisse = viewport, niente fitInView
    - Safe padding interno per impedire overflow (etichette, date, OGGI, marker)
    - Etichette centrate, word-wrap controllato
    - Data sul lato opposto all’etichetta
    - Connettori sotto i pallini; pallini sempre sopra
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Rendering
        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )

        # No scroll/drag
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setInteractive(False)

        # Sfondo bianco
        self.setStyleSheet("background:#ffffff;")
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setScene(self.scene)

        # Dati
        self.events: List[Event] = []
        self.icon_map: Dict[str, str] = {}
        self.expectancy_dt: Optional[datetime] = None
        self.birth_dt: Optional[datetime] = None
        self.dep_color_map: Dict[str, QColor] = {}
        self.current_person: Optional[str] = None
        self.show_past: bool = True
        self.show_future: bool = True
        # Tabelle di aspettativa di vita (iniettate dall'esterno)
        self.mappa_maschi: Dict[int, int] = {}
        self.mappa_femmine: Dict[int, int] = {}

        # Stile
        self.axis_color = QColor("#5b6570")
        self.label_color = QColor("#111111")
        self.future_opacity = 0.55  # marker futuri

        # Font Lato (Light/Regular/Bold/Black se disponibili)
        self.font_family, self.available_weights = load_lato_family(fallback_family="Arial")
        self.base_font = QFont(self.font_family)
        self.setFont(self.base_font)

        # Pulsante export PDF (overlay in alto a destra)
        self._pdf_btn = QToolButton(self.viewport())
        self._pdf_btn.setText("PDF")
        self._pdf_btn.setToolTip("Esporta timeline in PDF")
        self._pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pdf_btn.setAutoRaise(True)
        self._pdf_btn.setStyleSheet(
            """
            QToolButton{
                background: rgba(255,255,255,0.95);
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px 6px;
            }
            QToolButton:hover{ background:#f8fafc; }
            """
        )
        self._pdf_btn.clicked.connect(self._on_export_pdf_clicked)
        self._pdf_btn.hide()

    # ---------- API ----------
    def set_icon_map(self, icon_map: Dict[str, str]) -> None:
        self.icon_map = {(k or "").strip().lower(): v for k, v in icon_map.items()}

    def set_events(self, events: List[Event]) -> None:
        self.events = sorted(events, key=lambda e: e.dt)
        # Ricava il nome persona dagli eventi (tutti della stessa persona)
        self.current_person = (self.events[0].nome if self.events else None)
        # Costruisci la mappa colori per i familiari a carico
        self.dep_color_map.clear()
        palette = [
            QColor("#f59e0b"),  # amber-500
            QColor("#8b5cf6"),  # violet-500
            QColor("#ef4444"),  # red-500
            QColor("#10b981"),  # emerald-500
            QColor("#3b82f6"),  # blue-500
            QColor("#ec4899"),  # pink-500
            QColor("#22c55e"),  # green-500
            QColor("#06b6d4"),  # cyan-500
        ]
        idx = 0
        for ev in self.events:
            fam = (getattr(ev, 'familiare', '') or '').strip()
            if fam and fam not in self.dep_color_map:
                self.dep_color_map[fam] = palette[idx % len(palette)]
                idx += 1
        self._redraw_and_fit()

    def set_time_filters(self, show_past: bool, show_future: bool) -> None:
        changed = (self.show_past != show_past) or (self.show_future != show_future)
        self.show_past = show_past
        self.show_future = show_future
        if changed and self.events:
            self._redraw_and_fit()

    def set_expectancy_tables(self, mappa_maschi: Dict[int, int], mappa_femmine: Dict[int, int]) -> None:
        """Inietta le tabelle di aspettativa di vita (anni rimanenti per età)."""
        self.mappa_maschi = dict(mappa_maschi or {})
        self.mappa_femmine = dict(mappa_femmine or {})

    def set_expectancy(self, birth_dt: Optional[datetime], sex: Optional[str]) -> None:
        """Imposta la data dell'aspettativa di vita usando le tabelle iniettate.
        Fallback: 82 anni fissi se sesso non in tabella o età assente.
        """
        self.expectancy_dt = None
        self.birth_dt = birth_dt
        if not birth_dt:
            self._redraw_and_fit()
            return

        # Età attuale in anni compiuti
        today = date.today()
        bdate = birth_dt.date()
        age = today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
        if age < 0:
            age = 0

        # Seleziona tabella in base al sesso
        s = (sex or "").strip().lower()
        years_left: Optional[int] = None
        if s.startswith("m") or s.startswith("uomo") or s.startswith("masc"):
            years_left = self.mappa_maschi.get(age)
        elif s.startswith("f") or s.startswith("donna") or s.startswith("femm"):
            years_left = self.mappa_femmine.get(age)
        else:
            years_left = None

        # Calcola gli anni totali da nascita → fine vita
        if years_left is None:
            total_years = 82  # fallback fisso
        else:
            total_years = age + max(0, int(years_left))

        def _add_years(d: datetime, n: int) -> datetime:
            try:
                return d.replace(year=d.year + n)
            except ValueError:
                # gestione 29/02 → 28/02
                if d.month == 2 and d.day == 29:
                    return d.replace(year=d.year + n, month=2, day=28)
                # fallback: aggiungi giorni approssimati
                return d + timedelta(days=int(n * 365.25))

        self.expectancy_dt = _add_years(birth_dt, total_years)
        self._redraw_and_fit()

    # ---------- Eventi Qt ----------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redraw_and_fit()
        self._position_print_button()

    # ---------- Render ----------
    def _redraw_and_fit(self) -> None:
        self.scene.clear()
        self.resetTransform()
        if not self.events:
            # Assicurati che il pulsante PDF sia nascosto
            # se non ci sono eventi, anche se la funzione esce qui.
            if hasattr(self, "_pdf_btn"):
                self._pdf_btn.setEnabled(False)
                self._pdf_btn.hide()
            return

        # Dimensioni viewport e scena 1:1
        vw = max(300, self.viewport().width())
        vh = max(220, self.viewport().height())
        self.scene.setSceneRect(QRectF(0, 0, vw, vh))

        # Safe padding (impedisce overflow ai bordi)
        safe_pad = max(12, int(min(vw, vh) * 0.022))

        # Metriche
        pad_x  = int(vw * SIDE_PAD_RATIO)
        axis_thick = max(2, int(vh * 0.008))
        icon_size  = max(12, int(vh * 0.055))
        today_size = max(8,  int(vh * 0.030))
        label_gap  = max(10, int(vh * LABEL_GAP_VH_RATIO))
        date_gap   = max(8,  int(vh * DATE_GAP_VH_RATIO))

        # Font
        title_font = self._make_font(size=max(8, int(vh * LABEL_VH_SCALE)),
                                     prefer=["Bold", "Black", "Medium", "Normal"])
        date_font  = self._make_font(size=max(8, int(vh * DATE_VH_SCALE)),
                                     prefer=["Light", "Normal"])
        oggi_font  = self._make_font(size=max(8, int(vh * DATE_VH_SCALE)),
                                     prefer=["Medium", "Normal"])

        # Larghezza max etichetta
        max_label_w = max(160, int(vw * LABEL_MAX_W_VW_RATIO))

        # Asse
        y0 = vh / 2
        axis_x1 = safe_pad + pad_x
        axis_x2 = vw - (safe_pad + pad_x)
        axis_pen = QPen(self.axis_color, axis_thick, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        axis = QGraphicsLineItem(axis_x1, y0, axis_x2, y0)
        axis.setPen(axis_pen)
        axis.setZValue(0.1)
        self.scene.addItem(axis)

        # Range temporale con padding simmetrico (considera anche aspettativa se presente)
        # Include sempre "oggi" per garantire che il marker sia visibile.
        dates_for_range = [e.dt for e in self.events]
        show_past = self.show_past
        show_future = self.show_future
        now = datetime.now() # 'now' definito qui
        dates_for_range.append(now)
        if show_future and self.expectancy_dt is not None:
            dates_for_range.append(self.expectancy_dt)
        if show_past and self.birth_dt is not None:
            dates_for_range.append(self.birth_dt)
        dt_min = min(dates_for_range)
        dt_max = max(dates_for_range)
        if dt_min == dt_max:
            dt_max = dt_min + timedelta(days=1)
        base_range_days = max((dt_max - dt_min).days, 1)
        pad_days = max(int(base_range_days * 0.10), 15)
        dt_min_pad = dt_min
        dt_max_pad = dt_max + timedelta(days=pad_days)
        total_sec = (dt_max_pad - dt_min_pad).total_seconds()

        def x_from_dt(d: datetime) -> float:
            rel = (d - dt_min_pad).total_seconds() / total_sec if total_sec > 0 else 0.0
            rel = max(0.0, min(1.0, rel))
            return axis_x1 + (axis_x2 - axis_x1) * rel

        last_label_rects: Dict[Literal["above", "below"], List[QRectF]] = {
            "above": [],
            "below": [],
        }
        
        # Per garantire una distanza minima orizzontale tra i pallini
        last_dot_x: Optional[float] = None
        # Alternanza distanza verticale etichette per lato
        alt_toggle = {"above": False, "below": False}

        def months_until(start: datetime, end: datetime) -> int:
            """Ritorna i mesi rimanenti da start (oggi) a end (evento), arrotondati per eccesso.
            Minimo 0.
            """
            if end <= start:
                return 0
            ydiff = end.year - start.year
            mdiff = end.month - start.month
            months = ydiff * 12 + mdiff
            if end.day > start.day:
                months += 1  # conta il mese parziale come pieno
            return max(0, months)
        
        # =====================================================================
        # Inizio della logica di spaziatura unificata
        # =====================================================================

        # --- 1. RACCOGLI TUTTI I MARKER ---
        all_markers = []
        
        # Aggiungi eventi
        for ev in self.events:
            all_markers.append({"dt": ev.dt, "type": "event", "data": ev})

        # Aggiungi "OGGI"
        if dt_min_pad <= now <= dt_max_pad:
            all_markers.append({"dt": now, "type": "today", "data": None})

        # Aggiungi "NASCITA"
        if show_past and self.birth_dt is not None and dt_min_pad <= self.birth_dt <= dt_max_pad:
            all_markers.append({"dt": self.birth_dt, "type": "birth", "data": None})

        # Aggiungi "ASPETTATIVA"
        if show_future and self.expectancy_dt is not None and dt_min_pad <= self.expectancy_dt <= dt_max_pad:
            all_markers.append({"dt": self.expectancy_dt, "type": "expectancy", "data": None})

        # --- 2. ORDINA I MARKER PER DATA ---
        all_markers.sort(key=lambda m: m["dt"])

        # --- 3. LOOP UNICO: SPAZIATURA E DISEGNO ---
        dot_spacing = max(float(MIN_DOT_SPACING_PX), float(int(max_label_w * 0.55)))

        for marker in all_markers:
            dt = marker["dt"]
            m_type = marker["type"]

            # --- 3a. LOGICA DI SPAZIATURA UNIFICATA ---
            x_nom = x_from_dt(dt)
            
            # Determina il raggio del pallino per il clamping
            if m_type == "event":
                r = icon_size / 2
            else:
                r = today_size / 2  # Nascita, Oggi, Aspettativa
            
            min_x = float(safe_pad) + r
            max_x = min(float(vw - safe_pad) - r, float(axis_x2))
            x = max(min_x, min(max_x, x_nom))

            # Applica la spaziatura minima rispetto all'ultimo pallino posizionato
            if last_dot_x is not None and x < last_dot_x + dot_spacing:
                x = min(max_x, last_dot_x + dot_spacing)

            last_dot_x = x  # Aggiorna la posizione dell'ultimo pallino

            # --- 3b. DISEGNO (DISPATCH SUL TIPO) ---
            
            if m_type == "event":
                ev: Event = marker["data"]
                
                # ------- Etichetta centrata (logica originale) -------
                title_text = (ev.titolo or "").upper()
                delta_line = ""
                if ev.dt > now:
                    mleft = months_until(now, ev.dt)
                    if mleft >= 12:
                        years = mleft // 12
                        unit = "anno" if years == 1 else "anni"
                        delta_line = f"Tra: {years} {unit}"
                    else:
                        mdisp = max(1, mleft)
                        unit = "mese" if mdisp == 1 else "mesi"
                        delta_line = f"Tra: {mdisp} {unit}"

                cost_line = self._format_cost_line(getattr(ev, "costo", None))
                label_lines = [title_text]
                if cost_line:
                    label_lines.append(cost_line)
                if delta_line:
                    label_lines.append(delta_line)
                label_text = "\n".join(label_lines)
                label = QGraphicsTextItem()
                label.setDefaultTextColor(self.label_color)
                label.setFont(title_font)
                label.setPlainText(label_text)
                if cost_line or delta_line:
                    doc = label.document()
                    if cost_line:
                        cursor_cost = doc.find(cost_line)
                        if cursor_cost and not cursor_cost.isNull():
                            cost_format = QTextCharFormat()
                            cost_format.setFont(date_font)
                            cursor_cost.mergeCharFormat(cost_format)
                    if delta_line:
                        cursor_delta = doc.find(delta_line)
                        if cursor_delta and not cursor_delta.isNull():
                            cost_format = QTextCharFormat()
                            cost_format.setFont(date_font)
                            cursor_delta.mergeCharFormat(cost_format)

                padx = max(8, int(vw * 0.006))
                pady = max(6, int(vh * 0.008))

                natural_w = label.boundingRect().width()
                max_content_w = max_label_w - 2 * padx
                content_w = min(natural_w, max_content_w)
                label.setTextWidth(content_w)

                opt = label.document().defaultTextOption()
                opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                opt.setWrapMode(QTextOption.WrapMode.WordWrap)
                label.document().setDefaultTextOption(opt)
                label.document().setDocumentMargin(0)

                br = label.boundingRect()
                bw = min(max_label_w, br.width() + 2 * padx)
                bh = br.height() + 2 * pady
                bx = max(float(safe_pad), min(float(vw - bw - safe_pad), x - bw / 2))

                gap_above = int(label_gap * (2.0 if alt_toggle["above"] else 1.0))
                gap_below = int(label_gap * (2.0 if alt_toggle["below"] else 1.0))
                above_rect = QRectF(bx, y0 - gap_above - bh, bw, bh)
                below_rect = QRectF(bx, y0 + gap_below,   bw, bh)

                is_dep = bool(getattr(ev, 'is_dependent', False))
                forced_side = "below" if is_dep else "above"
                preferred_side = forced_side
                
                candidates = {"above": above_rect, "below": below_rect}
                side = preferred_side

                bubble_rect = candidates[side]
                bubble_rect = QRectF(
                    bubble_rect.x(),
                    max(float(safe_pad), min(float(vh - bh - safe_pad), bubble_rect.y())),
                    bubble_rect.width(),
                    bubble_rect.height(),
                )

                bubble_rect = self._resolve_label_overlap(
                    rect=bubble_rect,
                    others=last_label_rects[side],
                    x_min=float(safe_pad),
                    x_max=float(vw - safe_pad - bubble_rect.width()),
                    preferred_center=float(x),
                )
                
                alt_toggle[side] = not alt_toggle[side]

                # Marker icona/cerchio
                marker_top = max(safe_pad, min(vh - safe_pad - icon_size, y0 - icon_size / 2))
                if not self._try_draw_icon(x, marker_top, ev, icon_size, is_future=(ev.dt > now)):
                    self._draw_circle(x, marker_top, ev, icon_size, is_future=(ev.dt > now))

                last_label_rects[side].append(bubble_rect)

                # Bubble
                col = self._color_for_event(ev)
                bubble = BubbleItem(bubble_rect, radius=10.0, bg_color=col, alpha=BUBBLE_BG_ALPHA)
                self.scene.addItem(bubble)

                # Testo
                label.setPos(bubble_rect.x() + padx, bubble_rect.y() + pady)
                label.setZValue(1.0)
                tooltip_lines = [ev.titolo, ev.categoria]
                if cost_line:
                    tooltip_lines.append(cost_line)
                tooltip_lines.append(ev.dt.strftime("%Y-%m-%d"))
                label.setToolTip("\n".join(line for line in tooltip_lines if line))
                self.scene.addItem(label)

                # Connettore
                pen_conn = QPen(QColor("#9aa4ae"), 1)
                if side == "above":
                    y1, y2 = bubble_rect.y() + bubble_rect.height(), y0
                else:
                    y1, y2 = y0, bubble_rect.y()
                vline = QGraphicsLineItem(x, y1, x, y2)
                vline.setPen(pen_conn)
                vline.setZValue(0.2)
                self.scene.addItem(vline)

                # Data opposta
                date_side = "below" if side == "above" else "above"
                self._draw_date_opposite_clamped(
                    x=x, y_axis=y0, d=ev.dt, font=date_font,
                    side=date_side, gap=date_gap,
                    vw=vw, vh=vh, safe_pad=safe_pad
                )
            
            elif m_type == "today":
                # Disegna "OGGI"
                dot = QGraphicsEllipseItem(x - r, y0 - r, 2 * r, 2 * r)
                pen = QPen(TODAY_COLOR, max(2, int(vh * 0.005)))
                dot.setPen(pen)
                dot.setBrush(QBrush(TODAY_COLOR))
                dot.setZValue(2.2) # Sopra gli altri pallini
                dot.setToolTip(f"Oggi: {dt:%Y-%m-%d}")
                self.scene.addItem(dot)

                oggi_txt = QGraphicsTextItem("OGGI")
                oggi_txt.setDefaultTextColor(QColor("#6b7280"))
                oggi_txt.setFont(oggi_font)
                rct = oggi_txt.boundingRect()
                txt_x = max(safe_pad, min(vw - rct.width() - safe_pad, x - rct.width() / 2))
                txt_y = y0 + date_gap + 18
                txt_y = max(safe_pad, min(vh - rct.height() - safe_pad, txt_y))
                oggi_txt.setPos(txt_x, txt_y)
                oggi_txt.setZValue(0.3)
                self.scene.addItem(oggi_txt)

            elif m_type == "birth":
                # Disegna "NASCITA"
                dot_b = QGraphicsEllipseItem(x - r, y0 - r, 2 * r, 2 * r)
                pen_b = QPen(BIRTH_COLOR, max(2, int(vh * 0.005)))
                dot_b.setPen(pen_b)
                dot_b.setBrush(QBrush(BIRTH_COLOR))
                dot_b.setZValue(2.0)
                dot_b.setToolTip(f"Nascita: {dt:%Y-%m-%d}")
                self.scene.addItem(dot_b)
                
                txt_b = QGraphicsTextItem("NASCITA" + "\n" + dt.strftime("%Y"))
                txt_b.setDefaultTextColor(QColor("#6b7280"))
                txt_b.setFont(oggi_font)
                rct_b = txt_b.boundingRect()
                txt_bx = max(safe_pad, min(vw - rct_b.width() - safe_pad, x - rct_b.width() / 2))
                txt_by = y0 + date_gap + 18
                txt_by = max(safe_pad, min(vh - rct_b.height() - safe_pad, txt_by))
                txt_b.setPos(txt_bx, txt_by)
                txt_b.setZValue(0.3)
                self.scene.addItem(txt_b)

            elif m_type == "expectancy":
                # Disegna "ASPETTATIVA"
                dot = QGraphicsEllipseItem(x - r, y0 - r, 2 * r, 2 * r)
                pen = QPen(EXPECTANCY_COLOR, max(2, int(vh * 0.005)))
                dot.setPen(pen)
                dot.setBrush(QBrush(EXPECTANCY_COLOR))
                dot.setZValue(2.0)
                dot.setToolTip(f"Aspettativa: {dt:%Y-%m-%d}")
                self.scene.addItem(dot)
                
                txt = QGraphicsTextItem("ASPETTATIVA:\n" + dt.strftime("%Y"))
                txt.setDefaultTextColor(QColor("#6b7280"))
                txt.setFont(oggi_font)
                rct = txt.boundingRect()
                txt_x = max(safe_pad, min(vw - rct.width() - safe_pad, x - rct.width() / 2))
                txt_y = y0 + date_gap + 18
                txt_y = max(safe_pad, min(vh - rct.height() - safe_pad, txt_y))
                txt.setPos(txt_x, txt_y)
                txt.setZValue(0.3)
                self.scene.addItem(txt)

        # =====================================================================
        # Fine della logica di spaziatura unificata
        # =====================================================================

        # NIENTE fitInView: lasciamo la scena 1:1 con la viewport
        # self.fitInView(...)
        # Mostra/abilita il pulsante PDF se c'è contenuto
        if hasattr(self, "_pdf_btn"):
            # Usiamo 'all_markers' che include anche "Oggi", ecc.
            has_content = bool(all_markers)
            self._pdf_btn.setEnabled(has_content)
            if has_content:
                self._pdf_btn.show()
            else:
                self._pdf_btn.hide()
            self._position_print_button()

    # ---------- Primitive ----------
    def _draw_date_opposite_clamped(
        self, x: float, y_axis: float, d: datetime, font: QFont,
        side: Literal["above", "below"], gap: int,
        vw: int, vh: int, safe_pad: int
    ) -> None:
        txt = QGraphicsTextItem(d.strftime("%Y-%m-%d"))
        txt.setDefaultTextColor(QColor("#6b7280"))
        txt.setFont(font)
        rect = txt.boundingRect()

        if side == "below":
            y_text = y_axis + gap + 18
        else:
            y_text = y_axis - rect.height() - gap - 18

        # Clamp orizzontale e verticale
        x_text = max(float(safe_pad), min(float(vw - rect.width() - safe_pad), x - rect.width() / 2))
        y_text = max(float(safe_pad), min(float(vh - rect.height() - safe_pad), y_text))

        txt.setPos(x_text, y_text)
        txt.setZValue(0.3)
        self.scene.addItem(txt)

    def _try_draw_icon(self, x: float, top_y: float, ev: Event, icon_size: int, is_future: bool) -> bool:
        # Per i familiari a carico usiamo sempre il cerchio colorato (no icone di categoria)
        if (getattr(ev, 'familiare', '') or '').strip():
            return False
        cat_key = (ev.categoria or "").strip().lower()
        path = self.icon_map.get(cat_key)
        if not path:
            return False
        pix = QPixmap(path)
        if pix.isNull():
            return False
        pix = pix.scaled(
            icon_size, icon_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        it = QGraphicsPixmapItem(pix)
        it.setOffset(x - pix.width() / 2, top_y)
        it.setOpacity(self.future_opacity if is_future else 1.0)
        it.setZValue(2.0)
        it.setToolTip(f"{ev.titolo}\n{ev.categoria}\n{ev.dt:%Y-%m-%d}")
        self.scene.addItem(it)
        return True

    def _draw_circle(self, x: float, top_y: float, ev: Event, icon_size: int, is_future: bool) -> None:
        r = icon_size / 2
        c = self._color_for_event(ev)
        alpha_f = self.future_opacity if is_future else 1.0

        border = QColor(c); border.setAlphaF(alpha_f)
        fill   = QColor(c); fill.setAlphaF(alpha_f)

        pen = QPen(border)
        pen.setWidth(max(2, int(icon_size * 0.12)))

        circle = QGraphicsEllipseItem(x - r, top_y, 2 * r, 2 * r)
        circle.setPen(pen)
        circle.setBrush(QBrush(fill))
        circle.setOpacity(1.0)
        circle.setZValue(2.0)
        circle.setToolTip(f"{ev.titolo}\n{ev.categoria}\n{ev.dt:%Y-%m-%d}")
        self.scene.addItem(circle)

    # ---------- Utility ----------
    def _overlap_amount(self, rect: QRectF, others: List[QRectF]) -> float:
        total = 0.0
        for other in others:
            inter = rect.intersected(other)
            if not inter.isNull():
                total += inter.width() * inter.height()
        return total

    def _resolve_label_overlap(
        self,
        rect: QRectF,
        others: List[QRectF],
        x_min: float,
        x_max: float,
        preferred_center: float,
    ) -> QRectF:
        """Sposta la label in orizzontale per evitare sovrapposizioni con quelle già disegnate."""

        result = QRectF(rect)
        gap = max(6.0, rect.height() * 0.15)

        def overlaps_any(r: QRectF) -> List[QRectF]:
            return [o for o in others if r.intersects(o)]

        attempts = 0
        overlapping = overlaps_any(result)
        while overlapping and attempts < 16:
            attempts += 1
            shift_right = max((o.right() + gap) - result.left() for o in overlapping)
            shift_left = max(result.right() - (o.left() - gap) for o in overlapping)

            cand_right = QRectF(result)
            cand_right.translate(shift_right, 0.0)
            cand_left = QRectF(result)
            cand_left.translate(-shift_left, 0.0)

            valid_right = cand_right.left() <= x_max
            valid_left = cand_left.left() >= x_min

            if valid_right and valid_left:
                center_right = cand_right.center().x()
                center_left = cand_left.center().x()
                if abs(center_right - preferred_center) <= abs(center_left - preferred_center):
                    result = cand_right
                else:
                    result = cand_left
            elif valid_right:
                result = cand_right
            elif valid_left:
                result = cand_left
            else:
                break

            new_left = max(x_min, min(result.left(), x_max))
            result.moveLeft(new_left)
            overlapping = overlaps_any(result)

        if result.left() < x_min:
            result.moveLeft(x_min)
        if result.left() > x_max:
            result.moveLeft(x_max)

        return result

    # ---------- Stampa ----------
    def _position_print_button(self) -> None:
        # Ora posizioniamo solo il pulsante PDF nell'angolo in alto a destra
        if not hasattr(self, "_pdf_btn") or self._pdf_btn is None:
            return
        margin = 10
        self._pdf_btn.adjustSize()
        x_pdf = max(0, self.viewport().width() - self._pdf_btn.width() - margin)
        y = margin
        self._pdf_btn.move(x_pdf, y)
        self._pdf_btn.raise_()

        # (Rimosso) azioni di stampa: usiamo solo export PDF

    def _on_export_pdf_clicked(self) -> None:
        mods = QGuiApplication.keyboardModifiers()
        quick = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        if quick:
            dl = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            # Preferisci nome persona nel filename
            filename = default_pdf_filename(self.current_person)
            path = (dl.rstrip('/\\') + '/' + filename) if dl else filename
            self.export_pdf(path)
        else:
            self.export_pdf()

    def export_pdf(self, path: str | None = None) -> None:
        # Esporta direttamente a PDF (vettoriale) ad alta qualità
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setResolution(600)
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Landscape,
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter,
        )
        printer.setPageLayout(layout)

        if not path:
            # Proponi cartella Download con nome file basato sulla persona
            dl = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            filename = default_pdf_filename(self.current_person)
            initial = filename
            if dl:
                initial = (dl.rstrip('/\\') + '/' + filename)
            path, _ = QFileDialog.getSaveFileName(self, "Esporta PDF", initial, "PDF (*.pdf)")
            if not path:
                return

        if not str(path).lower().endswith('.pdf'):
            path = str(path) + '.pdf'
        printer.setOutputFileName(path)
        paint_timeline_to_printer(
            scene=self.scene,
            events=self.events,
            printer=printer,
            current_person=self.current_person,
            label_color=self.label_color,
            make_font=self._make_font,
            category_color_fn=color_for,
        )

    # ---------- Font helpers ----------

    def _make_font(self, size: int, prefer: List[str]) -> QFont:
        """Crea un QFont scegliendo il peso migliore disponibile secondo l’ordine preferito."""
        weight_map = {
            "Light":   QFont.Weight.Light,
            "Normal":  QFont.Weight.Normal,
            "Medium":  QFont.Weight.Medium,
            "DemiBold": QFont.Weight.DemiBold,
            "Bold":   QFont.Weight.Bold,
            "Black":   QFont.Weight.Black,
        }
        chosen = None
        for w in prefer:
            if w in self.available_weights:
                chosen = w
                break
        if chosen is None:
            chosen = "Normal"

        f = QFont(self.font_family, size)
        f.setWeight(weight_map[chosen])
        return f

    def _format_cost_line(self, costo: Optional[str]) -> Optional[str]:
        """Formatta il costo per l'etichetta/tooltip, mantenendo il testo originale se non numerico."""
        if costo is None:
            return None
        s = str(costo).strip()
        if not s:
            return None
        allowed = set("0123456789., ")
        if not any(ch.isdigit() for ch in s):
            return f"Costo: {s}"
        if any(ch not in allowed for ch in s):
            return f"Costo: {s}"
        cleaned = s.replace(" ", "")
        normalized = cleaned.replace(".", "").replace(",", ".")
        try:
            value = float(normalized)
        except ValueError:
            return f"Costo: {s}"
        if value.is_integer():
            formatted = f"{value:,.0f}"
        else:
            formatted = f"{value:,.2f}"
        formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"Costo: {formatted}"

    def _color_for_event(self, ev: Event) -> QColor:
        fam = (getattr(ev, 'familiare', '') or '').strip()
        if fam:
            c = self.dep_color_map.get(fam)
            if c:
                return QColor(c)
        return color_for(ev.categoria)
