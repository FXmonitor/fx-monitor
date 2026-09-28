"""
FX Monitor clone: две вкладки — «Расширенный» (view=pro) и «Доходы» (view=income).
Робот MT5 шлёт JSON на POST /api/update. Формат полей — как в вашем старом main.py.
Запуск: python main.py  (порт берётся из переменной PORT)
"""
import os
import json
import time
from datetime import datetime, timedelta
from html import escape

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()
accounts_data = {}   # login -> последний JSON от робота
last_seen = {}       # login -> unix-время последнего пакета

# ============================ НАСТРОЙКИ ============================
PAGE_TITLE = os.environ.get("FX_TITLE", "Аккаунт 4zF")
API_KEY = os.environ.get("FX_API_KEY", "")            # пусто = без проверки ключа
CENT = os.environ.get("FX_CENT", "1") == "1"          # робот шлёт центы -> делим на 100
TZ_HOURS = float(os.environ.get("FX_TZ", "3"))        # часовой пояс для даты в карточке
BRAND = "FX Monitor (10с)"
RATES = {"USD": 1.0, "EUR": 0.92, "RUB": 90.0, "UAH": 41.5}   # курсы к USD (правьте вручную)
try:
    RATES.update(json.loads(os.environ.get("FX_RATES", "{}")))
except Exception:
    pass
SYMS = {"USD": "$", "EUR": "€", "RUB": "₽", "UAH": "₴"}
GREEN_AT, YELLOW_AT = 2.0, 10.0   # просадка до 2% — зелёный, до 10% — жёлтый, дальше красный

# Данные, которых нет в пакете робота (в ДОЛЛАРАХ). Если робот пришлёт поля
# deposits / withdrawals / p_prev_week / p_prev_month / name / since — они главнее.
DEFAULT_META = {
    "name": "KRYSTAL (CLASSIC +)",
    "since": "26.11.2024",
    "deposits": 3101.90,
    "withdrawals": 2800.00,
    "prev_week": 6.08,
    "prev_month": 40.55,
}
# Индивидуально по счетам (номер счёта берите на странице /api/data), пример:
# ACCOUNT_META = {"12345678": {"name": "KING+", "since": "15.11.2024", "deposits": 4659,
#                              "withdrawals": 1601, "prev_week": 0, "prev_month": 0, "order": 2}}
ACCOUNT_META = {}


# ============================ ХЕЛПЕРЫ ============================
def num(x, d=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else d
    except Exception:
        return d


def fmt_money(v, cur):
    if abs(v) < 0.005:
        v = 0.0
    return f"{SYMS.get(cur, '$')} {v:,.2f}"


def fmt_pct(v, plus=True, zero="0%"):
    if abs(v) < 0.005:
        return zero
    return f"{'+' if plus and v > 0 else ''}{v:.2f}%"


def cls(v):
    return "" if abs(v) < 0.005 else ("pos" if v > 0 else "neg")


def tone(p):
    d = -p if p < 0 else 0.0
    return "g" if d <= GREEN_AT else ("y" if d <= YELLOW_AT else "r")


def parse_date(s):
    for f in ("%d.%m.%Y", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(str(s)[:10], f)
        except Exception:
            pass
    return None


def lots(x):
    return "0" if abs(x) < 0.005 else f"{x:.2f}"


def now_local():
    return datetime.utcnow() + timedelta(hours=TZ_HOURS)


# ============================ РАСЧЁТЫ ============================
def calc(login, info, cur):
    r = RATES.get(cur, 1.0)
    k = (0.01 if CENT else 1.0) * r
    meta = {**DEFAULT_META, **ACCOUNT_META.get(str(login), {})}

    def has(key):
        return info.get(key) is not None

    def cash(key, default=0.0):          # default — в долларах
        return num(info[key]) * k if has(key) else num(default) * r

    bal = cash("balance")
    eq = cash("equity") if has("equity") else bal
    mg = cash("margin")
    dep = cash("deposits", meta.get("deposits", 0))
    wd = cash("withdrawals", meta.get("withdrawals", 0))
    cur_v = {"day": cash("p_today"), "week": cash("p_week"), "month": cash("p_month")}
    prev_v = {"day": cash("p_yesterday"),
              "week": cash("p_prev_week", meta.get("prev_week", 0)),
              "month": cash("p_prev_month", meta.get("prev_month", 0))}
    per = {}
    for key in ("day", "week", "month"):
        c, p = cur_v[key], prev_v[key]
        bc, bp = bal - c, bal - c - p
        per[key] = dict(c=c, p=p, bc=bc, bp=bp,
                        cp=c / bc * 100 if bc > 0 else 0.0,
                        pp=p / bp * 100 if bp > 0 else 0.0)

    total = bal + wd - dep
    tp = total / dep * 100 if dep > 0 else 0.0
    dd = min(0.0, eq - bal)
    ddp = dd / bal * 100 if bal > 0 else 0.0
    lvl = eq / mg * 100 if mg > 0 else None

    since = str(info.get("since") or meta.get("since") or "")
    sd = parse_date(since)
    months = max((datetime.now() - sd).days / 30.4, 1.0) if sd else 0.0
    if has("monthly_pct"):
        m = num(info["monthly_pct"])
    else:
        m = total / bal * 100 / months if (bal > 0 and months > 0) else 0.0
    d = num(info["daily_pct"]) if has("daily_pct") else m / 30.4
    if has("yearly_pct"):
        y = num(info["yearly_pct"])
    else:
        y = ((1 + m / 100) ** 12 - 1) * 100 if m > -100 else -100.0

    syms = []
    pairs = info.get("pairs") or {}
    if isinstance(pairs, dict):
        for key, v in pairs.items():
            if not isinstance(v, dict):
                continue
            nm = str(key).upper()
            short = nm[:6] if len(nm) > 6 and nm[:6].isalpha() else nm
            bc_, sc_ = int(num(v.get("buy_cnt"))), int(num(v.get("sell_cnt")))
            profit = num(v.get("profit")) * k
            bid = v.get("bid")
            if bid is not None:
                dg = int(num(v.get("digits"), 5 if "JPY" not in short else 3))
                bid = f"{num(bid):.{dg}f}"
            syms.append(dict(name=short, buy=num(v.get("buy")), sell=num(v.get("sell")),
                             bc=bc_, sc=sc_, act=(bc_ + sc_) > 0,
                             pct=profit / bal * 100 if bal > 0 else 0.0, bid=bid))
    syms.sort(key=lambda s: (not s["act"], s["name"]))

    orders = int(num(info.get("tot_orders"))) or sum(s["bc"] + s["sc"] for s in syms)
    bcol = {"green": "g", "red": "r", "yellow": "y"}.get(str(info.get("badge_color", "")).lower())
    if not bcol:
        bcol = "y" if int(num(info.get("sush_on"), 1)) == 1 else "g"

    ts = last_seen.get(login, time.time())
    return dict(login=login, cur=cur, name=str(info.get("name") or meta.get("name") or f"#{login}"),
                since=since, order=num(meta.get("order"), 0), broker=str(info.get("company") or ""),
                ping=int(num(info.get("ping"))), bal=bal, eq=eq, dep=dep, wd=wd, per=per,
                total=total, tp=tp, dd=dd, ddp=ddp, lvl=lvl, d=d, m=m, y=y,
                roi=wd / dep * 100 if dep > 0 else 0.0,
                rom=(wd + eq) / dep * 100 if dep > 0 else 0.0,
                syms=syms, orders=orders, bcol=bcol,
                time=str(info.get("time") or now_local().strftime("%d.%m.%Y | %H:%M:%S")),
                age=max(0, int(time.time() - ts)))


# ============================ РЕНДЕР КАРТОЧЕК ============================
def age_html(c):
    return (f'<span class="ag" data-age="{c["age"]}">{escape(BRAND)} | '
            f'<span class="at"></span></span>')


def head_html(c):
    return (f'<span class="name">{escape(c["name"])}</span> '
            f'<span class="badge {c["bcol"]}">{c["orders"]}</span>')


def tile_html(s):
    if not s["act"]:
        t, pct = "n", "0%"
    else:
        t = tone(s["pct"])
        pct = "0%" if abs(s["pct"]) < 0.005 else f"{s['pct']:.2f}%"
    bid = f'<div class="p">{s["bid"]}</div>' if s["bid"] else ""
    return (f'<div class="t {t}"><div class="s">{escape(s["name"])}</div>{bid}'
            f'<div class="v">{pct}</div>'
            f'<div class="l">▲{lots(s["buy"])} /{s["bc"]}<br>▼{lots(s["sell"])} /{s["sc"]}</div></div>')


def pro_card(c):
    cur, per = c["cur"], c["per"]
    t = tone(c["ddp"])
    ddcls = {"g": "pos", "y": "yel", "r": "neg"}[t]
    if c["lvl"] is None:
        lvl, lcls = "—", ""
    else:
        lvl, lcls = f"{c['lvl']:.0f}%", ("pos" if c["lvl"] >= 100 else "neg")

    def mini(label, o):
        return (f'<div class="mini"><i>{label}</i><span class="{cls(o["c"] if label != "вчера" else o["p"])}">'
                f'{fmt_money(o["c"] if label != "вчера" else o["p"], cur)}</span> '
                f'({fmt_pct(o["cp"] if label != "вчера" else o["pp"])})</div>')

    tot = c["bal"] + c["eq"]
    wa = min(75.0, max(25.0, c["bal"] / tot * 100)) if tot > 0 else 50.0
    return f'''<div class="card">
  <div class="h"><div>            
