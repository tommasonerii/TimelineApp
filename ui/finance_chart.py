# ui/finance_chart.py
from __future__ import annotations

from typing import Iterable, Dict
from datetime import datetime, timedelta

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea
from PyQt6.QtCore import Qt, QEvent
import pandas as pd
import yfinance as yf

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas


# Indici globali (Yahoo Finance tickers)
DEFAULT_INDEXES: Dict[str, str] = {
    "S&P 500":      "^GSPC",
    "Euro Stoxx 50":"^STOXX50E",
    "FTSE 100":     "^FTSE",
    "Nikkei 225":   "^N225",
    "Hang Seng":    "^HSI",
}

class FinanceChart(QWidget):
    """
    Grafico delle variazioni percentuali normalizzate a 0% alla prima data.
    - Usa yfinance per scaricare gli Adj Close degli indici.
    - Allinea i valori alle date degli eventi (ultimo prezzo disponibile <= data evento).
    - Scroll del trackpad reindirizzato alla QScrollArea madre (zoom solo con CTRL).
    - Linea tratteggiata per i tratti futuri (dall’ultimo punto <= oggi in poi).
    """

    def __init__(self, parent=None, indexes: Dict[str, str] | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.indexes = indexes or DEFAULT_INDEXES

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.title = QLabel("Andamento indici globali (variazione % dalla prima data)")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setStyleSheet("color:#111; font-weight:600; margin: 4px 0;")
        lay.addWidget(self.title)

        self.fig = Figure(figsize=(6, 2.8), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.canvas.installEventFilter(self)  # per lo scroll
        lay.addWidget(self.canvas, stretch=1)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status.setStyleSheet("color:#6b7280; font-size:12px;")
        lay.addWidget(self.status)

    # ---------- Event filter: rerouting dello scroll alla QScrollArea ----------
    def eventFilter(self, obj, event):
        if obj is self.canvas and event.type() == QEvent.Type.Wheel:
            # CTRL = lascia zoom/pan a Matplotlib
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return False
            scroll = self._find_scroll_area()
            if scroll is not None:
                dy = event.pixelDelta().y()
                if dy == 0:
                    dy = event.angleDelta().y() // 2
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
        """Aggiorna il grafico in base alla lista di date eventi."""
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        # Normalizza/ordina date (array di date senza orario)
        ds = sorted({d.date() if isinstance(d, datetime) else d for d in dates})
        if not ds:
            self.status.setText("Nessuna data evento disponibile.")
            self.canvas.draw_idle()
            return

        start = ds[0] - timedelta(days=7)
        end   = ds[-1] + timedelta(days=7)

        # Scarica prezzi (Adj Close)
        try:
            tickers = list(self.indexes.values())
            data = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # end esclusiva
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

        # Estrai Adj Close in DataFrame colonne = nomi umani
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

        # Forward-fill e selezione dei punti sulle date evento (ultimo <= data evento)
        prices = prices.ffill()
        event_idx = pd.to_datetime(ds)
        aligned = prices.reindex(prices.index.union(event_idx)).ffill().loc[event_idx]

        # Normalizza alla prima data (0% = base)
        base = aligned.iloc[0]
        norm = (aligned / base - 1.0) * 100.0  # DataFrame, index = event_idx

        # Cutoff tra passato e futuro (oggi incluso = passato)
        today_ts = pd.Timestamp(datetime.now().date())
        past_idx = event_idx[event_idx <= today_ts]
        future_idx = event_idx[event_idx > today_ts]

        # Disegno per ogni indice: solido nel passato, tratteggiato nel futuro
        for col in norm.columns:
            label_added = False

            # Segmento passato
            if len(past_idx) > 0:
                y_past = norm.loc[past_idx, col].values.astype(float)
                ax.plot(past_idx, y_past, linewidth=2, label=col)
                label_added = True

            # Segmento futuro (dall'ultimo passato → futuri), tratteggiato
            if len(future_idx) > 0:
                if len(past_idx) > 0:
                    start_x = past_idx[-1]
                    start_y = float(norm.loc[start_x, col])
                else:
                    # nessun punto passato: tratto tutto in futuro (dalla prima data)
                    start_x = future_idx[0]
                    start_y = float(norm.loc[start_x, col])

                x_dashed = [start_x] + list(future_idx)
                y_dashed = [start_y] + list(norm.loc[future_idx, col].values.astype(float))

                ax.plot(
                    x_dashed, y_dashed,
                    linewidth=2,
                    linestyle="--",
                    label=(col if not label_added else "_nolegend_")  # evita duplicati in legenda
                )

            # Marker sui punti (tutti)
            y_all = norm[col].values.astype(float)
            ax.scatter(event_idx, y_all, s=20)

        # Asse, griglia, labels
        ax.axhline(0, linewidth=1, linestyle="--", alpha=0.6)
        ax.grid(True, which="major", alpha=0.25)
        ax.set_ylabel("Variazione % da prima data")
        ax.set_xlabel("Date evento")
        ax.legend(ncols=2, fontsize=9, frameon=False, loc="upper left")

        self.fig.tight_layout()
        self.canvas.draw_idle()

        self.status.setText(
            f"Intervallo: {ds[0].isoformat()} — {ds[-1].isoformat()}  |  Indici: {', '.join(self.indexes.keys())}"
        )
