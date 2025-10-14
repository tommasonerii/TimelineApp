# ui/timeline_canvas.py
from __future__ import annotations
from .font_utils import load_lato_family
from typing import Dict, List, Optional, Literal
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPixmap, QPainterPath,
    QTextOption, QFontDatabase
)
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsPathItem
)

from core.models import Event

# ===========================
#  PALETTE & COSTANTI
# ===========================
CATEGORY_COLORS: Dict[str, str] = {
    "famiglia":   "#fa9f42",
    "finanze":    "#2b4162",
    "sogni":      "#0b6e4f",
    "carriera":   "#814342",
    "istruzione": "#e0e0e2",
    "salute":     "#f71735",
}
DEFAULT_COLOR = "#C7884A"
TODAY_COLOR   = QColor("#0f172a")

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

        # Stile
        self.axis_color = QColor("#5b6570")
        self.label_color = QColor("#111111")
        self.future_opacity = 0.55  # marker futuri

        # Font Lato (Light/Regular/Bold/Black se disponibili)
        self.font_family, self.available_weights = load_lato_family(fallback_family="Arial")
        self.base_font = QFont(self.font_family)
        self.setFont(self.base_font)

    # ---------- API ----------
    def set_icon_map(self, icon_map: Dict[str, str]) -> None:
        self.icon_map = {(k or "").strip().lower(): v for k, v in icon_map.items()}

    def set_events(self, events: List[Event]) -> None:
        self.events = sorted(events, key=lambda e: e.dt)
        self._redraw_and_fit()

    # ---------- Eventi Qt ----------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redraw_and_fit()

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

        # Range temporale con padding simmetrico
        dt_min = self.events[0].dt
        dt_max = self.events[-1].dt
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

        # "OGGI"
        now = datetime.now()
        if dt_min_pad <= now <= dt_max_pad:
            x_now = x_from_dt(now)
            r = today_size / 2
            # Clamp X del marker oggi
            x_now = max(safe_pad + r, min(vw - safe_pad - r, x_now))

            dot = QGraphicsEllipseItem(x_now - r, y0 - r, 2 * r, 2 * r)
            pen = QPen(TODAY_COLOR, max(2, int(vh * 0.005)))
            dot.setPen(pen)
            dot.setBrush(QBrush(TODAY_COLOR))
            dot.setZValue(2.0)
            dot.setToolTip(f"Oggi: {now:%Y-%m-%d}")
            self.scene.addItem(dot)

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

        last_label_rects: Dict[Literal["above", "below"], List[QRectF]] = {
            "above": [],
            "below": [],
        }
        next_side: Literal["above", "below"] = "above"

        # Per garantire una distanza minima orizzontale tra i pallini
        last_dot_x: Optional[float] = None

        for ev in self.events:
            x_nom = x_from_dt(ev.dt)
            min_x = float(safe_pad) + icon_size / 2
            max_x = float(vw - safe_pad) - icon_size / 2
            x = max(min_x, min(max_x, x_nom))

            # Enforce distanza minima tra i pallini
            if last_dot_x is not None:
                if x < last_dot_x + MIN_DOT_SPACING_PX:
                    x = min(max_x, last_dot_x + MIN_DOT_SPACING_PX)
            last_dot_x = x

            # Marker icona/cerchio
            marker_top = max(safe_pad, min(vh - safe_pad - icon_size, y0 - icon_size / 2))
            if not self._try_draw_icon(x, marker_top, ev, icon_size, is_future=(ev.dt > now)):
                self._draw_circle(x, marker_top, ev, icon_size, is_future=(ev.dt > now))

            # ------- Etichetta centrata -------
            label_text = (ev.titolo or "").upper()
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

            above_rect = QRectF(bx, y0 - label_gap - bh, bw, bh)
            below_rect = QRectF(bx, y0 + label_gap,   bw, bh)

            preferred_side = next_side
            alternate_side = "below" if preferred_side == "above" else "above"

            def _has_overlap(rect: QRectF, items: List[QRectF]) -> bool:
                return any(rect.intersects(other) for other in items)

            candidates = {"above": above_rect, "below": below_rect}
            side = preferred_side
            if _has_overlap(candidates[side], last_label_rects[side]):
                if not _has_overlap(candidates[alternate_side], last_label_rects[alternate_side]):
                    side = alternate_side
                else:
                    overlap_pref = self._overlap_amount(candidates[side], last_label_rects[side])
                    overlap_alt = self._overlap_amount(candidates[alternate_side], last_label_rects[alternate_side])
                    side = alternate_side if overlap_alt < overlap_pref else preferred_side

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

            last_label_rects[side].append(bubble_rect)
            next_side = "below" if side == "above" else "above"

            # Bubble
            cat_color = color_for(ev.categoria)
            bubble = BubbleItem(bubble_rect, radius=10.0, bg_color=cat_color, alpha=BUBBLE_BG_ALPHA)
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

        # NIENTE fitInView: lasciamo la scena 1:1 con la viewport
        # self.fitInView(...)

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
        c = color_for(ev.categoria)
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
