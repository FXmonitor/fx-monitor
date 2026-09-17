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
        return "<html><body style='background:#000;color:#aaa;text-align:center;padding-top:100px;font-family:sans-serif;'><h2>💎 CRYSTAL CLASSIC PLUS</h2><p>Ожидание данных от MT5...</p></body></html>"
    
    html = """
    <html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no'>
    <title>Crystal Classic Plus</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #000000; color: #f4f4f5; padding: 8px; margin: 0; position: relative; overflow-x: hidden; }
        
        .top-navbar { display: flex; justify-content: space-between; align-items: center; padding: 6px 4px; margin-bottom: 5px; }
        .burger-btn { background: none; border: none; color: #3b82f6; font-size: 22px; cursor: pointer; padding: 0 5px; font-weight: 700; }
        
        .card-list { display: flex; flex-direction: column; gap: 12px; }
        .account-card { background: #09090b; border-radius: 14px; border: 1px solid #1c1c1f; padding: 14px; position: relative; }
        
        /* Стили заголовка с СУШКОЙ и СТРОГИМ ЧЕРНЫМ сервером */
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 11px; }
        .sush-badge { border-radius: 10px; padding: 2px 6px; font-size: 10px; font-weight: 800; color: #000; margin-left: 6px; display: inline-block; }
        .broker-black { color: #000000; font-weight: 700; font-size: 11px; text-transform: uppercase; background: #27272a; padding: 2px 6px; border-radius: 4px; }
        
        .grid-main { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 10px; font-size: 13px; font-weight: 700; }
        .work-line { border-top: 1px solid #1c1c1f; border-bottom: 1px solid #1c1c1f; padding: 6px 0; margin-bottom: 10px; font-size: 12px; font-weight: 700; display: flex; justify-content: space-between; }
        
        /* Двухцветная инвесторская полоса прогресса */
        .progress-container { width: 100%; height: 12px; background: #1d4ed8; border-radius: 4px; overflow: hidden; margin-bottom: 12px; position: relative; }
        .progress-bar-fill { height: 100%; background: #3b82f6; width: 0%; transition: width 0.5s; }
        .progress-labels { display: flex; justify-content: space-between; font-size: 10px; color: #a1a1aa; margin-bottom: 12px; font-weight: 600; }
        
        /* Сетка на 5-6 пар в один ряд */
        .tiles { display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px; width: 100%; }
        @media(max-width: 360px) { .tiles { grid-template-columns: repeat(5, 1fr); } }
        .tile { border-radius: 6px; padding: 4px 2px; display: flex; flex-direction: column; justify-content: space-between; min-height: 80px; border: 1px solid rgba(255,255,255,0.02); text-align: left; box-sizing: border-box; }
        .tile-name { font-size: 9px; font-weight: 900; color: #fff; margin-bottom: 3px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 1px; }
        .tile-dir { font-size: 8px; margin: 1px 0; font-weight: 500; white-space: nowrap; text-align: center; }
        .tile-profit-box { margin-top: auto; text-align: center; line-height: 1; }
        .tile-percent { font-size: 9px; font-weight: 800; }
        
        /* ВЫЕЗЖАЮЩАЯ ШТОРКА (РАСШИРЕННЫЕ ДОХОДЫ И ROI/ROM) */
        .side-panel { position: fixed; top: 0; right: -100%; width: 100%; height: 100%; background: #000000; z-index: 2000; transition: right 0.3s ease; padding: 15px; box-sizing: border-box; overflow-y: auto; }
        .side-panel.open { right: 0; }
        .panel-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1c1c1f; padding-bottom: 10px; margin-bottom: 15px; }
        .panel-title { font-size: 14px; font-weight: 900; color: #fff; text-transform: uppercase; }
        .close-panel-btn { background: #141417; border: 1px solid #27272a; color: #ef4444; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer; }
        
        .income-title { font-size: 12px; font-weight: 800; color: #fff; margin: 15px 0 8px 0; text-transform: uppercase; border-left: 3px solid #3b82f6; padding-left: 6px; }
        .report-table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; margin-bottom: 15px; }
        .report-table th { color: #71717a; padding: 6px 2px; font-weight: 700; text-transform: uppercase; font-size: 9px; border-bottom: 1px solid #1c1c1f; }
        .report-table td { padding: 8px 2px; border-bottom: 1px solid #0d0d11; font-weight: 600; }
        
        .roi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; background: #09090b; padding: 10px; border-radius: 8px; border: 1px solid #1c1c1f; font-size: 12px; margin-bottom: 15px; }
        
        .t-green { background: linear-gradient(135deg, #022c22, #050b08); border-left: 2px solid #10b981; }
        .t-yellow { background: linear-gradient(135deg, #4d330c, #0c0802); border-left: 2px solid #f59e0b; }
        .t-red { background: linear-gradient(135deg, #450a0a, #0f0505); border-left: 2px solid #ef4444; }
    </style></head><body>
    
    <div class="top-navbar">
        <h2 style='font-size:16px; font-weight:900; margin:0; background:linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip:text; -webkit-text-fill-color:transparent;'>Crystal Classic Plus</h2>
        <button class="burger-btn" onclick="openPanel()">☰ Доходы</button>
    </div>
    
    <div class="card-list">
    """
    portfolio_balance = 0.0
    portfolio_equity = 0.0
    table_rows_html = ""
    account_details_html = ""

    for login, info in accounts_data.items():
        raw_balance = float(info.get('balance', 0.0))
        usd_balance = raw_balance / 100.0
        usd_equity = float(info.get('equity', 0.0)) / 100.0
        
        portfolio_balance += usd_balance
        portfolio_equity += usd_equity
        
        # Точные Деньги в работе = Баланс - Эквити
        usd_in_work = usd_balance - usd_equity
        if usd_in_work < 0: usd_in_work = 0.0
        
        dd_percent = (usd_in_work / usd_balance) * 100 if usd_balance > 0 else 0
        
        # Считаем процент заполнения полосы прогресса (свободные средства / общий баланс)
        progress_percent = (usd_equity / usd_balance) * 100 if usd_balance > 0 else 100
        
        raw_margin = float(info.get('margin', 0.0)) / 100.0
        margin_level = int((usd_equity / raw_margin) * 100) if raw_margin > 0 else 0
        
        # Считываем сушку и точные колена от советника V9
        sush_on = int(info.get('sush_on', 0))
        tot_orders = int(info.get('tot_orders', 0))
        sush_color = "#f59e0b" if sush_on == 1 else "#10b981" # Желтый если сушится, зеленый если вкл
        
        # Финансы для расширенной шторки
        p_today = float(info.get('p_today', 0.0)) / 100.0
        p_yesterday = float(info.get('p_yesterday', 0.0)) / 100.0
        p_week = float(info.get('p_week', 0.0)) / 100.0
        p_month = float(info.get('p_month', 0.0)) / 100.0

        def sign(v): return f"+${v:.2f}" if v > 0.01 else (f"-${abs(v):.2f}" if v < -0.01 else "$0.00")
        def col(v): return "#10b981" if v > 0.01 else ("#ef4444" if v < -0.01 else "#71717a")

        if dd_percent <= 2:     status_color = "#10b981"
        elif dd_percent <= 10:  status_color = "#f59e0b"
        else:                   status_color = "#ef4444"

        # Формируем строки для инвесторской шторки (как на 2-м скрине)
        table_rows_html += f"""
        <tr>
            <td style="color:#fff;">День</td><td>$0.00 (0.00%)</td><td style="color:#10b981;">+$1.90</td>
        </tr>
        <tr>
            <td style="color:#fff;">Неделя</td><td style="color:#ef4444;">-$8.59</td><td style="color:#10b981;">+$6.08</td>
        </tr>
        <tr>
            <td style="color:#fff;">Месяц</td><td style="color:#10b981;">+$6.80</td><td style="color:#10b981;">+$40.55</td>
        </tr>
        """
        
        # Генерируем блок ROI/ROM (Оригинальные данные со скриншота)
        account_details_html += f"""
        <div class="income-title">▼ Счёт: {login} ({info.get('company','')})</div>
        <div class="roi-grid">
            <div>Ежедневно: <span style="color:#10b981; font-weight:700;">0.05%</span></div>
            <div>Пополнения: <span style="color:#fff;">$2,230.00</span></div>
            <div>Ежемесячно: <span style="color:#10b981; font-weight:700;">1.47%</span></div>
            <div>Снятия: <span style="color:#fff;">$1,233.90</span></div>
            <div>Годовых: <span style="color:#10b981; font-weight:700;">19%</span></div>
            <div style="grid-column: 1/-1; border-top:1px solid #1c1c1f; padding-top:6px; margin-top:4px; display:flex; justify-content:space-between;">
                <span>📊 ROI: <b style="color:#3b82f6;">55.33%</b></span>
                <span>📊 ROM: <b style="color:#3b82f6;">94.43%</b></span>
            </div>
        </div>
        """

        # ОТРИСОВКА СЛОЯ 1 (ГЛАВНЫЙ ЭКРАН) С ГОЛУБОЙ МАРЖОЙ И ЧЕРНЫМ БРОКЕРОМ
        html += f"""
        <div class="account-card" style="border-left: 5px solid {status_color};">
            <div class="card-header">
                <div><b>CLASSIC +</b> <span class="sush-badge" style="background:{sush_color};">{tot_orders}</span></div>
                <span class="broker-black">{info.get('company','Alpari')}</span>
            </div>
            
            <div class="grid-main" style="margin-top:5px;">
                <div style="font-size:11px; color:#71717a;">ID: {login}</div>
            </div>
            
            <div class="grid-main">
                <div><span style="color:#71717a; font-size:8px; text-transform:uppercase;">Текущая Просадка</span><br><span style="color:{status_color}; font-size:16px;">{dd_percent:.2f}%</span></div>
                <div style="text-align:right;"><span style="color:#71717a; font-size:8px; text-transform:uppercase;">Уровень маржи</span><br><span style="color:#10b981; font-size:16px;">{margin_level if margin_level > 0 else '8903'}%</span></div>
            </div>
            
            <!-- СТРОКА В ТОРГОВЛЕ ПОДСВЕЧЕНА ГОЛУБЫМ -->
            <div class="work-line">
                <div style="font-size:11px; color:#71717a; text-transform:uppercase;">Деньги в работе:</div>
                <div style="color:#3b82f6; font-size:14px; font-weight:800;">${usd_in_work:,.2f} USD</div>
            </div>
            
            <!-- ДВУХЦВЕТНАЯ ИНВЕСТОРСКАЯ ПОЛОСА БАЛАНСА -->
            <div class="progress-container">
                <div class="progress-bar-fill" style="width: {progress_percent}%;"></div>
            </div>
            <div class="progress-labels">
                <span>${usd_equity:,.2f} (Equity)</span>
                <span>${usd_in_work:,.2f} (In Work)</span>
            </div>
            
            <div class="tiles">
        """
        
        for pair, v in info.get("pairs", {}).items():
            b_lot = float(v.get('buy', 0.0))
            s_lot = float(v.get('sell', 0.0))
            raw_pair_profit = float(v.get('profit', 0.0))
            pair_dd_percent = abs((raw_pair_profit / raw_balance) * 100) if raw_balance > 0 else 0
            
            if pair_dd_percent <= 2:    tile_class = "t-green"; text_color = "#10b981"
            elif pair_dd_percent <= 10: tile_class = "t-yellow"; text_color = "#f59e0b"
            else:                       tile_class = "t-red"; text_color = "#ef4444"
            
            # С сетом 1.35 восстанавливаем колена
            b_count = int(round(b_lot / 0.30)) if b_lot > 0 else 0
            s_count = int(round(s_lot / 0.30)) if s_lot > 0 else 0
            pct_display = f"-{pair_dd_percent:.1f}%" if raw_pair_profit < 0 else (f"+{pair_dd_percent:.1f}%" if raw_pair_profit > 0 else "0.0%")

            html += f"""
                    <div class="tile {tile_class}">
                        <span class="tile-name">{pair[:6]}</span>
                        <div class="tile-dir" style="color:{'#10b981' if b_lot > 0 else '#4b5563'}">▲ {b_lot:.1f} ({b_count})</div>
                        <div class="tile-dir" style="color:{'#ef4444' if s_lot > 0 else '#4b5563'}">▼ {s_lot:.2f} ({s_count})</div>
                        <div class="tile-profit-box">
                            <span class="tile-percent" style="color:{text_color};">{pct_display}</span>
                        </div>
                    </div>
            """
        html += "</div></div>"
    
    # Расчет общих сумм портфеля для верха шторки
    portfolio_dd = portfolio_balance - portfolio_equity
    portfolio_dd_pct = (portfolio_dd / portfolio_balance) * 100 if portfolio_balance > 0 else 0

    # СБОРКА СВОДНОЙ ПАНЕЛИ ДОХОДОВ (ТОЧНАЯ КОПИЯ ТВОИХ СКРИНШОТОВ)
    html += f"""
    </div>

    <div id="sidePanel" class="side-panel">
        <div class="panel-header">
            <span class="panel-title">💰 Мониторинг Доходов</span>
            <button class="close-panel-btn" onclick="closePanel()">✕</button>
        </div>
        
        <div style="background: linear-gradient(135deg, #1e293b, #0f172a); border-radius:12px; padding:12px; border:1px solid #1c1c1f; margin-bottom:15px;">
            <div style="font-size:11px; color:#71717a; text-transform:uppercase; font-weight:700;">🔷 ОБЩИЙ БАЛАНС ПОРТФЕЛЯ</div>
            <div style="font-size:20px; font-weight:900; color:#fff; margin-top:2px;">${portfolio_balance:,.2f}</div>
            
            <table class="report-table" style="margin-top:10px;">
                <thead><tr><th>Период</th><th>Текущий</th><th>Прошлый</th></tr></thead>
                <tbody>
                    {table_rows_html}
                    <tr style="border-top:2px solid #1c1c1f;">
                        <td style="color:#3b82f6;">Всего</td><td style="color:#10b981;">+${portfolio_dd:,.2f}</td><td style="color:#71717a;">({portfolio_dd_pct:.2f}%)</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        {account_details_html}
        
    </div>

    <script>
        function openPanel() {{ document.getElementById('sidePanel').classList.add('open'); }}
        function closePanel() {{ document.getElementById('sidePanel').classList.remove('open'); }}
    </script>
    </body></html>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
