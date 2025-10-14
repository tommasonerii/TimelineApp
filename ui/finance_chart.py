# ui/finance_chart.py
from __future__ import annotations

from typing import Iterable, Dict, List, Tuple
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea,
    QHBoxLayout, QPushButton, QMenu
)
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QAction

import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.dates as mdates

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from core.forecast import forecast_cagrx_from_yfinance

MAX_SELECTED_INDEXES = 5
TODAY_COLOR_HEX = "#0f172a"

# Indici globali (Yahoo Finance tickers) + ETF indicizzati all'inflazione come "proxy"
AVAILABLE_INDEXES: Dict[str, str] = {
    "S&P 500": "^GSPC",
    "NASDAQ 100": "^NDX",
    "Dow Jones": "^DJI",
    "Euro Stoxx 50": "^STOXX50E",
    "FTSE 100": "^FTSE",
    "DAX": "^GDAXI",
    "CAC 40": "^FCHI",
    "Nikkei 225": "^N225",
    "Hang Seng": "^HSI",
    "Shanghai Composite": "000001.SS",
    "BSE Sensex": "^BSESN",
    "ASX 200": "^AXJO",
    "TSX Composite": "^GSPTSE",
    "Bovespa": "^BVSP",
    # Proxy inflazione (ETF inflation-linked)
    "US TIPS (TIP)": "TIP",
    "US TIPS short (VTIP)": "VTIP",
    "Euro IL Gov (INFL.MI)": "INFL.MI",
    "Euro IL Gov (EIIL.L)": "EIIL.L",
}

DEFAULT_SELECTION = [
    "S&P 500",
    "Euro Stoxx 50",
    "FTSE 100",
    "Nikkei 225",
]

# Colori CONSISTENTI per ogni indice
INDEX_COLORS: Dict[str, str] = {
    "S&P 500": "#1f77b4",
    "NASDAQ 100": "#6366f1",
    "Dow Jones": "#0ea5e9",
    "Euro Stoxx 50": "#22c55e",
    "FTSE 100": "#15803d",
    "DAX": "#a855f7",
    "CAC 40": "#ec4899",
    "Nikkei 225": "#f97316",
    "Hang Seng": "#f59e0b",
    "Shanghai Composite": "#ef4444",
    "BSE Sensex": "#14b8a6",
    "ASX 200": "#0f766e",
    "TSX Composite": "#8b5cf6",
    "Bovespa": "#047857",
    # ETF (proxy inflazione)
    "US TIPS (TIP)": "#7c3aed",
    "US TIPS short (VTIP)": "#4f46e5",
    "Euro IL Gov (INFL.MI)": "#ea580c",
    "Euro IL Gov (EIIL.L)": "#d97706",
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
        self._index_actions: Dict[str, QAction] = {}
        self._last_event_dates: List[datetime] = []

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
        self.selector_button.setStyleSheet("padding:6px 12px; border:1px solid #d1d5db; border-radius:8px; background:#f8fafc;")
        self.selector_menu = QMenu(self.selector_button)
        self.selector_button.setMenu(self.selector_menu)
        ctrl_layout.addWidget(self.selector_button, 0, Qt.AlignmentFlag.AlignVCenter)

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

        try:
            data = yf.download(
                tickers=list(selected_map.values()),
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=True
            )
        except Exception as e:
            self.status.setText(f"Errore download dati: {e}")
            self.canvas.draw_idle()
            self._annot = ax.annotate(
                "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            self._annot.set_visible(False)
            return

        if data is None or len(data) == 0:
            self.status.setText("Nessun dato scaricato.")
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
            color = INDEX_COLORS.get(name)
            base_price = float(base_row.get(name, float("nan")))
            if not np.isfinite(base_price) or base_price <= 0:
                continue

            today_price = float(aligned.loc[today_ts, name])
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
            y_all = []
            for d in event_idx:
                if d <= today_ts:
                    price = float(aligned.loc[d, name])
                    y_all.append(float((price / base_price - 1.0) * 100.0))
                else:
                    pred_val = None
                    if not y_future_prices.empty and d in y_future_prices.index:
                        pred_val = float(y_future_prices.loc[d])
                    if pred_val is not None:
                        y_all.append(float((pred_val / base_price - 1.0) * 100.0))
                    else:
                        y_all.append(y_today)

            sc = ax.scatter(event_idx, y_all, s=30, color=color, edgecolor="#0f172a", linewidths=0.5)
            self._scatters.append((sc, {"name": name, "x": event_idx.to_pydatetime(), "y": y_all}))

            # Punto "oggi"
            today_point = ax.scatter([today_ts], [y_today], s=52, color=TODAY_COLOR_HEX,
                                     edgecolor="#0f172a", linewidths=0.8, zorder=5)
            self._scatters.append((today_point, {
                "name": f"{name} (oggi)",
                "x": [today_ts.to_pydatetime()],
                "y": [float(y_today)],
            }))

        ax.axhline(0, linewidth=1, linestyle="--", alpha=0.45, color="#94a3b8")
        ax.set_ylabel("Variazione % da prima data")
        ax.set_xlabel("Date evento")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, ncols=2, fontsize=9, frameon=False, loc="upper left")

        self.canvas.draw_idle()

        sel_summary = ", ".join(self.selected_names) if self.selected_names else "—"
        self.status.setText(
            f"Intervallo: {self._last_event_dates[0].isoformat()} — {self._last_event_dates[-1].isoformat()} | "
            f"Indici selezionati: {sel_summary} | Punto oggi: {today_ts.date().isoformat()} | "
            "Futuro: modello CAGR-X (proxy Yahoo, tratteggiato)"
        )

        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
            fontsize=9
        )
        self._annot.set_visible(False)

    def _build_index_menu(self) -> None:
        self.selector_menu.clear()
        self._index_actions.clear()
        for name in self.available_indexes:
            action = QAction(name, self.selector_menu)
            action.setCheckable(True)
            action.setChecked(name in self.selected_names)
            action.toggled.connect(lambda checked, n=name: self._on_index_toggled(n, checked))
            self.selector_menu.addAction(action)
            self._index_actions[name] = action

    def _update_selection_summary(self) -> None:
        if self.selected_names:
            self.selection_summary.setText(", ".join(self.selected_names))
        else:
            self.selection_summary.setText("Nessun indice selezionato")

    def _on_index_toggled(self, name: str, checked: bool) -> None:
        if checked:
            if name not in self.selected_names:
                if len(self.selected_names) >= MAX_SELECTED_INDEXES:
                    action = self._index_actions.get(name)
                    if action is not None:
                        action.blockSignals(True)
                        action.setChecked(False)
                        action.blockSignals(False)
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
            y  = float(meta["y"][i])
            self._annot.xy = (mdates.date2num(dt), y)
            self._annot.set_text(f"{meta['name']}\n{dt:%Y-%m-%d}  •  {y:.1f}%")
            self._annot.set_visible(True)
            self.canvas.draw_idle()
            shown = True
            break

        if not shown and self._annot.get_visible():
            self._annot.set_visible(False)
            self.canvas.draw_idle()
