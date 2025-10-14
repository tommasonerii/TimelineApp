# ui/compound_interest.py
from __future__ import annotations

from typing import Iterable, Dict, Optional, Tuple, List
from datetime import datetime, date

import numpy as np
import pandas as pd
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import FuncFormatter

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea,
    QFormLayout, QDoubleSpinBox, QSpinBox, QHBoxLayout, QPushButton
)

from core.compounding import simulate_compound, CompoundParams


class CompoundInterestWidget(QWidget):
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

        self.spin_inflation = QDoubleSpinBox()
        self.spin_inflation.setRange(-50.0, 100.0); self.spin_inflation.setDecimals(2)
        self.spin_inflation.setValue(2.00); self.spin_inflation.setSuffix(" % annuo (inflazione)")
        self.spin_inflation.setSingleStep(0.10)

        self.spin_years = QSpinBox()
        self.spin_years.setRange(1, 100); self.spin_years.setValue(20); self.spin_years.setSuffix(" anni")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(12); form.setVerticalSpacing(6)
        form.addRow("Capitale iniziale", self.spin_initial)
        form.addRow("Versamento mensile", self.spin_monthly)
        form.addRow("Tasso annuo", self.spin_rate)
        form.addRow("Commissione gestione", self.spin_mgmt)
        form.addRow("Inflazione attesa", self.spin_inflation)
        form.addRow("Orizzonte", self.spin_years)

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
                  self.spin_mgmt, self.spin_inflation, self.spin_years):
            w.valueChanged.connect(self.recompute)

        # Hover state
        self._scatter = None                 # punti evento (matplotlib PathCollection)
        self._annot = None                   # tooltip per asse corrente
        self._annot_ax = None
        self._hover_cid = self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        # dati linea per hover (x numeri matplotlib, y float)
        self._xline = None
        self._yline = None
        self._line_marker = None
        self._line_markers: Dict = {}
        self._axes_data: Dict = {}
        self._annot_by_ax: Dict = {}
        self._value_ax = None

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
            inflation_rate=float(self.spin_inflation.value())/100.0,
            years=int(self.spin_years.value()),
        )

    def recompute(self) -> None:
        self.fig.clear()
        self._axes_data.clear()
        self._line_markers.clear()
        self._annot_by_ax.clear()
        self._scatter = None
        self._annot = None
        self._annot_ax = None
        self._value_ax = None

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

        if df.empty:
            self.status.setText("Nessun dato generato per questi parametri.")
            self.canvas.draw_idle(); return

        x_dates = df.index
        x_num = mdates.date2num(x_dates.to_pydatetime())

        ax_val, ax_infl, ax_contrib = self.fig.subplots(
            3, 1, sharex=True,
            gridspec_kw={"height_ratios": [2.2, 1.4, 1.1], "hspace": 0.05}
        )

        def _style_axis(ax):
            ax.set_facecolor("#fcfcfd")
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color("#e5e7eb")
            ax.grid(True, which="major", alpha=0.28, linestyle="--", linewidth=0.8)
            ax.tick_params(axis="both", labelsize=10)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _pos: self._fmt_eur(y, 0)))
            ax.margins(x=0.02)

        for axis in (ax_val, ax_infl, ax_contrib):
            _style_axis(axis)

        # --- Valore portafoglio (nominale) + Valore reale (deflazionato) ---
        value_color = "#2563eb"
        real_color = "#059669"
        val_series = df["value"].values.astype(float)
        real_series = df["real_value"].values.astype(float)

        line_val, = ax_val.plot(x_dates, val_series, linewidth=2.2, color=value_color, label="Valore portafoglio")
        line_real, = ax_val.plot(x_dates, real_series, linewidth=1.8, linestyle="--", color=real_color,
                                 label="Valore reale (netto inflazione)")
        ymax = float(max(val_series.max(), real_series.max()))
        ymin = float(min(val_series.min(), real_series.min()))
        ax_val.set_ylim(ymin * 0.98 if ymin > 0 else ymin - abs(ymax) * 0.02, ymax * 1.18)
        ax_val.set_ylabel("Valore (€)")
        ax_val.legend(frameon=False, loc="upper left", fontsize=10)

        # --- Inflazione (crescita solo al tasso inflattivo) ---
        infl_color = "#f97316"
        infl_series = df["inflation_value"].values.astype(float)
        line_infl, = ax_infl.plot(x_dates, infl_series, linewidth=2.0, color=infl_color, label="Valore con inflazione")
        infl_max = max(float(infl_series.max()), 1.0)
        ax_infl.set_ylim(0, infl_max * 1.15)
        ax_infl.set_ylabel("Inflazione (€)")
        ax_infl.legend(frameon=False, loc="upper left", fontsize=10)

        # --- Contributi cumulati ---
        area_color = "#60a5fa"
        contrib_vals = df["contrib"].values.astype(float)
        ax_contrib.fill_between(x_dates, contrib_vals, step="pre", alpha=0.16, color=area_color)
        line_contrib, = ax_contrib.plot(x_dates, contrib_vals, linewidth=1.8, color=area_color, label="Contributi cumulati")
        contrib_max = max(float(contrib_vals.max()), 1.0)
        ax_contrib.set_ylim(0, contrib_max * 1.18)
        ax_contrib.set_ylabel("Contributi (€)")
        ax_contrib.set_xlabel("Tempo")

        self._axes_data = {
            ax_val: {
                "x": x_num,
                "y": val_series,
                "label": "Valore portafoglio",
                "fmt": self._fmt_eur,
            },
            ax_infl: {
                "x": x_num,
                "y": infl_series,
                "label": "Valore con inflazione",
                "fmt": self._fmt_eur,
            },
            ax_contrib: {
                "x": x_num,
                "y": contrib_vals,
                "label": "Contributi cumulati",
                "fmt": self._fmt_eur,
            },
        }
        # Aggiunge anche il tracciato "reale" al dizionario dell'asse principale per hover separato
        self._axes_data[(ax_val, "real")] = {
            "x": x_num,
            "y": real_series,
            "label": "Valore reale (netto inflazione)",
            "fmt": self._fmt_eur,
            "color": real_color,
        }

        # Annotazioni e marker per ciascun asse linea principale
        for axis, line in ((ax_val, line_val), (ax_infl, line_infl), (ax_contrib, line_contrib)):
            annot = axis.annotate(
                "", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            annot.set_visible(False)
            self._annot_by_ax[axis] = annot
            marker, = axis.plot([], [], marker="o", markersize=5, color=line.get_color(), zorder=5)
            self._line_markers[axis] = marker

        # Marker/annot per la linea "reale" (secondo tracciato sullo stesso asse)
        annot_real = ax_val.annotate(
            "", xy=(0, 0), xytext=(10, -16), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
            fontsize=9
        ); annot_real.set_visible(False)
        self._annot_by_ax[(ax_val, "real")] = annot_real
        marker_real, = ax_val.plot([], [], marker="o", markersize=5, color=real_color, zorder=5)
        self._line_markers[(ax_val, "real")] = marker_real

        self._value_ax = ax_val
        self._annot = self._annot_by_ax.get(ax_val)
        self._annot_ax = ax_val
        self._xline = x_num
        self._yline = val_series
        self._line_marker = self._line_markers.get(ax_val)

        # --- pallini + etichette evento sul grafico principale ---
        self._ev_points_xy = []
        if self._event_points:
            ev_map: Dict[pd.Timestamp, List[str]] = {}
            for d, name in self._event_points:
                ts = pd.Timestamp(d)
                ev_map.setdefault(ts, []).append(name.strip())

            ev_idx = pd.to_datetime(sorted(ev_map.keys()))
            aligned = df.reindex(df.index.union(ev_idx)).ffill().loc[ev_idx]
            titles = ["; ".join([t for t in ev_map[ts] if t] or ["(senza titolo)"]) for ts in ev_idx]
            self._ev_points_xy = list(zip(aligned.index.to_pydatetime(), aligned["value"].values, titles))

            self._scatter = ax_val.scatter(
                aligned.index, aligned["value"].values,
                s=56, zorder=4,
                edgecolor="#0f172a", linewidths=0.7,
                facecolor=line_val.get_color(),
                label="_nolegend_",
            )
            for (dt, val, title) in self._ev_points_xy:
                ax_val.annotate(
                    title, xy=(mdates.date2num(dt), val),
                    xytext=(0, 8), textcoords="offset points",
                    fontsize=8, color="#334155",
                    ha="center", va="bottom",
                    bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85),
                    clip_on=True
                )

        self.canvas.draw_idle()

        self.status.setText(
            f"Start: {start_d.isoformat()} | Tasso annuo: {p.annual_rate*100:.2f}% | "
            f"Gestione: {p.mgmt_fee_annual*100:.2f}% | Inflazione: {p.inflation_rate*100:.2f}% | "
            "Versamento: ogni 1° del mese"
        )

    def _on_hover(self, event):
        """Tooltip sugli eventi (se sopra un pallino) oppure sulle linee dei tre grafici."""
        # Se fuori dagli assi, spegni tutto
        if event.inaxes is None:
            updated = False
            for annot in self._annot_by_ax.values():
                if annot.get_visible():
                    annot.set_visible(False)
                    updated = True
            for marker in self._line_markers.values():
                marker.set_data([], [])
            if updated:
                self.canvas.draw_idle()
            return

        ax = event.inaxes

        # 1) Se il mouse è su un pallino evento nel grafico principale
        if ax is self._value_ax and self._scatter is not None:
            contains, ind = self._scatter.contains(event)
            if contains and ind.get("ind"):
                i = ind["ind"][0]
                dt, val, title = self._ev_points_xy[i]
                dt_num = mdates.date2num(dt)
                annot = self._annot_by_ax.get(self._value_ax)
                if annot is not None:
                    annot.xy = (dt_num, float(val))
                    annot.set_text(f"{title}\n{dt:%Y-%m-%d}  •  {self._fmt_eur(val)}")
                    annot.set_visible(True)
                marker = self._line_markers.get(self._value_ax)
                if marker is not None:
                    marker.set_data([], [])
                # Nascondi marker e annotazioni degli altri assi
                for other_ax, other_marker in self._line_markers.items():
                    if other_ax not in (self._value_ax, (self._value_ax, "real")):
                        other_marker.set_data([], [])
                        other_annot = self._annot_by_ax.get(other_ax)
                        if other_annot and other_annot.get_visible():
                            other_annot.set_visible(False)
                # spegni anche il marker/annot della serie "reale"
                mr = self._line_markers.get((self._value_ax, "real"))
                if mr: mr.set_data([], [])
                ar = self._annot_by_ax.get((self._value_ax, "real"))
                if ar and ar.get_visible(): ar.set_visible(False)
                self.canvas.draw_idle()
                return

        # 2) Tooltip sulla linea più vicina nell'asse corrente (inclusa la serie "reale" se asse principale)
        # Scegli se stiamo hoverando il tracciato nominale o quello reale
        # Se asse principale, prova prima reale (per evitare overlap), poi nominale
        data_candidates = []
        if ax is self._value_ax:
            data_candidates.append((ax, "real"))
            data_candidates.append(ax)
        else:
            data_candidates.append(ax)

        handled = False
        for key in data_candidates:
            data = self._axes_data.get(key)
            if data is None or event.xdata is None:
                continue
            x = float(event.xdata)
            x_arr = data["x"]
            if len(x_arr) == 0:
                continue
            idx = int(np.clip(np.searchsorted(x_arr, x), 1, len(x_arr) - 1))
            left = idx - 1
            nearest = idx if abs(x_arr[idx] - x) < abs(x - x_arr[left]) else left
            dt_num = x_arr[nearest]
            val = float(data["y"][nearest])

            annot = self._annot_by_ax.get(key)
            marker = self._line_markers.get(key)
            if annot is None or marker is None:
                continue

            label = data["label"]
            fmt = data["fmt"]
            annot.xy = (dt_num, val)
            annot.set_text(f"{label}\n{mdates.num2date(dt_num):%Y-%m-%d}  •  {fmt(val)}")
            annot.set_visible(True)
            marker.set_data([dt_num], [val])

            # spegni gli altri marker/annot
            for other_key, other_marker in self._line_markers.items():
                if other_key == key:
                    continue
                other_marker.set_data([], [])
                other_annot = self._annot_by_ax.get(other_key)
                if other_annot and other_annot.get_visible():
                    other_annot.set_visible(False)

            self.canvas.draw_idle()
            handled = True
            break

        if not handled:
            # se nulla gestito, spegni annot/marker di quell'asse
            for key in data_candidates:
                annot = self._annot_by_ax.get(key)
                marker = self._line_markers.get(key)
                if annot and annot.get_visible():
                    annot.set_visible(False)
                if marker:
                    marker.set_data([], [])
            self.canvas.draw_idle()
