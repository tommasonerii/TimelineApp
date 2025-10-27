# ui/timeline_canvas.py
from __future__ import annotations
from .font_utils import load_lato_family
from typing import Dict, List, Optional, Literal
from datetime import datetime, timedelta, date

from PyQt6.QtCore import Qt, QRectF, QStandardPaths, QMarginsF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPainterPath,
    QTextOption, QFontDatabase, QPageLayout, QPageSize, QGuiApplication
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsPathItem,
    QToolButton, QFileDialog
)
from PyQt6.QtPrintSupport import QPrinter

from core.models import Event

# ===========================
#  PALETTE & COSTANTI
# ===========================
CATEGORY_COLORS: Dict[str, str] = {
    # Nuove categorie principali
    "bisogno":   "#ef4444",  # red-500
    "progetto":  "#3b82f6",  # blue-500
    "desiderio": "#10b981",  # emerald-500
    # Retrocompatibilità (se arrivano ancora eventi legacy)
    "famiglia":   "#fa9f42",
    "finanze":    "#2b4162",
    "sogni":      "#0b6e4f",
    "carriera":   "#814342",
    "istruzione": "#e0e0e2",
    "salute":     "#f71735",
}
DEFAULT_COLOR = "#C7884A"
TODAY_COLOR   = QColor("#0f172a")
EXPECTANCY_COLOR = QColor("#6366f1")  # viola

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
        self.dep_color_map: Dict[str, QColor] = {}
        self.current_person: Optional[str] = None

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

    def set_expectancy(self, birth_dt: Optional[datetime], sex: Optional[str]) -> None:
        """Imposta la data dell'aspettativa di vita dato sesso e data di nascita."""
        self.expectancy_dt = None
        if not birth_dt or not sex:
            self._redraw_and_fit()
            return

        s = (sex or "").strip().lower()
        if s.startswith("m") or s.startswith("uomo") or s.startswith("masc"):
            years = LIFE_EXPECTANCY_YEARS_MALE
        elif s.startswith("f") or s.startswith("donna") or s.startswith("femm"):
            years = LIFE_EXPECTANCY_YEARS_FEMALE
        else:
            years = LIFE_EXPECTANCY_YEARS_OTHER

        def _add_years(d: datetime, n: int) -> datetime:
            try:
                return d.replace(year=d.year + n)
            except ValueError:
                # gestione 29/02 → 28/02
                if d.month == 2 and d.day == 29:
                    return d.replace(year=d.year + n, month=2, day=28)
                # fallback: aggiungi giorni approssimati
                return d + timedelta(days=int(n * 365.25))

        self.expectancy_dt = _add_years(birth_dt, years)
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
            return

        # Dimensioni viewport e scena 1:1
        vw = max(300, self.viewport().width())
        vh = max(220, self.viewport().height())
        self.scene.setSceneRect(QRectF(0, 0, vw, vh))

        # Safe padding (impedisce overflow ai bordi)
        safe_pad = max(12, int(min(vw, vh) * 0.022))

        # Metriche
        pad_x      = int(vw * SIDE_PAD_RATIO)
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
        now_range = datetime.now()
        dates_for_range.append(now_range)
        if self.expectancy_dt is not None:
            dates_for_range.append(self.expectancy_dt)
        dt_min = min(dates_for_range)
        dt_max = max(dates_for_range)
        if dt_min == dt_max:
            dt_max = dt_min + timedelta(days=1)
        base_range_days = max((dt_max - dt_min).days, 1)
        pad_days = max(int(base_range_days * 0.10), 15)
        dt_min_pad = dt_min - timedelta(days=pad_days)
        dt_max_pad = dt_max + timedelta(days=pad_days)
        total_sec = (dt_max_pad - dt_min_pad).total_seconds()

        def x_from_dt(d: datetime) -> float:
            rel = (d - dt_min_pad).total_seconds() / total_sec if total_sec > 0 else 0.0
            rel = max(0.0, min(1.0, rel))
            return axis_x1 + (axis_x2 - axis_x1) * rel
        today_x: Optional[float] = None
        today_r: Optional[float] = None
        today_dot_item = None
        today_txt_item = None
        prev_ev_x: Optional[float] = None
        next_ev_x: Optional[float] = None
        # Riferimenti per marker Aspettativa
        exp_x: Optional[float] = None
        exp_r: Optional[float] = None
        exp_dot_item = None
        exp_txt_item = None

        # "OGGI"
        now = datetime.now()
        if dt_min_pad <= now <= dt_max_pad:
            x_now = x_from_dt(now)
            r = today_size / 2
            # Clamp X del marker oggi
            x_now = max(safe_pad + r, min(vw - safe_pad - r, x_now))
            today_x = x_now
            today_r = r

            dot = QGraphicsEllipseItem(x_now - r, y0 - r, 2 * r, 2 * r)
            pen = QPen(TODAY_COLOR, max(2, int(vh * 0.005)))
            dot.setPen(pen)
            dot.setBrush(QBrush(TODAY_COLOR))
            # Metti OGGI sopra ai pallini evento per evitare che venga coperto
            dot.setZValue(2.2)
            dot.setToolTip(f"Oggi: {now:%Y-%m-%d}")
            self.scene.addItem(dot)
            today_dot_item = dot

            oggi_txt = QGraphicsTextItem("OGGI")
            oggi_txt.setDefaultTextColor(QColor("#6b7280"))
            oggi_txt.setFont(oggi_font)
            rct = oggi_txt.boundingRect()
            # Clamp orizzontale del testo
            txt_x = max(safe_pad, min(vw - rct.width() - safe_pad, x_now - rct.width() / 2))
            txt_y = y0 + date_gap + 18
            # Clamp verticale
            txt_y = max(safe_pad, min(vh - rct.height() - safe_pad, txt_y))
            oggi_txt.setPos(txt_x, txt_y)
            oggi_txt.setZValue(0.3)
            self.scene.addItem(oggi_txt)
            today_txt_item = oggi_txt

        # "ASPETTATIVA"
        if self.expectancy_dt is not None and dt_min_pad <= self.expectancy_dt <= dt_max_pad:
            x_exp = x_from_dt(self.expectancy_dt)
            r = today_size / 2
            x_exp = max(safe_pad + r, min(vw - safe_pad - r, x_exp))

            dot = QGraphicsEllipseItem(x_exp - r, y0 - r, 2 * r, 2 * r)
            pen = QPen(EXPECTANCY_COLOR, max(2, int(vh * 0.005)))
            dot.setPen(pen)
            dot.setBrush(QBrush(EXPECTANCY_COLOR))
            dot.setZValue(2.0)
            dot.setToolTip(f"Aspettativa: {self.expectancy_dt:%Y-%m-%d}")
            self.scene.addItem(dot)
            exp_dot_item = dot

            txt = QGraphicsTextItem("ASPETTATIVA")
            txt.setDefaultTextColor(QColor("#6b7280"))
            txt.setFont(oggi_font)
            rct = txt.boundingRect()
            txt_x = max(safe_pad, min(vw - rct.width() - safe_pad, x_exp - rct.width() / 2))
            txt_y = y0 + date_gap + 18
            txt_y = max(safe_pad, min(vh - rct.height() - safe_pad, txt_y))
            txt.setPos(txt_x, txt_y)
            txt.setZValue(0.3)
            self.scene.addItem(txt)
            exp_txt_item = txt
            exp_x = x_exp
            exp_r = r

        last_label_rects: Dict[Literal["above", "below"], List[QRectF]] = {
            "above": [],
            "below": [],
        }
        next_side: Literal["above", "below"] = "above"

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

        for ev in self.events:
            x_nom = x_from_dt(ev.dt)
            min_x = float(safe_pad) + icon_size / 2
            max_x = float(vw - safe_pad) - icon_size / 2
            x = max(min_x, min(max_x, x_nom))
            # Spaziatura OGGI rispetto all'ultimo passato prima del primo futuro
            dot_spacing_pre = max(float(MIN_DOT_SPACING_PX), float(int(max_label_w * 0.55)))
            if today_x is not None and ev.dt >= now and (last_dot_x is None or last_dot_x < today_x):
                if prev_ev_x is not None and today_r is not None:
                    left_bound = prev_ev_x + dot_spacing_pre
                    left_bound = max(float(safe_pad) + today_r, min(float(vw - safe_pad) - today_r, left_bound))
                    if today_x < left_bound:
                        if today_dot_item is not None:
                            rect = today_dot_item.rect()
                            rect.moveLeft(left_bound - today_r)
                            today_dot_item.setRect(rect)
                        if today_txt_item is not None:
                            rct = today_txt_item.boundingRect()
                            txt_x = max(float(safe_pad), min(float(vw - rct.width() - safe_pad), left_bound - rct.width() / 2))
                            txt_y = y0 + date_gap + 18
                            txt_y = max(float(safe_pad), min(float(vh - rct.height() - safe_pad), txt_y))
                            today_txt_item.setPos(txt_x, txt_y)
                        today_x = left_bound
                last_dot_x = today_x
            

            # Enforce distanza minima tra i pallini: usa la soglia più grande
            dot_spacing = max(float(MIN_DOT_SPACING_PX), float(int(max_label_w * 0.55)))
            if last_dot_x is not None and x < last_dot_x + dot_spacing:
                x = min(max_x, last_dot_x + dot_spacing)

            # ------- Etichetta centrata -------
            title_text = (ev.titolo or "").upper()
            # Delta temporale solo per eventi futuri
            delta_text = ""
            if ev.dt > now:
                mleft = months_until(now, ev.dt)
                if mleft >= 12:
                    years = mleft // 12
                    unit = "anno" if years == 1 else "anni"
                    delta_text = f"\nTra: {years} {unit}"
                else:
                    mdisp = max(1, mleft)
                    unit = "mese" if mdisp == 1 else "mesi"
                    delta_text = f"\nTra: {mdisp} {unit}"

            label_text = f"{title_text}{delta_text}"
            label = QGraphicsTextItem()
            label.setDefaultTextColor(self.label_color)
            label.setFont(title_font)
            label.setPlainText(label_text)

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

            # Alterna la distanza verticale etichetta ↔ pallino per ridurre collisioni
            gap_above = int(label_gap * (1.6 if alt_toggle["above"] else 1.0))
            gap_below = int(label_gap * (1.6 if alt_toggle["below"] else 1.0))
            above_rect = QRectF(bx, y0 - gap_above - bh, bw, bh)
            below_rect = QRectF(bx, y0 + gap_below,   bw, bh)

            # Impone lato: capofamiglia sopra (is_dependent False), familiari a carico sotto
            is_dep = bool(getattr(ev, 'is_dependent', False))
            forced_side = "below" if is_dep else "above"
            preferred_side = forced_side
            alternate_side = forced_side  # nessuna alternanza

            def _has_overlap(rect: QRectF, items: List[QRectF]) -> bool:
                return any(rect.intersects(other) for other in items)

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

            # X finale deciso: aggiorna il riferimento e disegna il marker
            last_dot_x = x
            if ev.dt <= now:
                prev_ev_x = x
            elif next_ev_x is None:
                next_ev_x = x

            # Toggle alternanza per il lato usato
            alt_toggle[side] = not alt_toggle[side]

            # Marker icona/cerchio dopo aver fissato X
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
            label.setToolTip(f"{ev.titolo}\n{ev.categoria}\n{ev.dt:%Y-%m-%d}")
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

            # Data opposta, clampata ai bordi
            date_side = "below" if side == "above" else "above"
            self._draw_date_opposite_clamped(
                x=x, y_axis=y0, d=ev.dt, font=date_font,
                side=date_side, gap=date_gap,
                vw=vw, vh=vh, safe_pad=safe_pad
            )

        # OGGI è già stato allineato prima del primo evento futuro
        # Riposiziona il marker "ASPETTATIVA" per rispettare la distanza minima
        if exp_dot_item is not None and exp_x is not None and exp_r is not None:
            dot_spacing = float(int(max_label_w * 0.55))
            left_bound = float(safe_pad) + exp_r
            if last_dot_x is not None:
                left_bound = max(left_bound, last_dot_x + dot_spacing)
            if today_x is not None and today_x <= exp_x:
                left_bound = max(left_bound, today_x + dot_spacing)
            right_bound = float(vw - safe_pad) - exp_r
            new_x = exp_x
            if left_bound > right_bound:
                new_x = right_bound
            else:
                if new_x < left_bound:
                    new_x = left_bound
            if abs(new_x - exp_x) > 0.1:
                rect = exp_dot_item.rect()
                rect.moveLeft(new_x - exp_r)
                exp_dot_item.setRect(rect)
                if exp_txt_item is not None:
                    rct = exp_txt_item.boundingRect()
                    txt_x = max(float(safe_pad), min(float(vw - rct.width() - safe_pad), new_x - rct.width() / 2))
                    txt_y = y0 + date_gap + 18
                    txt_y = max(float(safe_pad), min(float(vh - rct.height() - safe_pad), txt_y))
                    exp_txt_item.setPos(txt_x, txt_y)
                exp_x = new_x
        # NIENTE fitInView: lasciamo la scena 1:1 con la viewport
        # self.fitInView(...)
        # Mostra/abilita il pulsante PDF se c'è contenuto
        if hasattr(self, "_pdf_btn"):
            self._pdf_btn.setEnabled(bool(self.events))
            if bool(self.events):
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
            filename = self._default_pdf_filename()
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
            filename = self._default_pdf_filename()
            initial = filename
            if dl:
                initial = (dl.rstrip('/\\') + '/' + filename)
            path, _ = QFileDialog.getSaveFileName(self, "Esporta PDF", initial, "PDF (*.pdf)")
            if not path:
                return

        if not str(path).lower().endswith('.pdf'):
            path = str(path) + '.pdf'
        printer.setOutputFileName(path)
        self._paint_to_printer(printer)

    def _default_pdf_filename(self) -> str:
        """Costruisce il nome file predefinito per l'export PDF.
        Formato richiesto: timeline_nome_cognome.pdf (senza timestamp).
        In assenza del nome persona, ricade su timeline.pdf.
        """
        person = (self.current_person or "").strip()
        if not person:
            base = "timeline"
        else:
            try:
                import unicodedata
                norm = unicodedata.normalize('NFKD', person)
                ascii_only = ''.join(ch for ch in norm if not unicodedata.combining(ch))
            except Exception:
                ascii_only = person
            slug = ''.join(ch if ch.isalnum() or ch in (' ', '-', '_') else ' ' for ch in ascii_only)
            slug = '_'.join(part for part in slug.strip().split())
            slug = slug.lower()
            base = f"timeline_{slug}" if slug else "timeline"
        return f"{base}.pdf"

    def _paint_to_printer(self, printer: QPrinter) -> None:
        painter = QPainter(printer)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            # Area stampabile in pixel alla risoluzione della stampante
            layout = printer.pageLayout()
            pr = layout.paintRectPixels(printer.resolution())
            target = QRectF(pr)
            source = QRectF(self.scene.sceneRect())

            # Disegna la scena adattandola all'area stampabile mantenendo le proporzioni
            self.scene.render(
                painter,
                target,
                source,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        finally:
            painter.end()

    # ---------- Font helpers ----------

    def _make_font(self, size: int, prefer: List[str]) -> QFont:
        """Crea un QFont scegliendo il peso migliore disponibile secondo l’ordine preferito."""
        weight_map = {
            "Light":    QFont.Weight.Light,
            "Normal":   QFont.Weight.Normal,
            "Medium":   QFont.Weight.Medium,
            "DemiBold": QFont.Weight.DemiBold,
            "Bold":     QFont.Weight.Bold,
            "Black":    QFont.Weight.Black,
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

    def _color_for_event(self, ev: Event) -> QColor:
        fam = (getattr(ev, 'familiare', '') or '').strip()
        if fam:
            c = self.dep_color_map.get(fam)
            if c:
                return QColor(c)
        return color_for(ev.categoria)






