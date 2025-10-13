# ui/finance_chart.py
from __future__ import annotations

from typing import Iterable, Dict, List, Tuple
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea
from PyQt6.QtCore import Qt, QEvent
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.dates as mdates

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from core.forecast import forecast_cagrx_from_yfinance

# Indici globali (Yahoo Finance tickers)
DEFAULT_INDEXES: Dict[str, str] = {
    "S&P 500":       "^GSPC",
    "Euro Stoxx 50": "^STOXX50E",
    "FTSE 100":      "^FTSE",
    "Nikkei 225":    "^N225",
    "Hang Seng":     "^HSI",
}

# Colori CONSISTENTI per ogni indice
INDEX_COLORS: Dict[str, str] = {
    "S&P 500":       "#1f77b4",  # blue
    "Euro Stoxx 50": "#2ca02c",  # green
    "FTSE 100":      "#9467bd",  # purple
    "Nikkei 225":    "#ff7f0e",  # orange
    "Hang Seng":     "#7f7f7f",  # gray
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

        self.indexes = indexes or DEFAULT_INDEXES

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.title = QLabel("Indici globali — variazione % dalla prima data (CAGR-X per il futuro)")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setStyleSheet("color:#111; font-weight:600; margin: 4px 0;")
        lay.addWidget(self.title)

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
        """Ridisegna in base alle date evento."""
        self.fig.clear()
        self._scatters.clear()
        ax = self.fig.add_subplot(111)

        # Date evento
        ds = sorted({d.date() if isinstance(d, datetime) else d for d in dates})
        if not ds:
            self.status.setText("Nessuna data evento disponibile.")
            self.canvas.draw_idle()
            return

        event_idx = pd.to_datetime(ds)
        today_ts = pd.Timestamp(datetime.now().date())
        past_idx = event_idx[event_idx <= today_ts]
        future_idx = event_idx[event_idx > today_ts]

        # Intervallo download storico
        start = min(ds[0] - timedelta(days=7), (today_ts - pd.DateOffset(years=10)).date())
        end   = max(ds[-1], today_ts.date()) + timedelta(days=7)

        # Scarica prezzi
        try:
            tickers = list(self.indexes.values())
            data = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # end esclusa
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=True
            )
        except Exception as e:
            self.status.setText(f"Errore download dati: {e}")
            self.canvas.draw_idle()
            return

        if data is None or len(data) == 0:
            self.status.setText("Nessun dato scaricato.")
            self.canvas.draw_idle()
            return

        # DataFrame prezzi (Adj Close) colonne = nomi umani
        try:
            adj = {}
            for name, ticker in self.indexes.items():
                try:
                    ser = data[ticker]['Adj Close']
                except Exception:
                    ser = data['Adj Close'][ticker]
                adj[name] = ser
            prices = pd.DataFrame(adj).sort_index()
        except Exception:
            if isinstance(data.columns, pd.MultiIndex):
                prices = data.xs('Adj Close', axis=1, level=1)
                rename_map = {v: k for k, v in self.indexes.items()}
                prices.rename(columns=rename_map, inplace=True)
            else:
                self.status.setText("Formato dati inaspettato (niente Adj Close).")
                self.canvas.draw_idle()
                return

        prices = prices.ffill()

        # Base di normalizzazione = prezzo alla prima data evento
        base_row = prices.reindex(prices.index.union(event_idx)).ffill().loc[event_idx[0]]

        # Disegna per ciascun indice
        for name in prices.columns:
            color = INDEX_COLORS.get(name, None)
            label_used = False

            # passato (linea piena)
            if len(past_idx) > 0:
                past_series = prices.reindex(prices.index.union(past_idx)).ffill().loc[past_idx, name]
                y_past = (past_series / base_row[name] - 1.0) * 100.0
                ax.plot(past_idx, y_past.values.astype(float), linewidth=2, label=name, color=color)
                label_used = True
            else:
                y_past = pd.Series(dtype=float)

            # futuro (CAGR-X) in tratteggio
            if len(future_idx) > 0:
                hist_for_model = prices[name].dropna()
                y_future_prices = forecast_cagrx_from_yfinance(hist_for_model, future_idx, lookback_years=5, macro_years=5)
                y_future = (y_future_prices / base_row[name] - 1.0) * 100.0

                if len(y_past) > 0:
                    x_dash = [past_idx[-1]] + list(future_idx)
                    y_dash = [float(y_past.iloc[-1])] + list(y_future.values.astype(float))
                else:
                    x_dash = list(future_idx)
                    y_dash = list(y_future.values.astype(float))

                ax.plot(x_dash, y_dash, linewidth=2, linestyle="--",
                        label=(name if not label_used else "_nolegend_"), color=color)

            # marker + tooltip su TUTTI gli eventi (passati + previsti)
            y_all = []
            for d in event_idx:
                if len(past_idx) > 0 and d in past_idx:
                    val = prices.reindex(prices.index.union([d])).ffill().loc[d, name]
                    y_all.append(float((val / base_row[name] - 1.0) * 100.0))
                else:
                    # per futuro, usa la proiezione
                    pred_val = y_future_prices.loc[d] if len(future_idx) > 0 and d in future_idx and d in y_future_prices.index else None
                    if pred_val is not None:
                        y_all.append(float((pred_val / base_row[name] - 1.0) * 100.0))
                    else:
                        y_all.append(float(y_past.iloc[-1]) if len(y_past) > 0 else 0.0)

            sc = ax.scatter(event_idx, y_all, s=30, color=color, edgecolor="#0f172a", linewidths=0.5)
            self._scatters.append((sc, {"name": name, "x": event_idx.to_pydatetime(), "y": y_all}))

        # look & feel
        ax.axhline(0, linewidth=1, linestyle="--", alpha=0.5, color="#94a3b8")
        ax.grid(True, which="major", alpha=0.25)
        ax.set_ylabel("Variazione % da prima data")
        ax.set_xlabel("Date evento")
        ax.legend(ncols=2, fontsize=9, frameon=False, loc="upper left")

        self.fig.tight_layout()
        self.canvas.draw_idle()

        self.status.setText(
            f"Intervallo: {ds[0].isoformat()} — {ds[-1].isoformat()} | "
            f"Indici: {', '.join(self.indexes.keys())} | "
            f"Futuro: modello CAGR-X (proxy Yahoo, tratteggiato)"
        )

        # Annotazione condivisa per hover
        ax = self.fig.axes[0]
        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(8, 10), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
            fontsize=9
        )
        self._annot.set_visible(False)

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
