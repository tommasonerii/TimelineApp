from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional, Sequence

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPageLayout
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QGraphicsScene

from core.models import Event

FontFactory = Callable[[int, List[str]], QFont]
CategoryColorResolver = Callable[[Optional[str]], QColor]


def default_pdf_filename(person: Optional[str], *, today: Optional[date] = None) -> str:
    """Restituisce il nome file PDF richiesto.
    Formato: cognome_nome_timeline_gg-mm-aaaa.pdf (senza slash per compatibilità FS).
    """
    today = today or date.today()
    today_token = today.strftime("%d-%m-%Y")
    person = (person or "").strip()

    def _slugify(value: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else " " for ch in value)
        return "_".join(part for part in cleaned.strip().split()).lower()

    if not person:
        base = "timeline"
    else:
        try:
            import unicodedata

            norm = unicodedata.normalize("NFKD", person)
            ascii_only = "".join(ch for ch in norm if not unicodedata.combining(ch))
        except Exception:
            ascii_only = person

        parts = [p for p in ascii_only.replace("-", " ").split() if p]
        if len(parts) >= 2:
            first = parts[0]
            last = " ".join(parts[1:])
        elif parts:
            first = parts[0]
            last = ""
        else:
            first = ""
            last = ""

        first_slug = _slugify(first)
        last_slug = _slugify(last)
        if last_slug and first_slug:
            base = f"{last_slug}_{first_slug}_timeline"
        elif last_slug:
            base = f"{last_slug}_timeline"
        elif first_slug:
            base = f"{first_slug}_timeline"
        else:
            base = "timeline"

    return f"{base}_{today_token}.pdf"


def paint_timeline_to_printer(
    *,
    scene: QGraphicsScene,
    events: Sequence[Event],
    printer: QPrinter,
    current_person: Optional[str],
    label_color: QColor,
    make_font: FontFactory,
    category_color_fn: CategoryColorResolver,
) -> None:
    """Disegna la scena della timeline nel PDF, aggiungendo intestazione e legenda."""
    painter = QPainter(printer)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        layout = printer.pageLayout()
        paint_rect_px = layout.paintRectPixels(printer.resolution())
        paint_rect_pt = layout.paintRect(QPageLayout.Unit.Point)
        target = QRectF(paint_rect_px)
        source = QRectF(scene.sceneRect())

        page_height_px = max(1.0, float(target.height()))
        page_height_pt = max(1.0, float(paint_rect_pt.height()))
        today_display = date.today().strftime("%d/%m/%Y")
        person_display = (current_person or "").strip()
        title_text = f"Timeline {person_display}" if person_display else "Timeline"

        title_font_size = max(16, int(page_height_pt * 0.035))
        date_font_size = max(11, int(page_height_pt * 0.022))
        legend_font_size = max(9, int(page_height_pt * 0.018))

        title_font = make_font(title_font_size, ["Bold", "Black", "DemiBold"])
        date_font = make_font(date_font_size, ["Medium", "Normal"])
        legend_font = make_font(legend_font_size, ["Normal", "Light"])

        text_pen = QPen(label_color)
        painter.setPen(text_pen)

        top_padding = max(24.0, page_height_px * 0.025)
        between_title_date = max(6.0, page_height_px * 0.008)
        after_header_gap = max(16.0, page_height_px * 0.018)
        legend_gap = max(20.0, page_height_px * 0.025)

        current_y = target.top() + top_padding

        painter.setFont(title_font)
        title_metrics = painter.fontMetrics()
        title_height = title_metrics.height()
        title_rect = QRectF(target.left(), current_y, target.width(), title_height)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, title_text)
        current_y += title_height + between_title_date

        painter.setFont(date_font)
        date_metrics = painter.fontMetrics()
        date_height = date_metrics.height()
        date_rect = QRectF(target.left(), current_y, target.width(), date_height)
        painter.drawText(date_rect, Qt.AlignmentFlag.AlignCenter, today_display)
        current_y += date_height + after_header_gap

        legend_entries: List[str] = []
        seen_categories = set()
        for ev in events:
            cat = (getattr(ev, "categoria", "") or "").strip()
            key = cat.lower()
            if not cat or key in seen_categories:
                continue
            seen_categories.add(key)
            legend_entries.append(cat)

        legend_height = 0.0
        legend_line_spacing = max(6.0, page_height_px * 0.01)
        swatch_size = max(12.0, page_height_px * 0.016)

        if legend_entries:
            painter.setFont(make_font(max(legend_font_size, int(legend_font_size * 1.1)), ["Bold", "DemiBold", "Medium"]))
            legend_header_metrics = painter.fontMetrics()
            legend_header_height = legend_header_metrics.height()
            painter.setFont(legend_font)
            legend_metrics = painter.fontMetrics()
            entry_height = max(swatch_size, float(legend_metrics.height()))
            legend_height = (
                legend_header_height
                + legend_line_spacing
                + len(legend_entries) * entry_height
                + max(0, len(legend_entries) - 1) * legend_line_spacing
            )
            legend_height += legend_line_spacing

        chart_bottom_limit = target.bottom() - (legend_height + (legend_gap if legend_entries else 0))
        chart_top = current_y
        chart_rect_height = chart_bottom_limit - chart_top
        if chart_rect_height <= 0:
            chart_rect = target
        else:
            chart_rect = QRectF(target.left(), chart_top, target.width(), chart_rect_height)

        scene.render(
            painter,
            chart_rect,
            source,
            Qt.AspectRatioMode.KeepAspectRatio,
        )

        if legend_entries:
            legend_left = chart_rect.left() + max(20.0, target.width() * 0.035)
            legend_top = chart_rect.bottom() + legend_gap
            painter.setFont(make_font(max(legend_font_size, int(legend_font_size * 1.1)), ["Bold", "DemiBold", "Medium"]))
            legend_header_metrics = painter.fontMetrics()
            header_height = legend_header_metrics.height()
            header_rect = QRectF(legend_left, legend_top, target.width() * 0.4, header_height)
            painter.drawText(header_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Legenda")

            painter.setFont(legend_font)
            legend_metrics = painter.fontMetrics()
            entry_height = max(swatch_size, float(legend_metrics.height()))
            y = header_rect.bottom() + legend_line_spacing
            swatch_offset = (entry_height - swatch_size) / 2.0
            text_offset = max(8.0, target.width() * 0.01)

            for cat in legend_entries:
                cat_color = category_color_fn(cat)
                swatch_rect = QRectF(legend_left, y + swatch_offset, swatch_size, swatch_size)
                painter.fillRect(swatch_rect, QBrush(cat_color))
                painter.drawRect(swatch_rect)

                text_rect = QRectF(swatch_rect.right() + text_offset, y, target.width() * 0.4, entry_height)
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cat)
                y += entry_height + legend_line_spacing
    finally:
        painter.end()
