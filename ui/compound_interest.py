# ui/compound_interest.py
from __future__ import annotations

from datetime import datetime, date
from typing import Iterable, Optional, List, Tuple, Dict

import numpy as np
import pandas as pd

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QDoubleSpinBox,
    QSpinBox, QPushButton, QSizePolicy, QScrollArea
)

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import FuncFormatter
import matplotlib.dates as mdates

from core.compounding import CompoundParams, simulate_compound


class CompoundInterestWidget(QWidget):
    """
    Calcolatore interesse composto (GUI) che usa core.compounding.
    - Parametri regolabili
    - Parte dalla prima data selezionata (set_start_date)
    - Pallini + etichette evento (set_event_points) e tooltip al volo
    - NESSUNO zoom: lo scroll a due dita viene sempre girato alla QScrollArea
    - Tooltip anche quando passi SULLA LINEA (valore in quel punto)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(820)  # più grande degli altri widget

        self._start_dt: Optional[datetime] = None
        self._event_points: List[Tuple[date, str]] = []  # (data, titolo)

        # ---- Titolo
        self.title = QLabel("Calcolatore interesse composto (dalla prima data)")
        self.title.setStyleSheet("color:#111; font-weight:600; margin: 4px 0;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # ---- Parametri
        self.spin_initial = QDoubleSpinBox(); self._cfg_money(self.spin_initial, 10_000.0, " €", 0.0, 1e12, 500.0)
        self.spin_monthly = QDoubleSpinBox(); self._cfg_money(self.spin_monthly,   300.0, " €/mese", 0.0, 1e9, 50.0)

        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(-100.0, 100.0); self.spin_rate.setDecimals(3)
        self.spin_rate.setValue(5.0); self.spin_rate.setSuffix(" % annuo"); self.spin_rate.setSingleStep(0.25)

        self.spin_mgmt = QDoubleSpinBox()
        self.spin_mgmt.setRange(0.0, 100.0); self.spin_mgmt.setDecimals(3)
        self.spin_mgmt.setValue(0.30); self.spin_mgmt.setSuffix(" % annuo (gestione)"); self.spin_mgmt.setSingleStep(0.10)

        self.spin_overnight = QDoubleSpinBox()
               # % giornaliero addizionale (0–5)
        self.spin_overnight.setRange(0.0, 5.0); self.spin_overnight.setDecimals(4)
        self.spin_overnight.setValue(0.0000); self.spin_overnight.setSuffix(" % giorn."); self.spin_overnight.setSingleStep(0.01)

        self.spin_years = QSpinBox()
        self.spin_years.setRange(1, 100); self.spin_years.setValue(20); self.spin_years.setSuffix(" anni")

        self.spin_day = QSpinBox()
        self.spin_day.setRange(1, 28); self.spin_day.setValue(1); self.spin_day.setSuffix("° giorno del mese")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(12); form.setVerticalSpacing(6)
        form.addRow("Capitale iniziale", self.spin_initial)
        form.addRow("Versamento mensile", self.spin_monthly)
        form.addRow("Tasso annuo", self.spin_rate)
        form.addRow("Commissione gestione", self.spin_mgmt)
        form.addRow("Commissione overnight", self.spin_overnight)
        form.addRow("Orizzonte", self.spin_years)
        form.addRow("Giorno versamento", self.spin_day)

        self.btn_calc = QPushButton("Ricalcola"); self.btn_calc.setCursor(Qt.CursorShape.PointingHandCursor)

        controls = QWidget()
        row = QHBoxLayout(controls); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(12)
        row.addLayout(form); row.addWidget(self.btn_calc, 0, Qt.AlignmentFlag.AlignBottom)

        # ---- Grafico (niente zoom)
        self.fig = Figure(figsize=(8.6, 4.4), dpi=100, constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(720)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.canvas.installEventFilter(self)             # scroll -> QScrollArea
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # ---- Status
        self.status = QLabel("")
        self.status.setStyleSheet("color:#6b7280; font-size:12px;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # ---- Root
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(8)
        root.addWidget(self.title)
        root.addWidget(controls)
        root.addWidget(self.canvas, 2)
        root.addWidget(self.status)

        # Signals
        self.btn_calc.clicked.connect(self.recompute)
        for w in (self.spin_initial, self.spin_monthly, self.spin_rate,
                  self.spin_mgmt, self.spin_overnight, self.spin_years, self.spin_day):
            w.valueChanged.connect(self.recompute)

        # Hover state
        self._scatter = None                 # punti evento (matplotlib PathCollection)
        self._annot = None                   # tooltip condiviso
        self._annot_ax = None
        self._hover_cid = self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        # dati linea per hover (x in numeri matplotlib, y in float)
        self._xline = None
        self._yline = None
        self._line_marker = None            # piccolo marker che segue il mouse
        self._ev_points_xy: List[Tuple[datetime, float, str]] = []  # (dt, value, title)

    # ---------- Public API ----------
    def set_start_date(self, dt: Optional[datetime]) -> None:
        self._start_dt = dt
        self.recompute()

    def set_event_points(self, points: Iterable[Tuple[datetime, str]]) -> None:
        # salva (data, titolo) come date pure e ordina
        self._event_points = sorted(
            [(p[0].date() if isinstance(p[0], datetime) else p[0], str(p[1])) for p in points]
        )
        self.recompute()

    # retrocompatibilità
    def set_event_dates(self, dates: Iterable[datetime]) -> None:
        self.set_event_points([(d, "") for d in dates])

    # ---------- Interni ----------
    def _cfg_money(self, sp: QDoubleSpinBox, value: float, suffix: str, minv: float, maxv: float, step: float):
        sp.setRange(minv, maxv); sp.setDecimals(2); sp.setValue(value); sp.setSuffix(suffix); sp.setSingleStep(step)

    def _fmt_eur(self, v: float, decimals: int = 2) -> str:
        s = f"{v:,.{decimals}f}"
        return "€ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

    def eventFilter(self, obj, event):
        # Nessuno zoom: inoltra SEMPRE lo scroll al contenitore scrollabile
        if obj is self.canvas and event.type() == QEvent.Type.Wheel:
            scroll = self._find_scroll_area()
            if scroll is not None:
                dy = event.pixelDelta().y() or (event.angleDelta().y() // 2)
                bar = scroll.verticalScrollBar(); bar.setValue(bar.value() - int(dy))
                return True
        return super().eventFilter(obj, event)

    def _find_scroll_area(self) -> QScrollArea | None:
        w = self.parent()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parent()
        return w if isinstance(w, QScrollArea) else None

    def _params(self) -> CompoundParams:
        return CompoundParams(
            initial=float(self.spin_initial.value()),
            monthly=float(self.spin_monthly.value()),
            annual_rate=float(self.spin_rate.value())/100.0,
            mgmt_fee_annual=float(self.spin_mgmt.value())/100.0,
            overnight_daily=float(self.spin_overnight.value())/100.0,
            years=int(self.spin_years.value()),
            contribution_day=int(self.spin_day.value()),
        )

    def recompute(self) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        if self._start_dt is None:
            self.status.setText("Seleziona una persona con almeno un evento: userò la prima data come partenza.")
            self.canvas.draw_idle(); return

        start_d = self._start_dt.date()
        p = self._params()
        try:
            df = simulate_compound(start_d, p)
        except Exception as e:
            self.status.setText(f"Errore parametri: {e}")
            self.canvas.draw_idle(); return

        # --- styling e contenimento ---
        ax.set_facecolor("#fcfcfd")
        for s in ("top", "right"): ax.spines[s].set_visible(False)
        for s in ("left", "bottom"): ax.spines[s].set_color("#e5e7eb")
        ax.grid(True, which="major", alpha=0.28, linestyle="--", linewidth=0.8)
        ax.margins(x=0.02, y=0.10)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: self._fmt_eur(x, 0)))
        ax.tick_params(axis="both", labelsize=10)

        # serie principale
        area_color = "#60a5fa"
        ax.fill_between(df.index, df["contrib"].values, step="pre", alpha=0.12, color=area_color)
        line_val, = ax.plot(df.index, df["value"].values, linewidth=2.2, label="Valore portafoglio")

        # salva serie per hover
        self._xline = mdates.date2num(df.index.to_pydatetime())
        self._yline = df["value"].values.astype(float)

        # Headroom extra
        ymax = float(df["value"].max())
        ymin = float(df["value"].min())
        ax.set_ylim(ymin * 0.98 if ymin > 0 else ymin - abs(ymax)*0.02, ymax * 1.18)

        # --- pallini + etichette evento ---
        self._scatter = None
        self._annot = None
        self._annot_ax = ax
        self._ev_points_xy = []

        if self._event_points:
            ev_map: Dict[pd.Timestamp, List[str]] = {}
            for d, name in self._event_points:
                ts = pd.Timestamp(d)
                ev_map.setdefault(ts, []).append(name.strip())

            ev_idx = pd.to_datetime(sorted(ev_map.keys()))
            aligned = df.reindex(df.index.union(ev_idx)).ffill().loc[ev_idx]

            # usa davvero i TITOLI passati; se vuoto -> "(senza titolo)"
            titles = ["; ".join([t for t in ev_map[ts] if t] or ["(senza titolo)"]) for ts in ev_idx]
            self._ev_points_xy = list(zip(aligned.index.to_pydatetime(), aligned["value"].values, titles))

            self._scatter = ax.scatter(
                aligned.index, aligned["value"].values,
                s=56, zorder=4,
                edgecolor="#0f172a", linewidths=0.7,
                facecolor=line_val.get_color(),
                label="_nolegend_"
            )
            # etichette piccole e compatte
            for (dt, val, title) in self._ev_points_xy:
                ax.annotate(
                    title, xy=(mdates.date2num(dt), val),
                    xytext=(0, 8), textcoords="offset points",
                    fontsize=8, color="#334155",
                    ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85),
                    clip_on=True
                )

        # tooltip/marker condivisi (per linea e per pallini)
        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
            fontsize=9
        )
        self._annot.set_visible(False)
        self._line_marker, = ax.plot([], [], marker="o", markersize=5, color=line_val.get_color(), zorder=5)

        ax.set_ylabel("Valore (€)")
        ax.set_xlabel("Tempo")
        ax.legend(frameon=False, loc="upper left", fontsize=10)
        self.fig.tight_layout()
        self.canvas.draw_idle()

        self.status.setText(
            f"Start: {start_d.isoformat()} | Tasso annuo: {p.annual_rate*100:.2f}% | "
            f"Gestione: {p.mgmt_fee_annual*100:.2f}% | Overnight: {p.overnight_daily*100:.4f}%/g | "
            f"Giorno versamento: {p.contribution_day}"
        )

    def _on_hover(self, event):
        """Tooltip sugli eventi (se sopra un pallino) ALTRIMENTI nearest‐point sulla linea."""
        if self._annot_ax is None:
            return
        if event.inaxes is not self._annot_ax:
            if self._annot and self._annot.get_visible():
                self._annot.set_visible(False)
                self._line_marker.set_data([], [])
                self.canvas.draw_idle()
            return

        # 1) Se il mouse è su un pallino evento, mostra titolo + valore
        if self._scatter is not None:
            contains, ind = self._scatter.contains(event)
            if contains and ind.get("ind"):
                i = ind["ind"][0]
                dt, val, title = self._ev_points_xy[i]
                self._annot.xy = (mdates.date2num(dt), float(val))
                self._annot.set_text(f"{title}\n{dt:%Y-%m-%d}  •  {self._fmt_eur(val)}")
                self._annot.set_visible(True)
                self._line_marker.set_data([], [])
                self.canvas.draw_idle()
                return

        # 2) Altrimenti, tooltip sul punto della LINEA più vicino all'x del mouse
        if self._xline is None or self._yline is None or event.xdata is None:
            if self._annot.get_visible():
                self._annot.set_visible(False)
                self._line_marker.set_data([], [])
                self.canvas.draw_idle()
            return

        x = float(event.xdata)
        # trova indice più vicino (array ordinato)
        idx = int(np.clip(np.searchsorted(self._xline, x), 1, len(self._xline)-1))
        left = idx - 1
        # sceglie fra left e idx il più vicino
        if abs(self._xline[idx] - x) < abs(x - self._xline[left]):
            nearest = idx
        else:
            nearest = left

        dt_num = self._xline[nearest]
        val = float(self._yline[nearest])
        self._annot.xy = (dt_num, val)
        self._annot.set_text(f"{mdates.num2date(dt_num):%Y-%m-%d}\n{self._fmt_eur(val)}")
        self._annot.set_visible(True)
        # marker che segue il mouse sulla linea
        self._line_marker.set_data([dt_num], [val])
        self.canvas.draw_idle()
