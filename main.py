import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()
accounts_data = {}

@app.post("/api/update")
async def update_account(request: Request):
    try:
        data = await request.json()
        accounts_data[data.get("login")] = data
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
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 12px; margin: 0; }
        .card-list { display: flex; flex-direction: column; gap: 12px; margin-top: 10px; }
        
        /* Стили вкладок-аккордеонов */
        .account-accordion { background: #09090b; border-radius: 14px; border: 1px solid #1c1c1f; overflow: hidden; padding: 14px; cursor: pointer; }
        .accordion-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .acc-info { display: flex; flex-direction: column; gap: 2px; }
        .acc-title { font-size: 15px; font-weight: 800; color: #fff; }
        .acc-meta { font-size: 11px; color: #71717a; }
        .acc-stat { text-align: right; display: flex; flex-direction: column; gap: 2px; }
        .stat-dd { font-size: 15px; font-weight: 800; }
        .stat-profit { font-size: 12px; font-weight: 700; }
        
        /* Строка В работе + Процент Маржи */
        .work-line { border-top: 1px solid #1c1c1f; border-bottom: 1px solid #1c1c1f; padding: 8px 0; margin: 10px 0; font-size: 13px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }
        
        /* Плашки финансового отчета на главной */
        .profit-timeline { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 8px; }
        .profit-tab { background: #141417; border: 1px solid #27272a; border-radius: 6px; padding: 6px; text-align: center; }
        .profit-val { font-size: 10px; font-weight: 800; margin-top: 2px; }
        
        /* Раскрывающаяся подвкладка плотности */
        .accordion-content { display: none; padding-top: 12px; margin-top: 10px; border-top: 1px solid #1c1c1f; cursor: default; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
        .label { font-size: 9px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px; }
        .val-big { font-size: 20px; font-weight: 900; color: #ffffff; }
        
        /* Сетка вертикальных плиток валютных пар */
        .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
        .tile { border-radius: 8px; padding: 8px; display: flex; flex-direction: column; justify-content: space-between; min-height: 85px; border: 1px solid rgba(255,255,255,0.02); text-align: left; }
        .tile-name { font-size: 12px; font-weight: 800; color: #fff; margin-bottom: 4px; }
        .tile-dir { font-size: 10px; margin: 1px 0; font-weight: 600; }
        .tile-profit-box { margin-top: auto; display: flex; flex-direction: column; text-align: right; }
        .tile-profit { font-size: 10px; font-weight: 700; color: #71717a; }
        .tile-percent { font-size: 11px; font-weight: 800; }
        
        .t-green { background: linear-gradient(135deg, #022c22, #050b08); border-left: 3px solid #10b981; border-top: 1px solid #153a26; }
        .t-yellow { background: linear-gradient(135deg, #4d330c, #0c0802); border-left: 3px solid #f59e0b; border-top: 1px solid #6b4712; }
        .t-red { background: linear-gradient(135deg, #450a0a, #0f0505); border-left: 3px solid #ef4444; border-top: 1px solid #5c1919; }
    </style></head><body>
    <h2 style='font-size:18px; font-weight:900; margin-bottom:12px; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>Crystal Classic Plus (USD)</h2>
    <div class="card-list">
    """
    for login, info in accounts_data.items():
        raw_balance = float(info.get('balance', 0.0))
        usd_balance = raw_balance / 100.0
        usd_equity = float(info.get('equity', 0.0)) / 100.0
        
        # Нагрузка = Баланс - Эквити
        usd_in_work = usd_balance - usd_equity
        if usd_in_work < 0: usd_in_work = 0.0
        
        dd_percent = (usd_in_work / usd_balance) * 100 if usd_balance > 0 else 0
        
        # Расчет Уровня Маржи в процентах от ТОРГОВОГО БАЛАНСА (Эквити / Залог * 100)
        # Если сделок нет, уровень маржи равен 0
        raw_margin = float(info.get('margin', 0.0))
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
        def get_p_sign(val): return f"+${val:.2f}" if val > 0.01 else (f"-${abs(val):.2f}" if val < -0.01 else "$0.00")

        html += f"""
        <div class="account-accordion" style="border-left: 5px solid {status_color};" onclick="toggleAccordion(event, {login})">
            <!-- ШАПКА ВКЛАДКИ -->
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
            
            <!-- СТРОКА В РАБОТЕ + ПРОЦЕНТ МАРЖИ СЧЕТА -->
            <div class="work-line">
                <div>
                    <span style="font-size:8px; color:#71717a; text-transform:uppercase; display:block; margin-bottom:1px;">В торговле</span>
                    <span style="color:#ffffff; font-size:14px;">${usd_in_work:,.2f}</span>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:8px; color:#71717a; text-transform:uppercase; display:block; margin-bottom:1px;">Уровень маржи</span>
                    <span style="color:{status_color}; font-size:14px;">{margin_level if margin_level > 0 else '10000'}%</span>
                </div>
            </div>
            
            <!-- ФИНАНСОВЫЙ ОТЧЕТ -->
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
            
            <!-- РАСКРЫВАЮЩАЯСЯ ПОДВКЛАДКА -->
            <div class="accordion-content" id="content_{login}" onclick="event.stopPropagation();">
                <div class="grid">
                    <div><span class="label">Баланс счета</span><br><b class="val-big">${usd_balance:,.2f}</b></div>
                    <div style="text-align:right;"><span class="label">Чистые средства</span><br><b class="val-big" style="color:#3b82f6;">${usd_equity:,.2f}</b></div>
                </div>
                
                <div style="margin-top:10px;" class="label">Плотность позиций (Светофор пар)</div>
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
            
            # Эмуляция подсчета плотности колен (ордеров) для вывода в скобках
            # (Так как MQL5 выдает общий лот, мы аппроксимируем колена: если лот > 0, колен минимум 1, и растет пропорционально объему)
            b_count = int(b_lot * 10) if b_lot > 0 else 0
            s_count = int(s_lot * 10) if s_lot > 0 else 0
            
            pct_display = f"-{pair_dd_percent:.2f}%" if usd_pair_profit < 0 else (f"+{pair_dd_percent:.2f}%" if usd_pair_profit > 0 else "0.00%")
            prof_display = f"${usd_pair_profit:.2f}" if usd_pair_profit != 0 else "$0.00"

            html += f"""
                    <div class="tile {tile_class}">
                        <span class="tile-name">{pair}</span>
                        <div class="tile-dir" style="color:{'#10b981' if b_lot > 0 else '#71717a'}">🟢 B: {b_lot:.2f} ({b_count})</div>
                        <div class="tile-dir" style="color:{'#ef4444' if s_lot > 0 else '#71717a'}">🔴 S: {s_lot:.2f} ({s_count})</div>
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
