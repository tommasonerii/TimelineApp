# ui/test_pages.py

def html_test_page() -> str:
    """HTML statico per verificare il rendering della WebEngine."""
    return """
    <!doctype html>
    <html>
      <head><meta charset="utf-8"></head>
      <body style="margin:0;background:#ffffff;color:#111;font-family:Segoe UI, Arial">
        <div style="padding:16px">
          <h2>Test HTML: QWebEngine funziona ✅</h2>
          <p>Se vedi questo testo e il riquadro sotto, il rendering HTML è OK.</p>
          <div style="height:220px;border:2px solid #333;background:#f5f5f5;border-radius:8px;
                      display:flex;align-items:center;justify-content:center;">
            <span style="font-weight:600;">Box 220px di altezza</span>
          </div>
        </div>
      </body>
    </html>
    """

def plotly_cdn_test_page() -> str:
    """Grafico minimale via CDN Plotly per testare JS + canvas."""
    return """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
      </head>
      <body style="margin:0;background:#ffffff;color:#111;font-family:Segoe UI, Arial">
        <div id="plot" style="width:100%;height:520px;"></div>
        <script>
          const data = [{ x:[1,2,3], y:[1,4,9], mode:'lines+markers', name:'demo' }];
          const layout = {
            title:'Test Plotly (CDN)',
            paper_bgcolor:'#ffffff', plot_bgcolor:'#ffffff',
            font:{color:'#111111'}, margin:{l:20,r:20,t:60,b:20}
          };
          Plotly.newPlot('plot', data, layout, {responsive:true, displayModeBar:false});
          window.addEventListener('resize', () => {
            const div = document.getElementById('plot');
            if (window.Plotly && div) Plotly.Plots.resize(div);
          });
        </script>
      </body>
    </html>
    """
