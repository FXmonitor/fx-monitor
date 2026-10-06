"""Telegram-уведомления FX Monitor. Меняйте пороги ниже; сайт (main.py) трогать не нужно."""
import os
import json
import time
import threading
import urllib.request
from html import escape

from fastapi.responses import HTMLResponse

# ============================ НАСТРОЙКИ ============================
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()

BAL_MIN = 1.0          # сообщение о балансе, когда накопилось $1 и больше
DD_FIRST = 40          # первый уровень просадки (на 30% и ниже молчим)
DD_STEP = 10           # шаг уровней: 40, 50, 60...
DD_BACK = 1.0          # сообщение о снижении: просадка ниже (DD_FIRST - DD_BACK), т.е. ниже 39%
STALE_SEC = 300        # нет данных от робота (сек)
CONN_SEC = 300         # терминал без связи с брокером (сек)
GRACE_SEC = 60         # после запуска сайта первую минуту молчим
WEEKEND_QUIET = True   # в выходные не слать «связь потеряна» и «нет данных»
# Выходные: суббота 00:00 — понедельник 03:00 по времени FX_TZ (по умолчанию Москва)
# ====================================================================

M = None               # модуль main.py, подставляется в init()
START_TIME = time.time()
STATE = {}
LAST = {"ok": None, "err": "", "time": ""}


def now_local():
    return M.now_local()


def send(text):
    if not (TG_TOKEN and TG_CHAT):
        LAST.update(ok=False, err="не заданы TG_TOKEN / TG_CHAT")
        return False
    try:
        body = json.dumps({"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = bool(json.loads(r.read().decode("utf-8")).get("ok"))
        LAST.update(ok=ok, err="" if ok else "Telegram ответил ошибкой",
                    time=now_local().strftime("%d.%m %H:%M:%S"))
        return ok
    except Exception as e:
        LAST.update(ok=False, err=str(e).replace(TG_TOKEN, "***")[:200],
                    time=now_local().strftime("%d.%m %H:%M:%S"))
        return False


def status_text():
    if not (TG_TOKEN and TG_CHAT):
        return "не настроен (нет TG_TOKEN / TG_CHAT)"
    if LAST["ok"] is None:
        return "настроен, отправок ещё не было"
    if LAST["ok"]:
        return f"работает, последняя отправка {LAST['time']}"
    return f"ОШИБКА: {LAST['err']}"


def acc_name(login, info):
    S = M.SETTINGS.get(str(login), {})
    return str(S.get("name") or info.get("name") or info.get("label") or f"Счёт {login}")


def is_weekend():
    n = now_local()
    wd = n.weekday()   # 0 = понедельник
    return wd in (5, 6) or (wd == 0 and n.hour < 3)


def fmt_amount(d):
    s = f"{d:+.2f}"
    if s.endswith(".00"):
        s = s[:-3]
    return s + "$"


def dd_update(dd_abs, lvl):
    """lvl — последний объявленный уровень (0 = ничего не объявлено).
    Возвращает (новый_уровень, событие): 'up' | 'down' | None."""
    cur = int(dd_abs // DD_STEP) * DD_STEP if dd_abs >= DD_FIRST else 0
    if cur > lvl:
        return cur, "up"
    if lvl >= DD_FIRST and dd_abs < DD_FIRST - DD_BACK:
        return 0, "down"
    return lvl, None


def check():
    now = time.time()
    grace = now - START_TIME < GRACE_SEC
    quiet = WEEKEND_QUIET and is_weekend()
    kb = 0.01 if M.CENT else 1.0
    msgs = []
    for login, info in list(M.accounts_data.items()):
        fresh = login not in STATE
        st = STATE.setdefault(login, {"bal": None, "dd": 0, "conn_since": None,
                                      "conn_sent": False, "stale_sent": False})
        silent = grace or fresh
        name = escape(acc_name(login, info))

        # 1. нет данных от робота
        stale = (now - M.last_seen.get(login, now)) > STALE_SEC
        if stale:
            if not st["stale_sent"] and not quiet and not silent:
                msgs.append(f"⚠️ <b>{name}</b> — нет данных от робота уже {STALE_SEC // 60} мин.")
                st["stale_sent"] = True
            continue
        if st["stale_sent"]:
            msgs.append(f"✅ <b>{name}</b> связь с роботом восстановлена!")
            st["stale_sent"] = False

        # 2. связь терминала с брокером
        cv = M.first_num(info, ("connected",))
        if cv is not None:
            if cv != 0:
                if st["conn_sent"] and not silent:
                    msgs.append(f"✅ <b>{name}</b> подключение восстановлено!")
                st["conn_sent"] = False
                st["conn_since"] = None
            elif quiet:
                st["conn_since"] = None
            else:
                if st["conn_since"] is None:
                    st["conn_since"] = now
                if not st["conn_sent"] and now - st["conn_since"] >= CONN_SEC and not silent:
                    msgs.append(f"⚠️ <b>{name}</b> — связь с терминалом потеряна!")
                    st["conn_sent"] = True

        # 3. баланс (от BAL_MIN долларов)
        bal_raw = M.first_num(info, ("balance",))
        if bal_raw is not None:
            usd = bal_raw * kb
            if st["bal"] is None:
                st["bal"] = usd
            else:
                diff = usd - st["bal"]
                if abs(diff) >= BAL_MIN:
                    if not silent:
                        icon = "💵" if diff > 0 else "💸"
                        arrow = "▲" if diff > 0 else "🔻"
                        msgs.append(f"{icon} <b>{fmt_amount(diff)}</b> {arrow} — баланс у {name}")
                    st["bal"] = usd

        # 4. просадка
        eq_raw = M.first_num(info, ("equity",))
        if bal_raw and bal_raw > 0 and eq_raw is not None:
            dd_abs = max(0.0, (bal_raw - eq_raw) / bal_raw * 100)
            new, event = dd_update(dd_abs, st["dd"])
            if event and not silent:
                arrow = "🔻" if event == "up" else "▲"
                msgs.append(f"⚔️ <b>-{dd_abs:.2f}%</b> {arrow} — уровень просадки у {name}")
            st["dd"] = new
    for m in msgs:
        send(m)
    return msgs


def worker():
    while True:
        try:
            if TG_TOKEN and TG_CHAT:
                check()
        except Exception:
            pass
        time.sleep(10)


def init(main_module, app):
    """Вызывается из main.py: подключает модуль сайта, ссылку /tg-test и фоновую проверку."""
    global M
    M = main_module

    @app.get("/tg-test", response_class=HTMLResponse)
    def tg_test(p: str = ""):
        head = '<meta charset="utf-8"><body style="font:15px Arial;padding:20px">'
        if M.ADMIN_PASS and p != M.ADMIN_PASS:
            return head + "Нужен пароль: /tg-test?p=ПАРОЛЬ"
        ok = send("✅ Проверка связи: бот FX Monitor подключён.")
        return head + ("Отправлено. Проверьте Telegram." if ok else "ОШИБКА: " + escape(status_text()))

    threading.Thread(target=worker, daemon=True).start()
