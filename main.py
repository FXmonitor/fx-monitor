import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime

app = FastAPI(title="FX Market Crystal Pro")

accounts_data = {}
history_data = {}

@app.post("/api/update")
async def update_account(request: Request):
    try:
        data = await request.json()
        login = data.get("login")
        now_str = datetime.now().strftime("%H:%M")
        
        accounts_data[login] = {
            "company": data.get("company"),
            "balance": data.get("balance"),
            "equity": data.get("equity"),
            "margin": data.get("margin", 0.0),
            "free_margin": data.get("free_margin", 0.0),
            "p_today": data.get("p_today", 0.0),
            "p_yesterday": data.get("p_yesterday", 0.0),
            "p_week": data.get("p_week", 0.0),
            "p_month": data.get("p_month", 0.0),
            "currency": data.get("currency"),
            "pairs": data.get("pairs", {})
        }
        
        if login not in history_data:
            history_data[login] = []
        history_data[login].append({"time": now_str, "equity": data.get("equity")})
        if len(history_data[login]) > 30:
            history_data[login].pop(0)
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error"}

@app.get("/", response_class=HTMLResponse)
def home():
    if not accounts_data:
        return """
        <html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'></head>
        <body style='background:#000;color:#fff;text-align:center;padding-top:100px;font-family:sans-serif;'>
            <h2>💎 CRYSTAL CLASSIC PLUS</h2><p style='color:#71717a;'>Синхронизация расширенных метрик портфеля...</p>
        </body></html>
        """

    html_content = """
    <html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'>
    <title>Crystal Classic Plus</title>
    <script src="https://jsdelivr.net"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 12px; margin: 0; }
        .card-list { display: flex; flex-direction: column; gap: 14px; margin-top: 10px; }
        .account-card { background: #09090b; border-radius: 16px; padding: 16px; border: 1px solid #1c1c1f; position: relative; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #1c1c1f; padding-bottom: 8px; }
        .login-title { font-size: 15px; font-weight: 800; color: #3b82f6; }
        .broker-title { font-size: 11px; color: #71717a; }
        .main-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 15px; }
        .metric-box { display: flex; flex-direction: column; }
        .label { font-size: 9px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px; }
        .val-big { font-size: 24px; font-weight: 900; color: #ffffff; margin-top: 2px; }
        .margin-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; background: #0c0c0e; padding: 10px; border-radius: 8px; border: 1px solid #1c1c1f; margin-bottom: 15px; }
        .margin-val { font-size: 13px; font-weight: 700; color: #e4e4e7; margin-top: 1px; }
        .profit-timeline { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 15px; }
        .profit-tab { background: #141417; border: 1px solid #27272a; border-radius: 6px; padding: 6px; text-align: center; }
        .profit-val { font-size: 11px; font-weight: 800; margin-top: 2px; }
        .tiles-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-top: 12px; border-top: 1px solid #1c1c1f; padding-top: 12px; }
        .tile { border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; justify-content: space-between; min-height: 52px; border: 1px solid rgba(255,255,255,0.02); }
        .tile-name { font-size: 11px; font-weight: 800; color: #fff; }
        .tile-lots { font-size: 9px; color: #a1a1aa; margin: 2px 0; }
        .tile-profit { font-size: 11px; font-weight: 700; text-align: right; }
        .chart-box { height: 110px; margin-top: 12px; border-top: 1px solid #1c1c1f; padding-top: 12px; }
    </style></head>
    <body>
        <div style="font-size:18px; font-weight:900; margin-bottom:15px; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;">Crystal Classic Plus</div>
        <div class="card-list">
    """
        for login, info in accounts_data.items():
            drawdown = info['balance'] - info['equity']
            dd_percent = (drawdown / info['balance']) * 100 if info['balance'] > 0 else 0
            
            if dd_percent <= 2:
                status_color = "#10b981"
                card_border = "1px solid #153a26"
            elif dd_percent <= 10:
                status_color = "#f59e0b"
                card_border = "1px solid #4d330c"
            else:
                status_color = "#ef4444"
                card_border = "1px solid #5c1919"
                
            pts = history_data.get(login, [])
            lbls = [p["time"] for p in pts]
            vals = [p["equity"] for p in pts]

            def get_p_color(val): return "#10b981" if val > 0.01 else ("#ef4444" if val < -0.01 else "#71717a")
            def get_p_sign(val): return f"+{val:.1f}" if val > 0.01 else f"{val:.1f}"

            html_content += f"""
                <div class="account-card" style="border: {card_border}; border-left: 5px solid {status_color};">
                    <div class="card-header">
                        <span class="login-title">Crystal Classic Plus</span>
                        <span class="broker-title">ID: {login} | {info['company']}</span>
                    </div>
                    
                    <div class="main-metrics">
                        <div class="metric-box">
                            <span class="label">Баланс аккаунта</span>
                            <span class="val-big">${info['balance']:,}</span>
                        </div>
                        <div class="metric-box" style="text-align:right;">
                            <span class="label">Текущая Просадка</span>
                            <span class="val-big" style="color:{status_color}">{dd_percent:.2f}%</span>
                        </div>
                    </div>

                    <div class="margin-grid">
                        <div class="metric-box">
                            <span class="label">В работе (Залог/Маржа)</span>
                            <span class="margin-val">${info['margin']:,}</span>
                        </div>
                        <div class="metric-box" style="text-align:right;">
                            <span class="label">Свободно средств</span>
                            <span class="margin-val" style="color:#3b82f6">${info['free_margin']:,}</span>
                        </div>
                    </div>

                    <span class="label" style="display:block; margin-bottom:5px;">Финансовый отчет робота</span>
                    <div class="profit-timeline">
                        <div class="profit-tab">
                            <span class="label" style="font-size:7px;">Сегодня</span>
                            <div class="profit-val" style="color:{get_p_color(info['p_today'])}">{get_p_sign(info['p_today'])}</div>
                        </div>
                        <div class="profit-tab">
                            <span class="label" style="font-size:7px;">Вчера</span>
                            <div class="profit-val" style="color:{get_p_color(info['p_yesterday'])}">{get_p_sign(info['p_yesterday'])}</div>
                        </div>
                        <div class="profit-tab">
                            <span class="label" style="font-size:7px;">Неделя</span>
                            <div class="profit-val" style="color:{get_p_color(info['p_week'])}">{get_p_sign(info['p_week'])}</div>
                        </div>
                        <div class="profit-tab">
                            <span class="label" style="font-size:7px;">Месяц</span>
                            <div class="profit-val" style="color:{get_p_color(info['p_month'])}">{get_p_sign(info['p_month'])}</div>
                        </div>
                    </div>

                    <span class="label">Динамика Equity (Средства) за день</span>
                    <div class="chart-box">
                        <canvas id="chart_{login}"></canvas>
                    </div>
                    <script>
                        new Chart(document.getElementById('chart_{login}'), {{
                            type: 'line',
                            data: {{
                                labels: {repr(lbls)},
                                datasets: [{{
                                    data: {repr(vals)},
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
                    </script>

                    <div style="margin-top:12px;" class="label">Плотность набранных позиций</div>
                    <div class="tiles-grid">
            """
            
            pairs = info.get("pairs", {})
            for pair, volumes in pairs.items():
                b_lot = volumes.get('buy', 0.0)
                s_lot = volumes.get('sell', 0.0)
                prof = volumes.get('profit', 0.0)
                
                if b_lot > 0 and s_lot > 0:
                    t_bg = "linear-gradient(135deg, #172554, #0f172a)"
                    t_border = "1px solid #3b82f6"
                    lots = f"B:{b_lot:.1f} S:{s_lot:.1f}"
                elif b_lot > 0:
                    t_bg = "linear-gradient(135deg, #022c22, #050b08)"
                    t_border = "1px solid #10b981"
                    lots = f"Buy: {b_lot:.1f}"
                else:
                    t_bg = "linear-gradient(135deg, #450a0a, #0f0505)"
                    t_border = "1px solid #ef4444"
                    lots = f"Sell: {s_lot:.1f}"
                    
                p_color = "#a1a1aa" if abs(prof) < 0.01 else ("#10b981" if prof > 0 else "#ef4444")

                html_content += f"""
                        <div class="tile" style="background: {t_bg}; border: {t_border};">
                            <span class="tile-name">{pair}</span>
                            <span class="tile-lots">{lots}</span>
                            <span class="tile-profit" style="color:{p_color}">${prof:.0f}</span>
                        </div>
                """
                
            html_content += """
                    </div>
                </div>
            """
            
        html_content += """
            </div>
        </body></html>
        """
        return html_content

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
