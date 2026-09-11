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
        return "<html><body style='background:#000;color:#aaa;text-align:center;padding-top:100px;font-family:sans-serif;'><h2>💎 CRYSTAL CLASSIC PLUS</h2><p>Ожидание данных от MT5...</p></body></html>"
    
    html = "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><style>body{font-family:sans-serif;background:#000;color:#fff;padding:15px;} .card{background:#09090b;border:1px solid #27272a;border-left:5px solid #10b981;border-radius:12px;padding:15px;margin-bottom:15px;} .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0;} .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px;} .tile{background:#141417;border:1px solid #27272a;border-radius:6px;padding:6px;font-size:11px;text-align:center;}</style></head><body>"
    html += "<h2 style='color:#3b82f6;'>Crystal Classic Plus</h2>"
    
    for login, info in accounts_data.items():
        html += f"""
        <div class='card'>
            <div style='display:flex;justify-content:between;color:#71717a;font-size:12px;'><b>Счет №{login}</b> <span>{info.get('company','')}</span></div>
            <div class='grid'>
                <div><span style='color:#71717a;font-size:10px;'>БАЛАНС</span><br><b style='font-size:20px;'>${info.get('balance',0):,}</b></div>
                <div style='text-align:right;'><span style='color:#71717a;font-size:10px;'>EQUITY</span><br><b style='font-size:20px;color:#3b82f6;'>${info.get('equity',0):,}</b></div>
            </div>
            <div style='background:#0c0c0e;padding:8px;border-radius:6px;font-size:12px;display:flex;justify-content:space-between;color:#e4e4e7;'>
                <span>В работе: ${info.get('margin',0):,}</span>
                <span>Свободно: ${info.get('free_margin',0):,}</span>
            </div>
            <div class='tiles'>
        """
        for pair, v in info.get("pairs", {}).items():
            lots = f"B:{v['buy']:.1f} S:{v['sell']:.1f}" if v['buy'] > 0 and v['sell'] > 0 else (f"Buy:{v['buy']:.1f}" if v['buy'] > 0 else f"Sell:{v['sell']:.1f}")
            html += f"<div class='tile'><b>{pair}</b><br><span style='color:#a1a1aa;font-size:9px;'>{lots}</span><br><b style='color:#ef4444;'>${v['profit']:.0f}</b></div>"
        html += "</div></div>"
    
    html += "</body></html>"
    return html
