# ui/finance_chart.py
from __future__ import annotations

from typing import Iterable, Dict, List, Tuple
from datetime import datetime, timedelta, date
from collections import OrderedDict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea,
    QHBoxLayout, QPushButton, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.dates as mdates

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from core.forecast import forecast_cagrx_from_yfinance

MAX_SELECTED_INDEXES = 5
TODAY_COLOR_HEX = "#0f172a"


class IndexPopup(QFrame):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background:#ffffff; border:1px solid #cbd5e1; border-radius:8px;")

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)


IndexMeta = Tuple[str, str, str]

INDEX_METADATA: List[IndexMeta] = [
    ("S&P 500", "^GSPC", "US"),
    ("NASDAQ 100", "^NDX", "US"),
    ("Dow Jones", "^DJI", "US"),
    ("Euro Stoxx 50", "^STOXX50E", "EU"),
    ("FTSE 100", "^FTSE", "UK"),
    ("DAX", "^GDAXI", "DE"),
    ("CAC 40", "^FCHI", "FR"),
    ("IBEX 35", "^IBEX", "ES"),
    ("FTSE MIB", "FTSEMIB.MI", "IT"),
    ("OMX Stockholm 30", "^OMXS30", "SE"),
    ("AEX", "^AEX", "NL"),
    ("SMI", "^SSMI", "CH"),
    ("Nikkei 225", "^N225", "JP"),
    ("Hang Seng", "^HSI", "HK"),
    ("Shanghai Composite", "000001.SS", "CN"),
    ("BSE Sensex", "^BSESN", "IN"),
    ("ASX 200", "^AXJO", "AU"),
    ("TSX Composite", "^GSPTSE", "CA"),
    ("Bovespa", "^BVSP", "BR"),
    ("US TIPS (TIP)", "TIP", "US"),
    ("US TIPS short (VTIP)", "VTIP", "US"),
    ("Euro IL Gov (INFL.MI)", "INFL.MI", "EU"),
    ("Euro IL Gov (EIIL.L)", "EIIL.L", "EU"),
]

AVAILABLE_INDEXES: Dict[str, str] = {
    f"{name} ({country})": ticker for name, ticker, country in INDEX_METADATA
}

DEFAULT_SELECTION = [
    "S&P 500 (US)",
    "Euro Stoxx 50 (EU)",
    "FTSE MIB (IT)",
    "Nikkei 225 (JP)",
]

# Colori CONSISTENTI per ogni indice
INDEX_COLORS: Dict[str, str] = {
    "S&P 500 (US)": "#1f77b4",
    "NASDAQ 100 (US)": "#6366f1",
    "Dow Jones (US)": "#0ea5e9",
    "Euro Stoxx 50 (EU)": "#22c55e",
    "FTSE 100 (UK)": "#15803d",
    "DAX (DE)": "#a855f7",
    "CAC 40 (FR)": "#ec4899",
    "IBEX 35 (ES)": "#f59e0b",
    "FTSE MIB (IT)": "#fb923c",
    "OMX Stockholm 30 (SE)": "#0d9488",
    "AEX (NL)": "#14b8a6",
    "SMI (CH)": "#ef4444",
    "Nikkei 225 (JP)": "#f97316",
    "Hang Seng (HK)": "#facc15",
    "Shanghai Composite (CN)": "#dc2626",
    "BSE Sensex (IN)": "#0ea5a8",
    "ASX 200 (AU)": "#0f766e",
    "TSX Composite (CA)": "#8b5cf6",
    "Bovespa (BR)": "#047857",
    # ETF (proxy inflazione)
    "US TIPS (TIP) (US)": "#7c3aed",
    "US TIPS short (VTIP) (US)": "#4f46e5",
    "Euro IL Gov (INFL.MI) (EU)": "#ea580c",
    "Euro IL Gov (EIIL.L) (EU)": "#d97706",
}


class FinanceChart(QWidget):
    """
    Grafico delle variazioni % normalizzate alla prima data degli eventi.
    - Storico via yfinance (Adj Close).
    - Colori fissi per indice (consistenti).
    - Tooltip su ogni PALLINO: mostra la variazione % a quella data.
    - Futuro: previsione CAGR-X (proxy macro Yahoo) in linea tratteggiata.
    """

    def __init__(self, parent=None, indexes: Dict[str, str] | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        base_indexes = indexes or AVAILABLE_INDEXES
        # mantieni l'ordine dichiarato
        self.available_indexes = {name: base_indexes[name] for name in base_indexes}
        self.selected_names = [name for name in DEFAULT_SELECTION if name in self.available_indexes]
        if not self.selected_names:
            self.selected_names = list(self.available_indexes.keys())[:MAX_SELECTED_INDEXES]
        self._index_checkboxes: Dict[str, QCheckBox] = {}
        self._last_event_dates: List[datetime] = []
        self._history_cache: "OrderedDict[Tuple[Tuple[str, ...], str, str], pd.DataFrame]" = OrderedDict()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.title = QLabel("Indici globali — variazione % dalla prima data (CAGR-X per il futuro)")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setStyleSheet("color:#111; font-weight:600; margin: 4px 0;")
        lay.addWidget(self.title)

        # Controls (selezione indici)
        controls = QWidget()
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(8)

        lbl = QLabel("Indici (max 5):")
        lbl.setStyleSheet("color:#374151;")
        ctrl_layout.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self.selector_button = QPushButton("Scegli indici")
        self.selector_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selector_button.setCheckable(True)
        self.selector_button.setStyleSheet(
            "padding:6px 12px; border:1px solid #d1d5db; border-radius:8px; background:#f8fafc;"
        )
        self.selector_button.toggled.connect(self._toggle_popup)
        ctrl_layout.addWidget(self.selector_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.selector_popup = IndexPopup(self)
        self.selector_popup.setMinimumWidth(240)
        popup_layout = QVBoxLayout(self.selector_popup)
        popup_layout.setContentsMargins(8, 8, 8, 8)
        popup_layout.setSpacing(6)
        self.selector_scroll = QScrollArea(self.selector_popup)
        self.selector_scroll.setWidgetResizable(True)
        self.selector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.selector_scroll.setMaximumHeight(260)
        popup_layout.addWidget(self.selector_scroll)
        self.selector_list = QWidget()
        self.selector_scroll.setWidget(self.selector_list)
        self.selector_list_layout = QVBoxLayout(self.selector_list)
        self.selector_list_layout.setContentsMargins(0, 0, 0, 0)
        self.selector_list_layout.setSpacing(4)
        self.selector_popup.closed.connect(lambda: self.selector_button.setChecked(False))

        self.selection_summary = QLabel("")
        self.selection_summary.setStyleSheet("color:#1f2937; font-size:12px;")
        self.selection_summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ctrl_layout.addWidget(self.selection_summary, 1, Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(controls)

        self._build_index_menu()
        self._update_selection_summary()

        self.fig = Figure(figsize=(6, 2.8), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.canvas.installEventFilter(self)  # scroll → QScrollArea
        lay.addWidget(self.canvas, stretch=1)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status.setStyleSheet("color:#6b7280; font-size:12px;")
        lay.addWidget(self.status)

        # hover state
        self._annot = None
        self._hover_cid = self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self._scatters: List[Tuple] = []  # [(PathCollection, dict(meta))]

    @staticmethod
    def _format_value(value: float) -> str:
        s = f"{value:,.2f}"
        return s.replace(",", "\u202f").replace(".", ",")

    def _cache_download(self, tickers: Tuple[str, ...], start: datetime | date, end: datetime | date) -> pd.DataFrame | None:
        """Scarica (o recupera dalla cache) la storia prezzi per i ticker richiesti."""
        if not tickers:
            return None

        download_end = (end + timedelta(days=1)).isoformat()
        cache_key = (tickers, start.isoformat(), download_end)
        cached = self._history_cache.get(cache_key)
        if cached is not None:
            # Move-to-end per avere una LRU semplice
            self._history_cache.move_to_end(cache_key)
            return cached.copy()

        try:
            data = yf.download(
                tickers=list(tickers),
                start=start.isoformat(),
                end=download_end,
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=True
            )
        except Exception:
            return None

        if data is None or len(data) == 0:
            return None

        self._history_cache[cache_key] = data.copy()
        # Limita la cache per non crescere senza controllo
        while len(self._history_cache) > 6:
            self._history_cache.popitem(last=False)
        return data.copy()

    # ---------- Rerouting scroll ----------
    def eventFilter(self, obj, event):
        if obj is self.canvas and event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return False
            scroll = self._find_scroll_area()
            if scroll is not None:
                dy = event.pixelDelta().y() or (event.angleDelta().y() // 2)
                bar = scroll.verticalScrollBar()
                bar.setValue(bar.value() - int(dy))
                return True
        return super().eventFilter(obj, event)

    def _find_scroll_area(self) -> QScrollArea | None:
        w = self.parent()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parent()
        return w if isinstance(w, QScrollArea) else None

    # ---------- API ----------
    def set_event_dates(self, dates: Iterable[datetime]) -> None:
        """Aggiorna il grafico memorizzando le date evento correnti."""
        ds = sorted({d.date() if isinstance(d, datetime) else d for d in dates})
        self._last_event_dates = ds
        self._draw_chart()

    def _draw_chart(self) -> None:
        self.fig.clear()
        self._scatters.clear()

        ax = self.fig.add_subplot(111)
        ax.set_facecolor("#fcfcfd")
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#e5e7eb")
        ax.grid(True, which="major", alpha=0.25)
        ax.tick_params(axis="both", labelsize=10)

        if not self._last_event_dates:
            ax.axhline(0, linewidth=1, linestyle="--", alpha=0.45, color="#94a3b8")
            self.status.setText("Nessuna data evento disponibile.")
            self.canvas.draw_idle()
            self._annot = ax.annotate(
                "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            self._annot.set_visible(False)
            return

        if not self.selected_names:
            ax.axhline(0, linewidth=1, linestyle="--", alpha=0.45, color="#94a3b8")
            self.status.setText("Seleziona almeno un indice (max 5) dal menu sopra il grafico.")
            self.canvas.draw_idle()
            self._annot = ax.annotate(
                "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            self._annot.set_visible(False)
            return

        event_idx = pd.to_datetime(self._last_event_dates)
        today_ts = pd.Timestamp(datetime.now().date())
        past_idx = event_idx[event_idx <= today_ts]
        future_idx = event_idx[event_idx > today_ts]

        start = min(self._last_event_dates[0] - timedelta(days=7), (today_ts - pd.DateOffset(years=10)).date())
        end = max(self._last_event_dates[-1], today_ts.date()) + timedelta(days=7)

        selected_map = {name: self.available_indexes[name] for name in self.selected_names}
        skipped_indexes: List[str] = []

        tickers_tuple = tuple(selected_map.values())
        data = self._cache_download(tickers_tuple, start, end)
        if data is None:
            self.status.setText("Errore download dati o dati assenti.")
            self.canvas.draw_idle()
            self._annot = ax.annotate(
                "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            self._annot.set_visible(False)
            return

        try:
            adj = {}
            for name, ticker in selected_map.items():
                try:
                    ser = data[ticker]["Adj Close"]
                except Exception:
                    ser = data["Adj Close"][ticker]
                adj[name] = ser
            prices = pd.DataFrame(adj).sort_index()
        except Exception:
            if isinstance(data.columns, pd.MultiIndex):
                prices = data.xs("Adj Close", axis=1, level=1)
                rename_map = {v: k for k, v in selected_map.items()}
                prices.rename(columns=rename_map, inplace=True)
            else:
                self.status.setText("Formato dati inaspettato (niente Adj Close).")
                self.canvas.draw_idle()
                self._annot = ax.annotate(
                    "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                    fontsize=9
                )
                self._annot.set_visible(False)
                return

        prices = prices.ffill()
        expanded_index = prices.index.union(event_idx).union(pd.DatetimeIndex([today_ts]))
        aligned = prices.reindex(expanded_index).ffill()
        base_row = aligned.loc[event_idx[0]]

        for name in aligned.columns:
            if name not in selected_map:
                continue
            color = INDEX_COLORS.get(name, "#1f2937")
            base_price = float(base_row.get(name, float("nan")))
            if not np.isfinite(base_price) or base_price <= 0:
                skipped_indexes.append(name)
                continue

            today_price = float(aligned.loc[today_ts, name])
            if not np.isfinite(today_price):
                skipped_indexes.append(name)
                continue
            y_today = (today_price / base_price - 1.0) * 100.0

            line_x: List[pd.Timestamp] = []
            line_y: List[float] = []
            if len(past_idx) > 0:
                past_vals = aligned.loc[past_idx, name]
                line_x = list(past_idx)
                line_y = list(((past_vals / base_price - 1.0) * 100.0).astype(float))

            if today_ts >= event_idx[0]:
                if not line_x or line_x[-1] != today_ts:
                    line_x.append(today_ts)
                    line_y.append(y_today)

            label_used = False
            if line_x:
                ax.plot(line_x, line_y, linewidth=2, color=color, label=name)
                label_used = True

            y_future_prices = pd.Series(dtype=float)
            if len(future_idx) > 0:
                hist_for_model = prices[name].dropna()
                try:
                    y_future_prices = forecast_cagrx_from_yfinance(hist_for_model, future_idx, lookback_years=5, macro_years=5)
                except Exception:
                    y_future_prices = pd.Series(dtype=float)

                if not y_future_prices.empty:
                    y_future = y_future_prices.reindex(future_idx)
                    y_future = y_future.fillna(method="ffill").fillna(method="bfill")
                    y_future = (y_future / base_price - 1.0) * 100.0
                    dash_x = [today_ts] + list(future_idx)
                    dash_y = [y_today] + list(y_future.values.astype(float))
                    ax.plot(dash_x, dash_y, linewidth=2, linestyle="--",
                            color=color, label=(name if not label_used else "_nolegend_"))
                elif not label_used:
                    ax.plot([today_ts], [y_today], linewidth=2, color=color, label=name)
                    label_used = True
            elif not label_used:
                ax.plot([today_ts], [y_today], linewidth=2, color=color, label=name)
                label_used = True

            # Punti evento
            y_all: List[float] = []
            value_all: List[float] = []
            for d in event_idx:
                if d <= today_ts:
                    price = float(aligned.loc[d, name])
                    y_all.append(float((price / base_price - 1.0) * 100.0))
                    value_all.append(price)
                else:
                    pred_val = None
                    if not y_future_prices.empty and d in y_future_prices.index:
                        pred_val = float(y_future_prices.loc[d])
                    if pred_val is not None:
                        y_all.append(float((pred_val / base_price - 1.0) * 100.0))
                        value_all.append(pred_val)
                    else:
                        y_all.append(y_today)
                        value_all.append(today_price)

            sc = ax.scatter(event_idx, y_all, s=30, color=color, edgecolor="#0f172a",
                            linewidths=0.5, picker=True)
            self._scatters.append((
                sc,
                {
                    "name": name,
                    "x": list(event_idx.to_pydatetime()),
                    "pct": y_all,
                    "value": value_all,
                }
            ))

            # Punto "oggi"
            today_point = ax.scatter([today_ts], [y_today], s=52, color=TODAY_COLOR_HEX,
                                     edgecolor="#0f172a", linewidths=0.8, zorder=5, picker=True)
            self._scatters.append((today_point, {
                "name": f"{name} — oggi",
                "x": [today_ts.to_pydatetime()],
                "pct": [float(y_today)],
                "value": [float(today_price)],
            }))

        ax.axhline(0, linewidth=1, linestyle="--", alpha=0.45, color="#94a3b8")
        ax.set_ylabel("Variazione % da prima data")
        ax.set_xlabel("Date evento")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, ncols=2, fontsize=9, frameon=False, loc="upper left")

        self.canvas.draw_idle()

        sel_summary = ", ".join(self.selected_names) if self.selected_names else "—"
        status_text = (
            f"Intervallo: {self._last_event_dates[0].isoformat()} — {self._last_event_dates[-1].isoformat()} | "
            f"Indici selezionati: {sel_summary} | Punto oggi: {today_ts.date().isoformat()} | "
            "Futuro: modello CAGR-X (proxy Yahoo, tratteggiato)"
        )
        if skipped_indexes:
            skipped = ", ".join(skipped_indexes)
            status_text += f" | Dati mancanti per: {skipped}"
        self.status.setText(status_text)

        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
            fontsize=9
        )
        self._annot.set_visible(False)

    def _build_index_menu(self) -> None:
        while self.selector_list_layout.count():
            item = self.selector_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._index_checkboxes.clear()

        for name in self.available_indexes:
            checkbox = QCheckBox(name, self.selector_list)
            checkbox.setChecked(name in self.selected_names)
            checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
            checkbox.setStyleSheet("padding:2px 4px;")
            checkbox.toggled.connect(lambda checked, n=name: self._on_index_toggled(n, checked))
            self.selector_list_layout.addWidget(checkbox)
            self._index_checkboxes[name] = checkbox

        self.selector_list_layout.addStretch(1)

    def _update_selection_summary(self) -> None:
        if self.selected_names:
            self.selection_summary.setText(", ".join(self.selected_names))
        else:
            self.selection_summary.setText("Nessun indice selezionato")

    def _toggle_popup(self, checked: bool) -> None:
        if checked:
            self._position_popup()
            self.selector_popup.show()
            self.selector_popup.raise_()
        else:
            self.selector_popup.hide()

    def _position_popup(self) -> None:
        popup_width = max(self.selector_button.width(), 240)
        hint_height = self.selector_popup.sizeHint().height()
        popup_height = min(max(hint_height, 120), 360)
        self.selector_popup.resize(popup_width, popup_height)
        global_pos = self.selector_button.mapToGlobal(self.selector_button.rect().bottomLeft())
        self.selector_popup.move(global_pos)

    def _on_index_toggled(self, name: str, checked: bool) -> None:
        if checked:
            if name not in self.selected_names:
                if len(self.selected_names) >= MAX_SELECTED_INDEXES:
                    checkbox = self._index_checkboxes.get(name)
                    if checkbox is not None:
                        checkbox.blockSignals(True)
                        checkbox.setChecked(False)
                        checkbox.blockSignals(False)
                    self.status.setText(f"Puoi selezionare al massimo {MAX_SELECTED_INDEXES} indici.")
                    return
                self.selected_names.append(name)
        else:
            if name in self.selected_names:
                self.selected_names.remove(name)

        self._update_selection_summary()
        self._draw_chart()

    # ---------- Hover: mostra % al passaggio sui pallini ----------
    def _on_hover(self, event):
        if self._annot is None or event.inaxes is None:
            return
        shown = False
        for sc, meta in self._scatters:
            contains, ind = sc.contains(event)
            if not contains or not ind.get("ind"):
                continue
            i = ind["ind"][0]
            dt = meta["x"][i]
            pct_vals = meta.get("pct") or meta.get("y")
            pct = float(pct_vals[i]) if pct_vals is not None else float("nan")
            val_list = meta.get("value")
            value = float(val_list[i]) if val_list and np.isfinite(val_list[i]) else None
            self._annot.xy = (mdates.date2num(dt), pct)
            detail_parts = [f"{dt:%Y-%m-%d}"]
            if value is not None:
                detail_parts.append(self._format_value(value))
            if np.isfinite(pct):
                detail_parts.append(f"{pct:+.1f}%")
            self._annot.set_text(f"{meta['name']}\n" + "  •  ".join(detail_parts))
            self._annot.set_visible(True)
            self.canvas.draw_idle()
            shown = True
            break

        if not shown and self._annot.get_visible():
            self._annot.set_visible(False)
            self.canvas.draw_idle()
