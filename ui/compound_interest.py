# ui/compound_interest.py
from __future__ import annotations

from typing import Iterable, Dict, Optional, Tuple, List, Any
from datetime import datetime, date

import numpy as np
import pandas as pd
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import FuncFormatter

from PyQt6.QtCore import Qt, QEvent, QDate
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSizePolicy, QScrollArea,
    QFormLayout, QDoubleSpinBox, QSpinBox, QHBoxLayout, QPushButton, QDateEdit
)

from core.compounding import simulate_compound, CompoundParams


class CompoundInterestWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(820)  # più grande degli altri widget

        self._start_dt: Optional[datetime] = None
        self._event_points: List[Tuple[date, str]] = []  # (data, titolo)
        self._suppress_start_signal = False

        # ---- Titolo
        self.title = QLabel("Calcolatore interesse composto")
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

        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setEnabled(False)
        self.start_date_edit.setToolTip("Scegli la data da cui far partire la simulazione")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(12); form.setVerticalSpacing(6)
        form.addRow("Data di partenza", self.start_date_edit)
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
        self.start_date_edit.dateChanged.connect(self._on_start_date_changed)

        # Hover state
        self._scatter = None                 # punti evento (matplotlib PathCollection)
        self._hover_cid = self.canvas.mpl_connect("motion_notify_event", self._on_hover)

        self._series_data: Dict[str, Dict] = {}
        self._series_by_axis: Dict = {}
        self._markers: Dict[str, Any] = {}
        self._annots: Dict[str, Any] = {}
        self._value_ax = None
        self._event_annot_key: Optional[str] = None

        self._ev_points_xy: List[Tuple[datetime, float, str]] = []  # (dt, value, title)

    # ---------- Public API ----------
    def set_start_date(self, dt: Optional[datetime]) -> None:
        self._start_dt = dt
        self._sync_start_date_edit()
        self.recompute()

    def set_event_points(self, points: Iterable[Tuple[datetime, str]]) -> None:
        # salva (data, titolo) come date pure e ordina
        self._event_points = sorted(
            [(p[0].date() if isinstance(p[0], datetime) else p[0], str(p[1])) for p in points]
        )
        self._sync_start_date_edit()
        self.recompute()

    # retrocompatibilità
    def set_event_dates(self, dates: Iterable[datetime]) -> None:
        self.set_event_points([(d, "") for d in dates])

    # ---------- Interni ----------
    def _cfg_money(self, sp: QDoubleSpinBox, value: float, suffix: str, minv: float, maxv: float, step: float):
        sp.setRange(minv, maxv); sp.setDecimals(2); sp.setValue(value); sp.setSuffix(suffix); sp.setSingleStep(step)

    def _on_start_date_changed(self, qdate: QDate) -> None:
        if self._suppress_start_signal:
            return
        if not qdate.isValid():
            return
        self._start_dt = datetime.combine(qdate.toPyDate(), datetime.min.time())
        self.recompute()

    def _sync_start_date_edit(self) -> None:
        self._suppress_start_signal = True
        try:
            if not self._event_points:
                if self._start_dt is not None:
                    qd = QDate(self._start_dt.year, self._start_dt.month, self._start_dt.day)
                    self.start_date_edit.setDate(qd)
                else:
                    self.start_date_edit.setDate(QDate.currentDate())
                self.start_date_edit.setEnabled(False)
                return

            dates = [d for d, _ in self._event_points]
            min_d = min(dates)
            max_d = max(dates)

            qmin = QDate(min_d.year, min_d.month, min_d.day)
            qmax = QDate(max_d.year, max_d.month, max_d.day)
            self.start_date_edit.setMinimumDate(qmin)
            self.start_date_edit.setMaximumDate(qmax)

            if self._start_dt is None:
                target_date = min_d
            else:
                current_date = self._start_dt.date()
                if current_date < min_d:
                    target_date = min_d
                elif current_date > max_d:
                    target_date = max_d
                else:
                    target_date = current_date

            self._start_dt = datetime.combine(target_date, datetime.min.time())
            self.start_date_edit.setDate(QDate(self._start_dt.year, self._start_dt.month, self._start_dt.day))
            self.start_date_edit.setEnabled(True)
        finally:
            self._suppress_start_signal = False

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
        self._series_data.clear()
        self._series_by_axis.clear()
        self._markers.clear()
        self._annots.clear()
        self._scatter = None
        self._value_ax = None
        self._event_annot_key = None

        if self._start_dt is None:
            if self._event_points:
                self.status.setText("Scegli una data di partenza per avviare la simulazione.")
            else:
                self.status.setText("Seleziona una persona con almeno un evento per generare la simulazione.")
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

        ax = self.fig.add_subplot(111)

        def _style_axis(axis):
            axis.set_facecolor("#fcfcfd")
            for side in ("top", "right"):
                axis.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                axis.spines[side].set_color("#e5e7eb")
            axis.grid(True, which="major", alpha=0.28, linestyle="--", linewidth=0.8)
            axis.tick_params(axis="both", labelsize=10)
            axis.yaxis.set_major_formatter(FuncFormatter(lambda y, _pos: self._fmt_eur(y, 0)))
            axis.margins(x=0.02)

        _style_axis(ax)

        # --- Valore portafoglio, inflazione e contributi nello stesso grafico ---
        value_color = "#2563eb"
        val_series = df["value"].values.astype(float)
        line_val, = ax.plot(x_dates, val_series, linewidth=2.2, color=value_color, label="Valore portafoglio")

        infl_color = "#f97316"
        infl_series = df["inflation_value"].values.astype(float)
        line_infl, = ax.plot(x_dates, infl_series, linewidth=2.0, linestyle="--", color=infl_color,
                              label="Valore con inflazione")

        area_color = "#60a5fa"
        contrib_vals = df["contrib"].values.astype(float)
        ax.fill_between(x_dates, contrib_vals, step="pre", alpha=0.18, color=area_color)
        line_contrib, = ax.plot(x_dates, contrib_vals, linewidth=1.8, color=area_color,
                                 label="Contributi cumulati")

        ymax = float(np.nanmax([
            np.nanmax(val_series),
            np.nanmax(infl_series),
            np.nanmax(contrib_vals),
        ]))
        ymin = float(np.nanmin([
            np.nanmin(val_series),
            np.nanmin(infl_series),
            np.nanmin(contrib_vals),
        ]))
        if not np.isfinite(ymin):
            ymin = 0.0
        if not np.isfinite(ymax):
            ymax = 1.0
        span = ymax - ymin if ymax != ymin else max(abs(ymax), 1.0)
        ymin_adj = ymin - span * 0.04
        ymax_adj = ymax + span * 0.18
        ax.set_ylim(ymin_adj, ymax_adj)
        ax.set_ylabel("Valore (€)")
        ax.set_xlabel("Tempo")
        ax.legend(frameon=False, loc="upper left", fontsize=10)

        def _register_series(key: str, line, series_values: np.ndarray, label: str):
            marker_color = line.get_color()
            annot = ax.annotate(
                "", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cbd5e1", lw=0.8, alpha=0.97),
                fontsize=9
            )
            annot.set_visible(False)
            marker, = ax.plot([], [], marker="o", markersize=5, color=marker_color, zorder=5)
            self._series_data[key] = {
                "axis": ax,
                "x": x_num,
                "y": series_values,
                "label": label,
                "fmt": self._fmt_eur,
            }
            self._series_by_axis.setdefault(ax, []).append(key)
            self._annots[key] = annot
            self._markers[key] = marker

        _register_series("value", line_val, val_series, "Valore portafoglio")
        _register_series("inflation", line_infl, infl_series, "Valore con inflazione")
        _register_series("contrib", line_contrib, contrib_vals, "Contributi cumulati")

        self._value_ax = ax
        self._event_annot_key = "value"

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

            self._scatter = ax.scatter(
                aligned.index, aligned["value"].values,
                s=56, zorder=4,
                edgecolor="#0f172a", linewidths=0.7,
                facecolor=line_val.get_color(),
                label="_nolegend_",
            )
            for (dt, val, title) in self._ev_points_xy:
                dt_num = mdates.date2num(dt)
                x_left, x_right = ax.get_xlim()
                x_range = max(x_right - x_left, 1e-6)
                if dt_num - x_left < 0.05 * x_range:
                    ha = "left"; dx = 6
                elif x_right - dt_num < 0.05 * x_range:
                    ha = "right"; dx = -6
                else:
                    ha = "center"; dx = 0
                ax.annotate(
                    title, xy=(dt_num, val),
                    xytext=(dx, 8), textcoords="offset points",
                    fontsize=8, color="#334155",
                    ha=ha, va="bottom",
                    bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85),
                    clip_on=False
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
            for annot in self._annots.values():
                if annot.get_visible():
                    annot.set_visible(False)
                    updated = True
            for marker in self._markers.values():
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
                annot = self._annots.get(self._event_annot_key)
                if annot is not None:
                    annot.xy = (dt_num, float(val))
                    annot.set_text(f"{title}\n{dt:%Y-%m-%d}  •  {self._fmt_eur(val)}")
                    annot.set_visible(True)
                for key, marker in self._markers.items():
                    marker.set_data([], [])
                    if key != self._event_annot_key:
                        other_annot = self._annots.get(key)
                        if other_annot and other_annot.get_visible():
                            other_annot.set_visible(False)
                self.canvas.draw_idle()
                return

        keys = self._series_by_axis.get(ax, [])
        if not keys or event.xdata is None:
            for key in keys:
                annot = self._annots.get(key)
                marker = self._markers.get(key)
                if annot and annot.get_visible():
                    annot.set_visible(False)
                if marker:
                    marker.set_data([], [])
            self.canvas.draw_idle()
            return

        best = None
        for key in keys:
            data = self._series_data.get(key)
            if data is None:
                continue
            x_arr = data["x"]
            x = float(event.xdata)
            if len(x_arr) == 0:
                continue
            if len(x_arr) == 1:
                nearest = 0
            else:
                idx = int(np.clip(np.searchsorted(x_arr, x), 1, len(x_arr) - 1))
                left = idx - 1
                nearest = idx if abs(x_arr[idx] - x) < abs(x - x_arr[left]) else left
            dt_num = x_arr[nearest]
            val = float(data["y"][nearest])
            diff = abs(val - float(event.ydata)) if event.ydata is not None else 0.0
            candidate = (diff, key, dt_num, val)
            if best is None or diff < best[0]:
                best = candidate
            if event.ydata is None:
                break

        if best is None:
            for key in keys:
                annot = self._annots.get(key)
                marker = self._markers.get(key)
                if annot and annot.get_visible():
                    annot.set_visible(False)
                if marker:
                    marker.set_data([], [])
            self.canvas.draw_idle()
            return

        _, sel_key, dt_num, val = best
        data = self._series_data[sel_key]
        annot = self._annots.get(sel_key)
        marker = self._markers.get(sel_key)
        if annot is None or marker is None:
            return

        annot.xy = (dt_num, val)
        annot.set_text(
            f"{data['label']}\n{mdates.num2date(dt_num):%Y-%m-%d}  •  {data['fmt'](val)}"
        )
        annot.set_visible(True)
        marker.set_data([dt_num], [val])

        for other_key, other_marker in self._markers.items():
            if other_key == sel_key:
                continue
            other_marker.set_data([], [])
            other_annot = self._annots.get(other_key)
            if other_annot and other_annot.get_visible():
                other_annot.set_visible(False)

        self.canvas.draw_idle()
