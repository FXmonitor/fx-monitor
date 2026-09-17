import os
import uvicorn
import math
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

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
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 8px; margin: 0; }
        .card-list { display: flex; flex-direction: column; gap: 10px; margin-top: 5px; }
        
        .account-accordion { background: #09090b; border-radius: 12px; border: 1px solid #1c1c1f; overflow: hidden; padding: 12px; cursor: pointer; }
        .accordion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .acc-info { display: flex; flex-direction: column; gap: 2px; }
        .acc-title { font-size: 13px; font-weight: 800; color: #fff; }
        .acc-meta { font-size: 10px; color: #71717a; }
        .acc-stat { text-align: right; display: flex; flex-direction: column; gap: 2px; }
        .stat-dd { font-size: 14px; font-weight: 800; }
        .stat-profit { font-size: 11px; font-weight: 700; }
        
        .work-line { border-top: 1px solid #1c1c1f; border-bottom: 1px solid #1c1c1f; padding: 6px 0; margin: 8px 0; font-size: 12px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
        
        .profit-timeline { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-top: 6px; }
        .profit-tab { background: #141417; border: 1px solid #27272a; border-radius: 6px; padding: 4px; text-align: center; }
        .profit-val { font-size: 9px; font-weight: 800; margin-top: 1px; }
        
        .accordion-content { display: none; padding-top: 10px; margin-top: 8px; border-top: 1px solid #1c1c1f; cursor: default; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; }
        .label { font-size: 8px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px; }
        .val-big { font-size: 18px; font-weight: 900; color: #ffffff; }
        
        .tiles { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; width: 100%; box-sizing: border-box; }
        .tile { border-radius: 6px; padding: 4px; display: flex; flex-direction: column; justify-content: space-between; min-height: 85px; border: 1px solid rgba(255,255,255,0.02); text-align: left; box-sizing: border-box; overflow: hidden; }
        .tile-name { font-size: 10px; font-weight: 900; color: #fff; margin-bottom: 2px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 2px; }
        .tile-dir { font-size: 9px; margin: 1px 0; font-weight: 500; white-space: nowrap; }
        .tile-profit-box { margin-top: auto; display: flex; flex-direction: column; text-align: right; line-height: 1.1; }
        .tile-profit { font-size: 8px; font-weight: 600; color: #71717a; }
        .tile-percent { font-size: 9px; font-weight: 800; }
        
        .t-green { background: linear-gradient(135deg, #022c22, #050b08); border-left: 2px solid #10b981; }
        .t-yellow { background: linear-gradient(135deg, #4d330c, #0c0802); border-left: 2px solid #f59e0b; }
        .t-red { background: linear-gradient(135deg, #450a0a, #0f0505); border-left: 2px solid #ef4444; }
    </style></head><body>
    <h2 style='font-size:16px; font-weight:900; margin-bottom:10px; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>Crystal Classic Plus (USD)</h2>
    <div class="card-list">
    """
    for login, info in accounts_data.items():
        raw_balance = float(info.get('balance', 0.0))
        usd_balance = raw_balance / 100.0
        usd_equity = float(info.get('equity', 0.0)) / 100.0
        
        usd_in_work = usd_balance - usd_equity
        if usd_in_work < 0: usd_in_work = 0.0
        
        dd_percent = (usd_in_work / usd_balance) * 100 if usd_balance > 0 else 0
        
        raw_margin = float(info.get('margin', 0.0)) / 100.0
        margin_level = int((usd_equity / raw_margin) * 100) if raw_margin > 0 else 0
        
        p_today = float(info.get('p_today', 0.0)) / 100.0
        p_yesterday = float(info.get('p_yesterday', 0.0)) / 100.0
        p_week = float(info.get('p_week', 0.0)) / 100.0
        p_month = float(info.get('p_month', 0.0)) / 100.0
        
        p_today_color = "#10b981" if p_today > 0.01 else ("#ef4444" if p_today < -0.01 else "#71717a")
        p_today_text = f"+${p_today:.2f}" if p_today > 0.01 else f"${p_today:.2f}"

        if dd_percent <= 2:     status_color = "#10b981"
        elif dd_percent <= 10:  status_color = "#f59e0b"
        else:                   status_color = "#ef4444"

        def get_p_color(val): return "#10b981" if val > 0.01 else ("#ef4444" if val < -0.01 else "#71717a")
        def get_p_sign(val): return f"+${val:.1f}" if val > 0.01 else (f"-${abs(val):.1f}" if val < -0.01 else "$0.0")

        html += f"""
        <div class="account-accordion" style="border-left: 5px solid {status_color};" onclick="toggleAccordion(event, {login})">
            <div class="accordion-header">
                <div class="acc-info">
                    <span class="acc-title">Crystal Classic Plus</span>
                    <span class="acc-meta">ID: {login} | {info.get('company','')}</span>
                </div>
                <div class="acc-stat">
                    <span class="stat-dd" style="color:{status_color}">DD: {dd_percent:.2f}%</span>
                    <span class="stat-profit" style="color:{p_today_color}">{p_today_text}</span>
                </div>
            </div>
            
            <div class="work-line">
                <div>
                    <span style="font-size:8px; color:#71717a; text-transform:uppercase; display:block; margin-bottom:1px;">В торговле</span>
                    <span style="color:#ffffff; font-size:13px;">${usd_in_work:,.2f}</span>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:8px; color:#71717a; text-transform:uppercase; display:block; margin-bottom:1px;">Уровень маржи</span>
                    <span style="color:{status_color}; font-size:13px;">{margin_level if margin_level > 0 else '10000'}%</span>
                </div>
            </div>
            
            <div class="profit-timeline">
                <div class="profit-tab">
                    <span class="label" style="font-size:7px; color:#71717a;">Сегодня</span>
                    <div class="profit-val" style="color:{get_p_color(p_today)}">{get_p_sign(p_today)}</div>
                </div>
                <div class="profit-tab">
                    <span class="label" style="font-size:7px; color:#71717a;">Вчера</span>
                    <div class="profit-val" style="color:{get_p_color(p_yesterday)}">{get_p_sign(p_yesterday)}</div>
                </div>
                <div class="profit-tab">
                    <span class="label" style="font-size:7px; color:#71717a;">Неделя</span>
                    <div class="profit-val" style="color:{get_p_color(p_week)}">{get_p_sign(p_week)}</div>
                </div>
                <div class="profit-tab">
                    <span class="label" style="font-size:7px; color:#71717a;">Месяц</span>
                    <div class="profit-val" style="color:{get_p_color(p_month)}">{get_p_sign(p_month)}</div>
                </div>
            </div>
            
            <div class="accordion-content" id="content_{login}" onclick="event.stopPropagation();">
                <div class="grid">
                    <div><span class="label">Баланс счета</span><br><b class="val-big">${usd_balance:,.2f}</b></div>
                    <div style="text-align:right;"><span class="label">Чистые средства</span><br><b class="val-big" style="color:#3b82f6;">${usd_equity:,.2f}</b></div>
                </div>
                
                <div style="margin-top:8px; margin-bottom:6px;" class="label">Плотность позиций (Светофор пар)</div>
                <div class="tiles">
        """
        
        for pair, v in info.get("pairs", {}).items():
            b_lot = float(v.get('buy', 0.0))
            s_lot = float(v.get('sell', 0.0))
            raw_pair_profit = float(v.get('profit', 0.0))
            usd_pair_profit = raw_pair_profit / 100.0
            pair_dd_percent = abs((raw_pair_profit / raw_balance) * 100) if raw_balance > 0 else 0
            
            if pair_dd_percent <= 2:    tile_class = "t-green"; text_color = "#10b981"
            elif pair_dd_percent <= 10: tile_class = "t-yellow"; text_color = "#f59e0b"
            else:                       tile_class = "t-red"; text_color = "#ef4444"
            
            # УМНЫЙ АЛГОРИТМ ОПРЕДЕЛЕНИЯ КОЛЕН ПО СЕТУ EXPONENT = 1.35
            # Автоматически определяет базовый лот брокера (0.01 или 0.10)
            def calculate_orders(total_lot):
                if total_lot <= 0: return 0
                base = 0.10 if total_lot >= 0.10 else 0.01
                exponent = 1.35
                sum_lots = 0.0
                orders = 0
                while sum_lots < (total_lot - 0.005) and orders < 20:
                    sum_lots += base * math.pow(exponent, orders)
                    orders += 1
                return orders if orders > 0 else 1

            b_count = calculate_orders(b_lot)
            s_count = calculate_orders(s_lot)
            
            pct_display = f"-{pair_dd_percent:.1f}%" if usd_pair_profit < 0 else (f"+{pair_dd_percent:.1f}%" if usd_pair_profit > 0 else "0.0%")
            prof_display = f"${usd_pair_profit:.1f}" if usd_pair_profit != 0 else "$0.0"

            html += f"""
                    <div class="tile {tile_class}">
                        <span class="tile-name">{pair[:6]}</span>
                        <div class="tile-dir" style="color:{'#10b981' if b_lot > 0 else '#4b5563'}">▲ {b_lot:.2f} ({b_count})</div>
                        <div class="tile-dir" style="color:{'#ef4444' if s_lot > 0 else '#4b5563'}">▼ {s_lot:.2f} ({s_count})</div>
                        <div class="tile-profit-box">
                            <span class="tile-percent" style="color:{text_color};">{pct_display}</span>
                            <span class="tile-profit">({prof_display})</span>
                        </div>
                    </div>
            """
        html += """
                </div>
            </div>
        </div>
        """
    
    html += """
    </div>
    <script>
        function toggleAccordion(event, login) {
            var content = document.getElementById('content_' + login);
            if (content.style.display === 'block') {
                content.style.display = 'none';
            } else {
                content.style.display = 'block';
            }
        }
    </script>
    </body></html>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
