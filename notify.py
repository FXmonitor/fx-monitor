"""notify.py — Telegram-уведомления GTrade.
Env на Render: TG_TOKEN, TG_CHAT. Необязательно: TG_TZ (часы от UTC), NOTIFY_DB (путь к файлу БД).
Проверка: /tg-test   Состояние: /tg-status   (если задан FX_ADMIN_PASS, добавьте ?p=ПАРОЛЬ)
"""
import os
import json
import math
import time
import sqlite3
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from fastapi.responses import JSONResponse

# ----------------------------------------------------------------- настройки
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()
DB_PATH = os.environ.get("NOTIFY_DB", str(Path(__file__).resolve().parent / "notify_state.db"))

MIN_MOVE_USD = 1.0        # баланс: сообщение, как только накопилось изменение >= $1
DD_START = 40.0           # первое сообщение о просадке при >= 40%
DD_STEP = 10.0            # дальше шаг 10% в обе стороны
LOSS_AFTER_SEC = 180      # нет пакетов дольше 3 минут = потеря связи
POLL_SEC = 1              # проверка каждую секунду без задержек
CLEARING = (23 * 60 + 55, 5)          # клиринг: с 23:55 до 00:05
WEEKEND_FROM = (4, 23 * 60 + 59)      # с пятницы 23:59
WEEKEND_TO = (6, 23 * 60 + 59)        # до воскресенья 23:59

M = None                  # модуль main.py (задаётся в init)
ST = {}                   # состояние счетов в памяти (зеркало БД)
LAST = {"err": "", "sent": "", "ok_time": ""}
DISC = {}                 # login -> с какого времени терминал сообщает connected=0
START_TS = time.time()
QUIET_TS = 0.0            # когда в последний раз был "тихий период"
_db = None
_lock = threading.Lock()


# ----------------------------------------------------------------- база данных
def db_open():
    global _db
    _db = sqlite3.connect(DB_PATH, check_same_thread=False)
    _db.execute("""CREATE TABLE IF NOT EXISTS account_state(
        login TEXT PRIMARY KEY, name TEXT, balance REAL,
        last_reported_dd REAL DEFAULT 0, connection_alert_sent INTEGER DEFAULT 0,
        last_ping_time REAL)""")
    _db.commit()
    for r in _db.execute("SELECT login,name,balance,last_reported_dd,connection_alert_sent,last_ping_time FROM account_state"):
        ST[r[0]] = dict(name=r[1] or "", balance=r[2], last_reported_dd=r[3] or 0.0,
                        connection_alert_sent=bool(r[4]), last_ping_time=r[5] or 0.0)


def db_save(login):
    s = ST[login]
    with _lock:
        _db.execute("""INSERT INTO account_state(login,name,balance,last_reported_dd,connection_alert_sent,last_ping_time)
            VALUES(?,?,?,?,?,?) ON CONFLICT(login) DO UPDATE SET name=excluded.name,balance=excluded.balance,
            last_reported_dd=excluded.last_reported_dd,connection_alert_sent=excluded.connection_alert_sent,
            last_ping_time=excluded.last_ping_time""",
                    (login, s["name"], s["balance"], s["last_reported_dd"],
                     1 if s["connection_alert_sent"] else 0, s["last_ping_time"]))
        _db.commit()


# ----------------------------------------------------------------- Telegram
def send(text):
    if not TG_TOKEN or not TG_CHAT:
        LAST["err"] = "не заданы TG_TOKEN / TG_CHAT"
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = json.dumps({
        "chat_id": TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode("utf-8")
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            ok = bool(json.loads(r.read().decode("utf-8")).get("ok"))
        LAST["err"] = "" if ok else "Telegram вернул ok=false"
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode("utf-8")).get("description", "")
        except Exception:
            desc = ""
        LAST["err"] = f"HTTP {e.code} {desc}"
        ok = False
    except Exception as e:
        LAST["err"] = f"{type(e).__name__}: сеть/таймаут"
        ok = False
    if ok:
        LAST["sent"] = text
        LAST["ok_time"] = now_local().strftime("%d.%m %H:%M:%S")
    return ok


# ----------------------------------------------------------------- время
def now_local():
    tz = float(os.environ.get("TG_TZ", getattr(M, "TZ_HOURS", 3.0)))
    return datetime.utcnow() + timedelta(hours=tz)


def is_clearing(t):
    m = t.hour * 60 + t.minute
    return m >= CLEARING[0] or m <= CLEARING[1]


def is_weekend(t):
    wd, m = t.weekday(), t.hour * 60 + t.minute
    if wd == WEEKEND_FROM[0]:
        return m >= WEEKEND_FROM[1]
    if wd == 5:
        return True
    if wd == WEEKEND_TO[0]:
        return m < WEEKEND_TO[1]
    return False


def is_quiet():
    t = now_local()
    return is_clearing(t) or is_weekend(t)


# ----------------------------------------------------------------- шаблоны
def money(x):
    return str(int(round(x))) if abs(x - round(x)) < 0.005 else f"{x:.2f}"


def pct_str(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def msg_profit(v, name):
    return f"💵 <b>+{money(v)}$</b> ▲ — баланс у {escape(name)}"


def msg_withdraw(v, name):
    return f"💸 <b>-{money(abs(v))}$</b> 🔻 — баланс у {escape(name)}"


def msg_dd(dd, up, name):
    return f"⚔️ -{pct_str(dd)}% {'🔻' if up else '▲'} — уровень просадки у {escape(name)}"


def msg_lost(name):
    return f"🆘 {escape(name)} терминал не может подключиться к торговому счету! Перезапустите ваш Metatrader"


def msg_back(name):
    return f"✅ {escape(name)} подключение восстановлено!"


# ----------------------------------------------------------------- логика
def num(x, d=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else d
    except Exception:
        return d


def acc_name(login, info):
    s = M.SETTINGS.get(login, {})
    n = s.get("name") if isinstance(s, dict) else ""
    return str(n or info.get("name") or info.get("label") or f"Счёт {login}")


def process_packet(login, info, st):
    kb = 0.01 if M.CENT else 1.0
    bal = num(info.get("balance")) * kb
    eq = num(info.get("equity"), num(info.get("balance"))) * kb
    name = acc_name(login, info)
    st["name"] = name
    first = st["balance"] is None

    dd = max(0.0, (bal - eq) / bal * 100.0) if bal > 0 else 0.0
    level = math.floor(dd / DD_STEP) * DD_STEP if dd >= DD_START else 0.0

    if first:
        st["balance"] = bal
        st["last_reported_dd"] = level      # после рестарта молча принимаем текущий уровень
        return

    lines = []
    bal_triggered = False
    dd_triggered = False

    # 1) баланс: копим разницу от последнего отправленного баланса, пока не наберётся >= $1
    d = bal - st["balance"]
    if d >= MIN_MOVE_USD - 1e-9:
        lines.append(msg_profit(d, name))
        bal_triggered = True
    elif d <= -MIN_MOVE_USD + 1e-9:
        lines.append(msg_withdraw(d, name))
        bal_triggered = True

    # 2) просадка: шаг 10% от последнего отправленного уровня
    last = st["last_reported_dd"]
    up = dd >= DD_START - 1e-9 if last == 0 else dd >= last + DD_STEP - 1e-9
    down = last > 0 and dd <= last - DD_STEP + 1e-9
    if up or down:
        lines.append(msg_dd(dd, up, name))
        dd_triggered = True

    # отправляем одним сообщением (если сработали оба — будут в 2 строки, как в эталоне)
    if lines and send("\n".join(lines)):
        if bal_triggered:
            st["balance"] = bal
        if dd_triggered:
            st["last_reported_dd"] = level


def tick():
    global QUIET_TS
    now = time.time()
    quiet = is_quiet()
    if quiet:
        QUIET_TS = now
    acc = {str(k): v for k, v in list(M.accounts_data.items())}
    seen = {str(k): v for k, v in list(M.last_seen.items())}

    for login in set(acc) | set(ST):
        st = ST.setdefault(login, dict(name="", balance=None, last_reported_dd=0.0,
                                       connection_alert_sent=False, last_ping_time=0.0))
        info = acc.get(login) or {}
        changed = False

        ts = seen.get(login, 0.0)
        if login in acc and ts > st["last_ping_time"]:
            st["last_ping_time"] = ts
            process_packet(login, info, st)
            changed = True

        # терминал сам сообщил, что нет связи с брокером (если робот шлёт connected)
        conn = info.get("connected") if info else None
        if conn is not None and num(conn, 1) == 0:
            DISC.setdefault(login, now)
        else:
            DISC.pop(login, None)
        disc_long = login in DISC and now - DISC[login] > LOSS_AFTER_SEC

        # потеря связи: отсчёт 3 минут начинается заново после старта сервиса и после тихого периода
        ref = max(st["last_ping_time"], START_TS, QUIET_TS)
        lost = (now - ref > LOSS_AFTER_SEC) or (disc_long and not quiet)
        name = st["name"] or f"Счёт {login}"

        if lost and not quiet and not st["connection_alert_sent"]:
            if send(msg_lost(name)):
                st["connection_alert_sent"] = True
                changed = True
        elif st["connection_alert_sent"]:
            fresh = login in acc and now - st["last_ping_time"] <= 30 and login not in DISC
            if fresh and send(msg_back(name)):
                st["connection_alert_sent"] = False
                changed = True

        if changed:
            db_save(login)


def loop():
    time.sleep(3)
    while True:
        try:
            tick()
        except Exception as e:
            LAST["err"] = f"tick: {type(e).__name__}"
        time.sleep(POLL_SEC)


# ----------------------------------------------------------------- подключение к сайту
def init(main_module, app):
    global M
    M = main_module
    try:
        db_open()
    except Exception as e:
        LAST["err"] = f"БД: {type(e).__name__}"

    def allowed(p):
        return not getattr(M, "ADMIN_PASS", "") or p == M.ADMIN_PASS

    def tg_test(p: str = ""):
        if not allowed(p):
            return JSONResponse({"status": "error", "detail": "bad pass"}, status_code=403)
        ok = send("✅ <b>GTrade</b>: тестовое сообщение, связь с Telegram работает")
        return {"ok": ok, "error": LAST["err"]}

    def tg_status(p: str = ""):
        if not allowed(p):
            return JSONResponse({"status": "error", "detail": "bad pass"}, status_code=403)
        return {"configured": bool(TG_TOKEN and TG_CHAT), "quiet_now": is_quiet(),
                "server_time": now_local().strftime("%d.%m %H:%M:%S"),
                "last_error": LAST["err"], "last_sent": LAST["sent"], "last_ok": LAST["ok_time"],
                "accounts": {k: dict(v) for k, v in ST.items()}}

    app.add_api_route("/tg-test", tg_test, methods=["GET"])
    app.add_api_route("/tg-status", tg_status, methods=["GET"])
    threading.Thread(target=loop, daemon=True).start()
