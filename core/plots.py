# core/plots.py
from typing import List
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from .models import Event

def build_timeline_figure(events: List[Event], person: str) -> go.Figure:
    """
    Timeline 1D su y=0: linea di base + marker + etichette sopra i punti.
    Tema chiaro esplicito e altezza fissa per evitare 'plot invisibile'.
    """
    fig = go.Figure()

    # Tema chiaro + dimensioni
    fig.update_layout(
        title=f"Eventi di {person}",
        xaxis_title="", yaxis_title="",
        margin=dict(l=20, r=20, t=60, b=20),
        hovermode="x unified",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font=dict(color="#111111"),
        height=520,  # altezza fissa lato Plotly
    )

    if not events:
        # Asse Y nascosto e messaggio in hover
        fig.update_yaxes(visible=False, showticklabels=False)
        return fig

    # DataFrame ordinato
    df = pd.DataFrame([
        {
            "dt": e.dt,
            "Titolo": e.titolo,
            "Categoria": e.categoria,
        }
        for e in sorted(events, key=lambda x: x.dt)
    ])

    # Linea di base (y=0)
    y0 = [0] * len(df)
    fig.add_trace(
        go.Scatter(
            x=df["dt"],
            y=y0,
            mode="lines",
            line=dict(width=2, color="#A0A0A0"),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    # Marker + etichette
    fig.add_trace(
        go.Scatter(
            x=df["dt"],
            y=y0,
            mode="markers+text",
            text=df["Titolo"],
            textposition="top center",
            marker=dict(size=12),
            customdata=df[["Categoria"]],
            hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>%{x|%Y-%m-%d}<extra></extra>",
            showlegend=False,
        )
    )

    # Asse Y nascosto
    fig.update_yaxes(visible=False, showticklabels=False)

    # Tick solo sulle date evento
    ticks = sorted(df["dt"].unique())
    if len(ticks) > 0:
        fig.update_xaxes(tickvals=ticks)

    return fig


def fig_to_html(fig: go.Figure, include_plotlyjs: bool = True) -> str:
    """
    Converte la figura in HTML stand-alone da caricare in QWebEngineView.
    - Disattiviamo il rendering "responsive" di Plotly: in QWebEngineView può
      produrre un div con height: 100% e quindi altezza 0 se il contenitore non
      ha un'altezza esplicita, generando una pagina bianca.
    - Forziamo un'altezza di default lato HTML per garantire visibilità.
    """
    inner = fig.to_html(
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        config={"responsive": False},
        default_height="520px",
        default_width="100%",
    )
    # Wrapper con altezza esplicita per evitare container a 0px
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'></head>"
        "<body style='background:#ffffff; color:#111111;'>"
        "<div style='height:540px;'>" + inner + "</div>"
        "</body></html>"
    )
