import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from datetime import datetime

app = FastAPI()
accounts_data = {}
history_data = {}  # Хранит точки для недельного графика

@app.post("/api/update")
async def update_account(request: Request):
    try:
        data = await request.json()
        login = data.get("login")
        now_date = datetime.now().strftime("%d.%m %H:%M")
        
        accounts_data[login] = data
        
        # Накапливаем историю для графика за неделю (сохраняем до 50 точек)
        if login not in history_data:
            history_data[login] = []
        
        # Добавляем точку (переводим центы в доллары для графика сразу)
        usd_eq = float(data.get("equity", 0.0)) / 100.0
        
        # Чтобы график не забивался одинаковыми точками, пишем раз в несколько минут
        if not history_data[login] or history_data[login][-1]["equity"] != usd_eq:
            history_data[login].append({"time": now_date, "equity": usd_eq})
            
        if len(history_data[login]) > 50:
            history_data[login].pop(0)
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error"}

@app.get("/", response_class=HTMLResponse)
def home():
    if not accounts_data:
        return "<html><body style='background:#000;color:#aaa;text-align:center;padding-top:100px;font-family:sans-serif;'><h2>💎 CRYSTAL CLASSIC PLUS</h2><p>Ожидание данных от MT5...</p></body></html>"
    
    html = """
    <html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'>
    <title>Crystal Classic Plus</title>
    <script src="https://jsdelivr.net"></script>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 12px; margin: 0; }
        .card { background: #09090b; border: 1px solid #1c1c1f; border-radius: 14px; padding: 15px; margin-bottom: 15px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }
        .label { font-size: 10px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px; }
        .val-big { font-size: 22px; font-weight: 900; color: #ffffff; }
        .chart-box { height: 120px; margin: 15px 0; background: #0c0c0e; border: 1px solid #1c1c1f; border-radius: 8px; padding: 8px; }
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
    """
    
    html += "<h2 style='font-size:18px; font-weight:900; margin-bottom:15px; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>Crystal Classic Plus (USD)</h2>"
    for login, info in accounts_data.items():
        raw_balance = float(info.get('balance', 0.0))
        usd_balance = raw_balance / 100.0
        usd_equity = float(info.get('equity', 0.0)) / 100.0
        
        # УБИРАЕМ ДЕЛЕНИЕ НА 100 ДЛЯ МАРЖИ — ТЕПЕРЬ ТУТ БУДЕТ ЧЕСТНЫЙ ИСПРАВЛЕННЫЙ ВЫВОД $84
        usd_margin = float(info.get('margin', 0.0))
        usd_free_margin = float(info.get('free_margin', 0.0))
        
        drawdown_usd = usd_balance - usd_equity
        dd_percent = (drawdown_usd / usd_balance) * 100 if usd_balance > 0 else 0
        
        if dd_percent <= 2:     account_color = "#10b981"
        elif dd_percent <= 10:  account_color = "#f59e0b"
        else:                   account_color = "#ef4444"

        # Извлекаем точки истории для недельного кривой
        pts = history_data.get(login, [])
        lbls = [p["time"] for p in pts]
        vals = [p["equity"] for p in pts]

        html += f"""
        <div class='card' style='border-left: 5px solid {account_color};'>
            <div style='display:flex;justify-content:space-between;color:#71717a;font-size:11px;'>
                <b>Счёт №{login}</b> 
                <span>{info.get('company','')}</span>
            </div>
            
            <div class='grid'>
                <div><span class='label'>Баланс аккаунта</span><br><b class='val-big'>${usd_balance:,.2f}</b></div>
                <div style='text-align:right;'><span class='label'>Общая Просадка</span><br><b class='val-big' style='color:{account_color}'>{dd_percent:.2f}%</b></div>
            </div>
            
            <div style='background:#0c0c0e;padding:8px;border-radius:8px;font-size:11px;display:flex;justify-content:space-between;color:#e4e4e7;border:1px solid #1c1c1f;'>
                <span>В работе: ${usd_margin:,.2f}</span>
                <span>Свободно: ${usd_free_margin:,.2f}</span>
            </div>

            <!-- КРИВАЯ ДОХОДНОСТИ ЗА НЕДЕЛЮ -->
            <div style='margin-top:12px;' class='label'>Кривая доходности Equity (Неделя)</div>
            <div class='chart-box'><canvas id='chart_{login}'></canvas></div>
            <script>
                new Chart(document.getElementById('chart_{login}'), {{
                    type: 'line',
                    data: {{
                        labels: {repr(lbls)},
                        datasets: [{{
                            data: {repr(vals)},
                            borderColor: '#3b82f6',
                            borderWidth: 2,
                            pointRadius: 0,
                            fill: true,
                            backgroundColor: 'rgba(59, 130, 246, 0.02)',
                            tension: 0.1
                        }}]
                    }},
                    options: {{
                        responsive: true, maintainAspectRatio: false,
                        plugins: {{ legend: {{ display: false }} }},
                        scales: {{ x:{{ display: false }}, y:{{ grid:{{ color: '#1c1c1f' }}, ticks:{{ color: '#71717a', font:{{size:8}} }} }} }}
                    }}
                }});
            </script>
            
            <div class='tiles'>
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
            <div class='tile {tile_class}'>
                <span class='tile-name'>{pair}</span>
                <span class='tile-lots'>{lots_text}</span>
                <div>
                    <div class='tile-percent' style='color:{text_color};'>{pct_display}</div>
                    <div class='tile-profit' style='color:#71717a;'>({prof_display})</div>
                </div>
            </div>
            """
        html += "</div></div>"
    
    html += "</body></html>"
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
