import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="FX Monitor API")
accounts_data = {}

@app.post("/api/update")
async def update_account(request: Request):
    try:
        data = await request.json()
        login = data.get("login")
        accounts_data[login] = {
            "company": data.get("company"),
            "balance": data.get("balance"),
            "equity": data.get("equity"),
            "currency": data.get("currency")
        }
        print(f"📥 Получены данные для счета: {login}")
        return {"status": "success"}
    except Exception as e:
        return {"status": "error"}

@app.get("/", response_class=HTMLResponse)
def home():
    if not accounts_data:
        return """
        <html><head><meta charset='utf-8'><title>FX Monitor</title></head>
        <body style='font-family:sans-serif; text-align:center; padding-top:50px; background:#121212; color:#fff;'>
            <h1>📈 FX Монитор</h1><p>Сайт успешно запущен в облаке! Ожидаем данные от MT5...</p>
        </body></html>
        """
    
    html_content = """
    <html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>FX Monitor</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #121212; color: #fff; padding: 20px; }
        .card { background: #1e1e1e; border-radius: 12px; padding: 20px; margin-bottom: 15px; border: 1px solid #2d2d2d; }
        h2 { margin: 0 0 10px 0; color: #007aff; }
        .val { font-size: 24px; font-weight: bold; color: #34c759; margin: 5px 0; }
    </style></head>
    <body>
        <h1>📊 Мониторинг счетов (iPhone)</h1><hr style='border:1px solid #2d2d2d;'>
    """
    for login, info in accounts_data.items():
        html_content += f"""
        <div class='card'>
            <h2>Счет №{login}</h2>
            <div style='color:#aaa; font-size:14px;'>Брокер: {info['company']}</div>
            <div class='val'>💰 {info['balance']} {info['currency']}</div>
            <div style='font-size:16px; color:#ff9500;'>Средства (Equity): {info['equity']}</div>
        </div>
        """
    html_content += "</body></html>"
    return html_content

if __name__ == "__main__":
    # Читаем порт, который автоматически выдаст нам Render
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
