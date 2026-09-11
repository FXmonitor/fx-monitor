import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime

app = FastAPI()
accounts_data = {}

@app.post("/api/update")
async def update_account(request: Request):
    try:
        data = await request.json()
        login = data.get("login")
        accounts_data[login] = data
        return {"status": "success"}
    except Exception as e:
        return {"status": "error"}

@app.get("/", response_class=HTMLResponse)
def home():
    if not accounts_data:
        return """
        <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'></head>
        <body style='background:#000;color:#aaa;text-align:center;padding-top:100px;font-family:sans-serif;'>
            <h2>💎 CRYSTAL CLASSIC PLUS</h2>
            <p>Ожидание точных долларовых данных от MT5...</p>
        </body></html>
        """
    
    html = """
    <html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'>
    <title>Crystal Classic Plus</title>
    <script src="https://jsdelivr.net"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 12px; margin: 0; }
        .card-list { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
        .account-accordion { background: #09090b; border-radius: 12px; border: 1px solid #1c1c1f; overflow: hidden; }
        .accordion-header { padding: 14px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; background: #0d0d11; }
        .acc-info { display: flex; flex-direction: column; gap: 2px; }
        .acc-title { font-size: 14px; font-weight: 800; color: #fff; }
        .acc-meta { font-size: 11px; color: #71717a; }
        .acc-stat { text-align: right; display: flex; flex-direction: column; gap: 2px; }
        .stat-dd { font-size: 14px; font-weight: 800; }
        .stat-profit { font-size: 11px; font-weight: 600; }
        .accordion-content { display: none; padding: 15px; background: #09090b; border-top: 1px solid #1c1c1f; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
        .label { font-size: 9px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px; }
        .val-big { font-size: 20px; font-weight: 900; color: #ffffff; }
        .chart-box { height: 115px; margin: 12px 0; background: #0c0c0e; border: 1px solid #1c1c1f; border-radius: 8px; padding: 6px; }
        .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 12px; }
        .tile { border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; justify-content: space-between; min-height: 65px; border: 1px solid rgba(255,255,255,0.02); text-align: left; }
        .tile-name { font-size: 12px; font-weight: 800; color: #fff; }
        .tile-lots { font-size: 10px; color: #d4d4d8; margin: 1px 0; }
        .tile-profit { font-size: 10px; font-weight: 700; text-align: right; }
        .tile-percent { font-size: 11px; font-weight: 800; text-align: right; margin-top: 1px; }
        .t-green { background: linear-gradient(135deg, #022c22, #050b08); border-left: 3px solid #10b981; border-top: 1px solid #153a26; }
        .t-yellow { background: linear-gradient(135deg, #4d330c, #0c0802); border-left: 3px solid #f59e0b; border-top: 1px solid #6b4712; }
        .t-red { background: linear-gradient(135deg, #450a0a, #0f0505); border-left: 3px solid #ef4444; border-top: 1px solid #5c1919; }
    </style></head><body>
    <h2 style='font-size:18px; font-weight:900; margin-bottom:12px; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>Crystal Classic Plus (USD)</h2>
    <div class="card-list">
    """
    
    chart_scripts = ""
    for login, info in accounts_data.items():
        raw_balance = float(info.get('balance', 0.0))
        
        # ТОЧНЫЙ ПЕРЕВОД ИЗ ЦЕНТОВ В USD (Баланс, Эквити, Маржа, Свободно)
        usd_balance = raw_balance / 100.0
        usd_equity = float(info.get('equity', 0.0)) / 100.0
        usd_margin = float(info.get('margin', 0.0)) / 100.0
        usd_free_margin = float(info.get('free_margin', 0.0)) / 100.0
        
        drawdown_usd = usd_balance - usd_equity
        dd_percent = (drawdown_usd / usd_balance) * 100 if usd_balance > 0 else 0
        
        p_today = float(info.get('p_today', 0.0)) / 100.0
        p_today_color = "#10b981" if p_today > 0.01 else ("#ef4444" if p_today < -0.01 else "#71717a")
        p_today_text = f"+${p_today:.2f}" if p_today > 0.01 else f"${p_today:.2f}"

        if dd_percent <= 2:     status_color = "#10b981"
        elif dd_percent <= 10:  status_color = "#f59e0b"
        else:                   status_color = "#ef4444"

        html += f"""
        <div class="account-accordion" style="border-left: 4px solid {status_color};">
            <div class="accordion-header" onclick="toggleAccordion({login})">
                <div class="acc-info">
                    <span class="acc-title">Crystal Classic Plus</span>
                    <span class="acc-meta">ID: {login} | {info.get('company','')}</span>
                </div>
                <div class="acc-stat">
                    <span class="stat-dd" style="color:{status_color}">DD: {dd_percent:.2f}%</span>
                    <span class="stat-profit" style="color:{p_today_color}">{p_today_text}</span>
                </div>
            </div>
            
            <div class="accordion-content" id="content_{login}">
                <div class="grid">
                    <div><span class="label">Баланс аккаунта</span><br><b class="val-big">${usd_balance:,.2f}</b></div>
                    <div style="text-align:right;"><span class="label">Чистые средства</span><br><b class="val-big" style="color:#3b82f6;">${usd_equity:,.2f}</b></div>
                </div>
                
                <div style="background:#0c0c0e;padding:8px;border-radius:6px;font-size:11px;display:flex;justify-content:space-between;color:#e4e4e7;border:1px solid #1c1c1f;">
                    <span>В работе: ${usd_margin:,.2f}</span>
                    <span>Свободно: ${usd_free_margin:,.2f}</span>
                </div>

                <div style="margin-top:12px;" class="label">Кривая доходности Equity (Неделя)</div>
                <div class="chart-box"><canvas id="chart_{login}"></canvas></div>
                
                <div style="margin-top:12px;" class="label">Плотность позиций (Светофор пар)</div>
                <div class="tiles">
        """
        
        for pair, v in info.get("pairs", {}).items():
            b_lot = v.get('buy', 0.0)
            s_lot = v.get('sell', 0.0)
            raw_pair_profit = v.get('profit', 0.0)
            usd_pair_profit = raw_pair_profit / 100.0
            pair_dd_percent = abs((raw_pair_profit / raw_balance) * 100) if raw_balance > 0 else 0
            
            if pair_dd_percent <= 2:
                tile_class = "t-green"
                text_color = "#10b981"
            elif pair_dd_percent <= 10:
                tile_class = "t-yellow"
                text_color = "#f59e0b"
            else:
                tile_class = "t-red"
                text_color = "#ef4444"
                
            lots_text = f"B:{b_lot:.2f} S:{s_lot:.2f}" if b_lot > 0 and s_lot > 0 else (f"Buy: {b_lot:.2f}" if b_lot > 0 else f"Sell: {s_lot:.2f}")
            pct_display = f"-{pair_dd_percent:.2f}%" if usd_pair_profit < 0 else (f"+{pair_dd_percent:.2f}%" if usd_pair_profit > 0 else "0.00%")
            prof_display = f"${usd_pair_profit:.2f}" if usd_pair_profit != 0 else "$0.00"

            html += f"""
                    <div class="tile {tile_class}">
                        <span class="tile-name">{pair}</span>
                        <span class="tile-lots">{lots_text}</span>
                        <div>
                            <div class="tile-percent" style="color:{text_color};">{pct_display}</div>
                            <div class="tile-profit" style="color:#71717a;">({prof_display})</div>
                        </div>
                    </div>
            """
        html += f"""
                </div>
            </div>
        </div>
        """
        
        chart_scripts += f"""
        (function() {{
            var login = "{login}";
            var currentEquity = {usd_equity};
            var nowStr = new Date().toLocaleTimeString('ru-RU', {{hour: '2-digit', minute:'2-digit'}});
            var localHist = localStorage.getItem('hist_' + login);
            var historyArr = localHist ? JSON.parse(localHist) : [];
            
            if (historyArr.length === 0 || historyArr[historyArr.length - 1].equity !== currentEquity) {{
                historyArr.push({{ time: nowStr, equity: currentEquity }});
            }}
            if (historyArr.length > 50) historyArr.shift();
            localStorage.setItem('hist_' + login, JSON.stringify(historyArr));
            
            var lbls = historyArr.map(p => p.time);
            var vals = historyArr.map(p => p.equity);
            
            var ctx = document.getElementById('chart_' + login).getContext('2d');
            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: lbls,
                    datasets: [{{
                        data: vals,
                        borderColor: '#3b82f6',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: true,
                        backgroundColor: 'rgba(59, 130, 246, 0.01)',
                        tension: 0.1
                    }}]
                }},
                options: {{
                    responsive: true, maintainAspectRatio: false,
                    plugins: {{ legend: {{ display: false }} }},
                    scales: {{ x:{{ display: false }}, y:{{ grid:{{ color: '#141417' }}, ticks:{{ color: '#4b5563', font:{{size:8}} }} }} }}
                }}
            }});
        }})();
        """
    
    html += f"""
    </div>
    <script>
        function toggleAccordion(login) {{
            var content = document.getElementById('content_' + login);
            if (content.style.display === 'block') {{
                content.style.display = 'none';
            }} else {{
                content.style.display = 'block';
                window.dispatchEvent(new Event('resize'));
            }}
        }}
        {chart_scripts}
    </script>
    </body></html>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
