"""FX Monitor clone (Расширенный + Доходы). Диагностика: /debug"""
import os
import json
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI()
accounts_data = {}
last_seen = {}

PAGE_TITLE = os.environ.get("FX_TITLE", "Аккаунт 4zF")
API_KEY = os.environ.get("FX_API_KEY", "")
ADMIN_PASS = os.environ.get("FX_ADMIN_PASS", "")
CENT = os.environ.get("FX_CENT", "1") == "1"
TZ_HOURS = float(os.environ.get("FX_TZ", "3"))
SETTINGS_FILE = Path(os.environ.get("FX_SETTINGS", "settings.json"))
BRAND = "FX Monitor (10с)"
RATES = {"USD": 1.0, "EUR": 0.92, "RUB": 90.0, "UAH": 41.5}
try:
    RATES.update(json.loads(os.environ.get("FX_RATES", "{}")))
except Exception:
    pass
SYMS = {"USD": "$", "EUR": "€", "RUB": "₽", "UAH": "₴"}
GREEN_AT, YELLOW_AT = 1.0, 10.0

ORDER_KEYS = ("tot_orders", "total_orders", "orders_total", "orders", "positions", "open_orders")
PERIOD_KEYS = {
    "p_today": ("p_today", "p_day", "profit_today", "today"),
    "p_yesterday": ("p_yesterday", "profit_yesterday", "yesterday"),
    "p_week": ("p_week", "profit_week", "week"),
    "p_month": ("p_month", "profit_month", "month"),
    "p_prev_week": ("p_prev_week", "p_last_week", "prev_week", "last_week"),
    "p_prev_month": ("p_prev_month", "p_last_month", "prev_month", "last_month"),
}
DEP_KEYS = ("deposits", "deposit")
WD_KEYS = ("withdrawals", "withdrawal")

SETTINGS = {}
try:
    SETTINGS = json.loads(SETTINGS_FILE.read_text("utf-8"))
except Exception:
    SETTINGS = {}


def save_settings():
    try:
        SETTINGS_FILE.write_text(json.dumps(SETTINGS, ensure_ascii=False), "utf-8")
    except Exception:
        pass


def num(x, d=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else d
    except Exception:
        return d


def first_num(info, names):
    for n in names:
        v = info.get(n)
        if v is None or isinstance(v, (dict, list, bool)):
            continue
        try:
            f = float(v)
            if f == f and abs(f) != float("inf"):
                return f
        except Exception:
            pass
    return None


def fmt_money(v, cur):
    if v is None:
        return "—"
    if abs(v) < 0.005:
        v = 0.0
    return f"{SYMS.get(cur, '$')} {v:,.2f}"


def fmt_pct(v, plus=True, zero="0%"):
    if v is None:
        return "—"
    if abs(v) < 0.005:
        return zero
    return f"{'+' if plus and v > 0 else ''}{v:.2f}%"


def cls(v):
    return "" if v is None or abs(v) < 0.005 else ("pos" if v > 0 else "neg")


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


def login_sort_key(c):
    s = str(c["login"])
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def calc(login, info, cur):
    r = RATES.get(cur, 1.0)
    kb = 0.01 if CENT else 1.0
    S = SETTINGS.get(str(login), {})

    def usd(names):
        v = first_num(info, names)
        return None if v is None else v * kb

    bal_u = usd(("balance",)) or 0.0
    eq_u = usd(("equity",))
    if eq_u is None:
        eq_u = bal_u
    mg_u = usd(("margin",)) or 0.0
    bal, eq, mg = bal_u * r, eq_u * r, mg_u * r

    dep_u = S["deposits"] if "deposits" in S else usd(DEP_KEYS)
    wd_u = S["withdrawals"] if "withdrawals" in S else usd(WD_KEYS)
    known = dep_u is not None
    dep, wd = (dep_u or 0.0) * r, (wd_u or 0.0) * r

    per = {}
    for key, ck, pk in (("day", "p_today", "p_yesterday"), ("week", "p_week", "p_prev_week"),
                        ("month", "p_month", "p_prev_month")):
        cu, pu = usd(PERIOD_KEYS[ck]), usd(PERIOD_KEYS[pk])
        c = None if cu is None else cu * r
        p = None if pu is None else pu * r
        cc, pv = c or 0.0, p or 0.0
        bc, bp = bal - cc, bal - cc - pv
        per[key] = dict(c=c, p=p, bc=bc, bp=bp,
                        cp=None if c is None else (cc / bc * 100 if bc > 0 else 0.0),
                        pp=None if p is None else (pv / bp * 100 if bp > 0 else 0.0))

    total = (bal + wd - dep) if known else None
    tp = (total / dep * 100 if dep > 0 else 0.0) if known else None
    dd = min(0.0, eq - bal)
    ddp = dd / bal * 100 if bal > 0 else 0.0
    lvl = eq / mg * 100 if mg > 0 else None

    since = str(S.get("since") or info.get("since") or "")
    sd = parse_date(since)
    months = max((datetime.now() - sd).days / 30.4, 1.0) if sd else 0.0
    mp = first_num(info, ("monthly_pct",))
    if mp is not None:
        m = mp
    elif known and months > 0 and bal > 0:
        m = total / bal * 100 / months
    else:
        m = None
    dp = first_num(info, ("daily_pct",))
    d = dp if dp is not None else (m / 30.4 if m is not None else None)
    yp = first_num(info, ("yearly_pct",))
    if yp is not None:
        y = yp
    elif m is not None:
        y = ((1 + m / 100) ** 12 - 1) * 100 if m > -100 else -100.0
    else:
        y = None

    syms = []
    pairs = info.get("pairs") or {}
    if isinstance(pairs, dict):
        for key, v in pairs.items():
            if not isinstance(v, dict):
                continue
            nm = str(key).upper()
            short = nm[:6] if len(nm) > 6 and nm[:6].isalpha() else nm
            bc_, sc_ = int(num(v.get("buy_cnt"))), int(num(v.get("sell_cnt")))
            profit = num(v.get("profit")) * kb * r
            bid = v.get("bid")
            if bid is not None:
                dg = int(num(v.get("digits"), 5 if "JPY" not in short else 3))
                bid = f"{num(bid):.{dg}f}"
            syms.append(dict(name=short, buy=num(v.get("buy")), sell=num(v.get("sell")),
                             bc=bc_, sc=sc_, act=(bc_ + sc_) > 0,
                             pct=profit / bal * 100 if bal > 0 else 0.0, bid=bid))
    syms.sort(key=lambda s: (not s["act"], s["name"]))

    pair_cnt = sum(s["bc"] + s["sc"] for s in syms)
    orders = int(max(first_num(info, ORDER_KEYS) or 0, pair_cnt))
    bcol = {"green": "g", "red": "r", "yellow": "y"}.get(str(info.get("badge_color", "")).lower())
    if not bcol:
        bcol = "y" if int(num(info.get("sush_on"), 1)) == 1 else "g"

    auto_name = str(info.get("name") or info.get("label") or f"Счёт {login}")
    ts = last_seen.get(login, time.time())
    return dict(login=login, cur=cur, name=str(S.get("name") or auto_name), custom_name=str(S.get("name") or ""),
                auto_name=auto_name, since=since, custom_since=str(S.get("since") or ""),
                broker=str(info.get("company") or ""), ping=int(num(info.get("ping"))),
                bal=bal, eq=eq, dep=dep, wd=wd, known=known,
                dep_manual=S.get("deposits"), wd_manual=S.get("withdrawals"), dep_u=dep_u, wd_u=wd_u,
                per=per, total=total, tp=tp, dd=dd, ddp=ddp, lvl=lvl, d=d, m=m, y=y,
                roi=(wd / dep * 100) if known and dep > 0 else None,
                rom=((wd + eq) / dep * 100) if known and dep > 0 else None,
                syms=syms, orders=orders, bcol=bcol,
                time=str(info.get("time") or now_local().strftime("%d.%m.%Y | %H:%M:%S")),
                age=max(0, int(time.time() - ts)))


def attrs(c):
    def n(v):
        return "" if v is None else f"{v:.2f}"
    return (f'data-login="{escape(str(c["login"]))}" data-n="{escape(c["custom_name"])}" data-na="{escape(c["auto_name"])}" '
            f'data-s="{escape(c["custom_since"])}" data-sa="{escape(c["since"])}" '
            f'data-d="{n(c["dep_manual"])}" data-da="{n(c["dep_u"])}" data-w="{n(c["wd_manual"])}" data-wa="{n(c["wd_u"])}"')


def age_html(c):
    return (f'<span class="ag" data-age="{c["age"]}">{escape(BRAND)} | <span class="at"></span></span>')


def head_html(c):
    return (f'<span class="name ed" title="Нажмите, чтобы переименовать">{escape(c["name"])}</span> '
            f'<span class="badge {c["bcol"]}" title="Открыто ордеров">{c["orders"]}</span>')


def since_html(c):
    return f'работает с {escape(c["since"])}' if c["since"] else "&nbsp;"


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
    ddcls = {"g": "pos", "y": "yel", "r": "neg"}[tone(c["ddp"])]
    if c["lvl"] is None:
        lvl, lcls = "—", ""
    else:
        lvl, lcls = f"{c['lvl']:.0f}%", ("pos" if c["lvl"] >= 100 else "neg")

    def mini(label, v, p):
        return (f'<div class="mini"><i>{label}</i><span class="{cls(v)}">{fmt_money(v, cur)}</span>'
                f'{"" if v is None else " (" + fmt_pct(p) + ")"}</div>')

    dv = per["day"]["c"]
    big = f'{fmt_money(dv, cur)}' + ('' if dv is None else f' <small>({fmt_pct(per["day"]["cp"])})</small>')
    return f'''<div class="card" {attrs(c)}>
  <div class="h"><div>{head_html(c)}<div class="since">{since_html(c)}</div></div>
    <div class="dt">{escape(c["time"])}<span class="mi ed" title="Настройки счёта">☰</span></div></div>
  <div class="mid">
    <div class="lm">
      <div><div class="lb">просадка</div><div class="bigp {ddcls}">{c["ddp"]:.2f}%</div><div class="sub {ddcls}">{fmt_money(c["dd"], cur)}</div></div>
      <div><div class="lb">маржа</div><div class="bigp {lcls}">{lvl}</div></div>
    </div>
    <div class="day">
      <div class="big">{big}</div>
      {mini("вчера", per["day"]["p"], per["day"]["pp"])}{mini("неделя", per["week"]["c"], per["week"]["cp"])}{mini("месяц", per["month"]["c"], per["month"]["cp"])}
    </div>
  </div>
  <div class="bar"><div>{fmt_money(c["bal"], cur)}</div><div>{fmt_money(c["eq"], cur)}</div></div>
  <div class="tiles">{"".join(tile_html(s) for s in c["syms"])}</div>
  <div class="foot"><span class="br">{escape(c["broker"])}{f" ({c['ping']}мс)" if c["ping"] else ""}</span>{age_html(c)}</div>
</div>'''


def cellv(v, p, cur, plus, zero):
    if v is None:
        return "<b>—</b>"
    ptxt = "" if p is None else f" <em>({fmt_pct(p, plus, zero)})</em>"
    return f'<b class="{cls(v)}">{fmt_money(v, cur)}</b>{ptxt}'


def table_html(rows, cur, plus, zero_pct, total_v, total_p):
    names = {"day": "день", "week": "неделя", "month": "месяц"}
    h = '<table class="pt"><tr><th></th><th>текущий</th><th>прошлый</th></tr>'
    for k in ("day", "week", "month"):
        o = rows[k]
        h += (f'<tr><td>{names[k]}</td><td>{cellv(o["c"], o["cp"], cur, plus, zero_pct)}</td>'
              f'<td>{cellv(o["p"], o["pp"], cur, plus, zero_pct)}</td></tr>')
    h += f'<tr><td>всего</td><td>{cellv(total_v, total_p, cur, plus, zero_pct)}</td><td></td></tr></table>'
    return h


def income_card(c):
    cur = c["cur"]

    def pc(v, dec=2):
        if v is None:
            return "<b>—</b>"
        v = 0.0 if abs(v) < 0.005 else v
        return f'<b class="{cls(v)}">{v:.{dec}f}%</b>'

    def badge(kind, v):
        return f'<span class="{kind}">{kind.upper()} <b>{"—" if v is None else f"{v:.2f}%"}</b></span>'

    return f'''<div class="card" {attrs(c)}>
  <div class="ig">
    <div>{head_html(c)}</div><div class="r2 dt">{escape(c["time"])}<span class="mi ed" title="Настройки счёта">☰</span></div>
    <div class="since">{since_html(c)}</div><div class="r2 bal">{fmt_money(c["bal"], cur)}</div>
    <div>ежедневно {pc(c["d"])}</div><div class="r2"><span class="lb2">пополнения</span> <span class="lnk">{fmt_money(c["dep"] if c["known"] else None, cur)}</span></div>
    <div>ежемесячно {pc(c["m"])}</div><div class="r2"><span class="lb2">снятия</span> <span class="lnk">{fmt_money(c["wd"] if c["known"] else None, cur)}</span></div>
    <div>годовых {pc(c["y"], 0)}</div><div class="r2">{badge("roi", c["roi"])}</div>
    <div></div><div class="r2">{badge("rom", c["rom"])}</div>
  </div>
  {table_html(c["per"], cur, True, "0%", c["total"], c["tp"])}
  <div class="foot"><span></span>{age_html(c)}</div>
</div>'''


def total_card(cs, cur):
    rows = {}
    for k in ("day", "week", "month"):
        kc = [x for x in cs if x["per"][k]["c"] is not None]
        kp = [x for x in cs if x["per"][k]["p"] is not None]
        c = sum(x["per"][k]["c"] for x in kc) if kc else None
        p = sum(x["per"][k]["p"] for x in kp) if kp else None
        bc = sum(x["per"][k]["bc"] for x in kc if abs(x["per"][k]["c"]) >= 0.005)
        bp = sum(x["per"][k]["bp"] for x in kp if abs(x["per"][k]["p"]) >= 0.005)
        rows[k] = dict(c=c, p=p, cp=None if c is None else (c / bc * 100 if bc > 0 else 0.0),
                       pp=None if p is None else (p / bp * 100 if bp > 0 else 0.0))
    bal = sum(x["bal"] for x in cs)
    kn = [x for x in cs if x["known"]]
    dep = sum(x["dep"] for x in kn)
    tot = sum(x["total"] for x in kn) if kn else None
    tp = None if tot is None else (tot / dep * 100 if dep > 0 else 0.0)
    return (f'<div class="card tot"><div class="ttl"><b>Общий баланс</b><span class="bal">{fmt_money(bal, cur)}</span></div>'
            f'{table_html(rows, cur, False, "0.00%", tot, tp)}</div>')


def render_body(view, cur):
    if not accounts_data:
        return '<div class="empty">Ожидание данных от MT5… (POST /api/update)</div>'
    cs = [calc(login, info, cur) for login, info in list(accounts_data.items())]
    cs.sort(key=login_sort_key)
    if view == "income":
        return (f'<div class="grid">{total_card(cs, cur)}</div>'
                f'<div class="grid" style="margin-top:30px">{"".join(income_card(c) for c in cs)}</div>'
                f'<div class="beta">Доходы Beta-2</div>')
    return f'<div class="grid">{"".join(pro_card(c) for c in cs)}</div>'


def norm_view(v):
    return "income" if str(v).lower() in ("income", "inc", "dohody", "доходы") else "pro"


def norm_cur(c):
    c = str(c or "USD").upper()
    return c if c in RATES else "USD"


@app.post("/api/update")
async def update_account(request: Request):
    try:
        raw = (await request.body()).decode("utf-8-sig", "ignore").replace("\x00", "").strip()
        data = json.loads(raw)
        if API_KEY and data.get("key") != API_KEY and request.headers.get("x-api-key") != API_KEY:
            return JSONResponse({"status": "error", "detail": "bad key"}, status_code=403)
        login = data.get("login")
        if login is None:
            return {"status": "error", "detail": "no login"}
        accounts_data[login] = data
        last_seen[login] = time.time()
        return {"status": "success"}
    except Exception:
        return {"status": "error"}


@app.get("/api/data")
def api_data():
    return accounts_data


@app.get("/api/settings")
def get_settings():
    return SETTINGS


@app.post("/api/settings")
async def set_settings(request: Request):
    try:
        data = json.loads((await request.body()).decode("utf-8-sig", "ignore"))
        if ADMIN_PASS and str(data.get("pass", "")) != ADMIN_PASS:
            return JSONResponse({"status": "error", "detail": "bad pass"}, status_code=403)
        login = str(data.get("login", "")).strip()
        if not login:
            return {"status": "error"}
        s = {}
        for key in ("name", "since"):
            v = str(data.get(key) or "").strip()
            if v:
                s[key] = v[:60]
        for key in ("deposits", "withdrawals"):
            v = str(data.get(key) if data.get(key) is not None else "").strip()
            v = v.replace(",", ".").replace(" ", "").replace("$", "")
            if v:
                try:
                    s[key] = float(v)
                except Exception:
                    pass
        if s:
            SETTINGS[login] = s
        else:
            SETTINGS.pop(login, None)
        save_settings()
        return {"status": "success"}
    except Exception:
        return {"status": "error"}


@app.get("/debug", response_class=HTMLResponse)
def debug():
    checks = [("balance", ("balance",)), ("equity", ("equity",)), ("margin", ("margin",)),
              ("ордера (tot_orders)", ORDER_KEYS)]
    checks += [(k, v) for k, v in PERIOD_KEYS.items()]
    checks += [("deposits", DEP_KEYS), ("withdrawals", WD_KEYS)]
    out = ['<meta charset="utf-8"><body style="font:14px Arial;padding:16px;background:#f4f6fa"><h2>Диагностика: что прислал робот</h2>']
    if not accounts_data:
        out.append("<p>Робот пока ничего не прислал.</p>")
    for login, info in accounts_data.items():
        age = int(time.time() - last_seen.get(login, time.time()))
        out.append(f"<h3>Счёт {escape(str(login))} — пакет {age} сек. назад</h3>"
                   "<table border=1 cellpadding=5 style='border-collapse:collapse;background:#fff'>")
        for title, names in checks:
            v = first_num(info, names)
            color = "#1a9c55" if v is not None else "#d01040"
            text = f"OK: {v}" if v is not None else "НЕТ ДАННЫХ"
            out.append(f"<tr><td>{escape(title)}</td><td style='color:{color}'>{text}</td></tr>")
        pairs = info.get("pairs")
        pc = len(pairs) if isinstance(pairs, dict) else 0
        color = "#1a9c55" if pc else "#d01040"
        out.append(f"<tr><td>pairs (пары)</td><td style='color:{color}'>{pc} шт.</td></tr></table>")
        out.append(f"<p style='color:#555'>Все поля в пакете: {escape(', '.join(map(str, info.keys())))}</p>")
    out.append("</body>")
    return "".join(out)


@app.get("/fragment", response_class=HTMLResponse)
def fragment(view: str = "pro", cur: str = "USD"):
    return render_body(norm_view(view), norm_cur(cur))


@app.get("/", response_class=HTMLResponse)
@app.get("/u/{user}", response_class=HTMLResponse)
def home(user: str = "", view: str = "pro", cur: str = "USD"):
    v, c = norm_view(view), norm_cur(cur)
    return (PAGE.replace("__TITLE__", escape(PAGE_TITLE)).replace("__VIEW__", v)
            .replace("__CUR__", c).replace("__BODY__", render_body(v, c)))


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--green:#28c76f;--red:#dc1e4b;--blue:#3d5fd6;--yellow:#e0a800}
*{box-sizing:border-box}
body{margin:0;font:13px/1.35 "Open Sans","Segoe UI",Roboto,Arial,sans-serif;color:#2b2f36;
  background:linear-gradient(135deg,#e2eaf2,#d5dfea);min-height:100vh}
.wrap{padding:8px 8px 30px}
.top,.top2{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;flex-wrap:wrap}
.top2{margin-top:8px}
h1{margin:0;font-size:20px;font-weight:700;color:#444;display:flex;align-items:center;gap:8px}
h1 svg{width:20px;height:20px;fill:#444}
.btn{border:0;border-radius:4px;color:#fff;cursor:pointer;width:38px;height:32px;display:inline-flex;align-items:center;justify-content:center;vertical-align:top}
.btn svg{width:15px;height:15px;fill:none;stroke:#fff;stroke-width:2}
.b-g{background:#2ecc71}.b-d{background:#2f3338;margin-left:8px}
.spin svg{animation:sp .8s linear}
@keyframes sp{to{transform:rotate(360deg)}}
.dd{position:relative;display:flex;align-items:center;gap:8px}
.ddbtn{background:#1d3a78;color:#fff;border:0;border-radius:3px;padding:8px 14px;font-weight:600;cursor:pointer;font-size:13px;font-family:inherit}
.ddbtn:after{content:"";display:inline-block;margin-left:8px;border:4px solid transparent;border-top-color:#fff;vertical-align:-2px}
.ddm{display:none;position:absolute;top:36px;left:0;background:#fff;border-radius:3px;box-shadow:0 3px 12px rgba(0,0,0,.25);z-index:9;min-width:150px}
.ddm.open{display:block}
.ddm a{display:block;padding:8px 14px;color:#222;cursor:pointer}
.ddm a:hover{background:#eef2fb}
.new{background:#1ea7fd;color:#fff;padding:7px 10px;border-radius:3px;font-weight:600}
.cur{display:flex;border:1px solid #3f7cf0;border-radius:3px;overflow:hidden;background:#fff;height:32px}
.cur button{border:0;border-left:1px solid #3f7cf0;background:#fff;color:#3f7cf0;width:31px;cursor:pointer;font-size:12px;font-weight:700}
.cur button:first-child{border-left:0}
.cur button.on{background:#3f7cf0;color:#fff}
.cur svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,440px),1fr));gap:30px;margin:16px 0 0}
.card{background:#fff;border-radius:3px;box-shadow:0 1px 4px rgba(40,60,90,.25);padding:14px 16px 8px;position:relative}
.name{font-weight:700;font-size:13px;color:#222}
.ed{cursor:pointer}
.name.ed:hover{text-decoration:underline dotted}
.badge{display:inline-block;min-width:22px;padding:0 6px;margin-left:4px;border-radius:12px;color:#fff;font-weight:600;font-size:12px;text-align:center}
.g{background:var(--green)}.r{background:var(--red)}.y{background:#f6b90f}
.since{color:#aaa;font-size:11px}
.dt{color:#888;font-size:10.5px;text-align:right}
.mi{color:#888;font-size:13px;display:block;text-align:right;line-height:1}
.pos{color:var(--green)}.neg{color:var(--red)}.yel{color:var(--yellow)}
.h{display:flex;justify-content:space-between}
.mid{display:flex;justify-content:space-between;margin-top:2px;gap:8px}
.lm{display:flex;gap:16px}.lm .lb{color:#999;font-size:13px}
.bigp{font-size:25px;font-weight:600;line-height:1.15}
.sub{font-size:12px}
.day{text-align:right}
.day .big{font-size:24px;color:#222;line-height:1.1;white-space:nowrap}
.day .big small{font-size:18px;color:#666}
.mini{font-size:11.5px;color:#444;white-space:nowrap}.mini i{font-style:normal;color:#999;font-size:10px;margin-right:3px}
.bar{display:flex;height:31px;margin-top:6px;color:#fff;font-weight:700;font-size:16px}
.bar div{flex:1;display:flex;align-items:center;justify-content:center;white-space:nowrap;overflow:hidden}
.bar div:first-child{background:#4169e1}.bar div:last-child{background:#1aa7ff}
.tiles{display:flex;flex-wrap:wrap;gap:3px;margin-top:10px;min-height:20px}
.t{width:66px;text-align:center;color:#fff;background:#3dc47e;border-radius:1px;overflow:hidden}
.t.y{background:#f4b32a}.t.r{background:var(--red)}.t.n{background:#ececec;color:#333}
.t .s{color:#1e2226;font-weight:700;font-size:11px;line-height:1.2;padding:4px 0 3px}
.t .p{background:#33383e;color:#fff;font-size:11px;font-weight:600;line-height:1.3;padding:1px 0;margin:0 2px}
.t .v{font-size:15px;font-weight:700;line-height:1.2;padding:5px 0 3px;white-space:nowrap;letter-spacing:-.2px}
.t .l{font-size:10.5px;font-weight:600;line-height:1.35;padding:3px 0 4px;background:rgba(0,0,0,.09);white-space:nowrap}
.t.n .s{color:#222}.t.n .v{color:#222}.t.n .l{color:#555;background:transparent}
.foot{display:flex;justify-content:space-between;margin-top:8px;font-size:9.5px}
.foot .br{color:#999}.foot .ag{color:#5fd39a}.foot .ag.stale{color:var(--red)}
.tot{background:linear-gradient(180deg,#adc3f3 0%,#dde8f8 45%,#d9f6e8 100%);padding-bottom:12px}
.tot .ttl{display:flex;justify-content:space-between;align-items:center;margin:6px 0 10px}
.tot .ttl b{font-size:14px;text-transform:uppercase}
.bal{font-size:18px;font-weight:600;color:var(--blue)}
.ig{display:grid;grid-template-columns:1fr auto;column-gap:10px;row-gap:1px;align-items:center}
.ig .r2{text-align:right}
.lnk{color:var(--blue)}
.lb2{color:#888;font-size:13px}
.roi,.rom{display:inline-block;padding:0 6px;margin-top:1px;font-size:13px;color:#222;border-radius:2px}
.roi{background:linear-gradient(90deg,#8bf0b5,#3fd48a)}
.rom{background:linear-gradient(90deg,#73e6f6,#4a9df8)}
.roi b,.rom b{font-weight:700}
table.pt{width:100%;border-collapse:collapse;margin-top:10px}
.pt th{font-weight:400;color:#888;text-align:right;padding:1px 0}
.pt td{text-align:right;padding:2px 0;border-top:1px solid #d5dbe4;white-space:nowrap}
.pt td:first-child,.pt th:first-child{text-align:left;color:#888;width:20%}
.pt td b{font-weight:700;color:#222}
.pt td b.pos{color:var(--green)}.pt td b.neg{color:var(--red)}
.pt td em{font-style:normal;color:#444}
.beta{margin:26px 0 0;font-size:11px;color:#3f7cf0}
.empty{margin:40px 8px;color:#777}
.mdl{display:none;position:fixed;inset:0;background:rgba(20,30,50,.45);z-index:50;align-items:center;justify-content:center}
.mdl.open{display:flex}
.mbox{background:#fff;border-radius:4px;padding:18px 20px;width:min(92vw,360px);box-shadow:0 8px 30px rgba(0,0,0,.35)}
.mbox h3{margin:0 0 6px;font-size:15px}
.mbox label{display:block;color:#666;font-size:12px;margin-top:9px}
.mbox input{width:100%;padding:7px 9px;border:1px solid #c5cedd;border-radius:3px;font-size:14px;margin-top:3px;font-family:inherit}
.mbtn{display:flex;gap:8px;margin-top:14px}
.mbtn button{flex:1;padding:9px;border:0;border-radius:3px;cursor:pointer;font-weight:600;font-family:inherit}
#m_save{background:#1d3a78;color:#fff}#m_cancel{background:#e6ebf3}
.mhint{color:#999;font-size:11px;margin-top:8px}
</style></head><body><div class="wrap">
<div class="top">
  <h1><svg viewBox="0 0 24 24"><path d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2c-4 0-8 2-8 5v3h16v-3c0-3-4-5-8-5z"/></svg>__TITLE__</h1>
  <div><button class="btn b-g" id="rf" title="Обновить"><svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7M21 3v6h-6"/></svg></button><button class="btn b-d" id="fs" title="Полный экран"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button></div>
</div>
<div class="top2">
  <div class="dd"><button class="ddbtn" id="ddb">Расширенный</button><span class="new" id="newb">new</span>
    <div class="ddm" id="ddm"><a data-v="pro">Расширенный</a><a data-v="income">Доходы</a></div></div>
  <div class="cur" id="cur"></div>
</div>
<div id="app">__BODY__</div>
</div>
<div class="mdl" id="mdl"><div class="mbox">
  <h3>Настройки счёта <span id="mlog"></span></h3>
  <label>Название<input id="f_name"></label>
  <label>Работает с (дд.мм.гггг)<input id="f_since"></label>
  <label>Пополнения, $ (в долларах)<input id="f_dep" inputmode="decimal"></label>
  <label>Снятия, $ (в долларах)<input id="f_wd" inputmode="decimal"></label>
  <div class="mbtn"><button id="m_save">Сохранить</button><button id="m_cancel">Отмена</button></div>
  <div class="mhint">Пустое поле = брать данные от робота автоматически</div>
</div></div>
<script>
let VIEW="__VIEW__", CUR="__CUR__", EDIT=null;
const q=new URLSearchParams(location.search);
if(!q.get('cur')&&localStorage.getItem('fxcur'))CUR=localStorage.getItem('fxcur');
const CURS=[['USD','<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/></svg>'],['USD','$'],['EUR','€'],['RUB','₽'],['UAH','₴']];
const $=id=>document.getElementById(id);
function drawCur(){
  $('cur').innerHTML=CURS.map(([k,l],i)=>`<button data-c="${k}" class="${(CUR===k&&i>0)||(CUR==='USD'&&i===0)?'on':''}">${l}</button>`).join('');
  $('cur').querySelectorAll('button').forEach(b=>b.onclick=()=>{CUR=b.dataset.c;localStorage.setItem('fxcur',CUR);sync();drawCur();load();});
}
function sync(){
  $('ddb').textContent=VIEW==='pro'?'Расширенный':'Доходы';
  $('newb').style.display=VIEW==='pro'?'':'none';
  const u=new URL(location);u.searchParams.set('view',VIEW);u.searchParams.set('cur',CUR);history.replaceState(null,'',u);
}
function stamp(){document.querySelectorAll('.ag').forEach(e=>e.dataset.base=Date.now());tick();}
function tick(){document.querySelectorAll('.ag').forEach(e=>{
  const s=Math.round(+e.dataset.age+(Date.now()-(+e.dataset.base||Date.now()))/1000);
  e.querySelector('.at').textContent=s<60?s+' сек. назад':s<3600?Math.floor(s/60)+' мин. назад':Math.floor(s/3600)+' ч. назад';
  e.classList.toggle('stale',s>60);});}
async function load(){
  $('rf').classList.add('spin');setTimeout(()=>$('rf').classList.remove('spin'),800);
  try{const r=await fetch('/fragment?view='+VIEW+'&cur='+CUR,{cache:'no-store'});
    if(r.ok){$('app').innerHTML=await r.text();stamp();}}catch(e){}
}
async function saveSettings(p){
  p.pass=sessionStorage.getItem('fxpass')||'';
  try{
    const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
    if(r.status===403){const w=prompt('Пароль на изменение настроек:');if(w){sessionStorage.setItem('fxpass',w);return saveSettings(p);}return false;}
    const j=await r.json();return j.status==='success';
  }catch(e){return false;}
}
document.addEventListener('click',e=>{
  const t=e.target.closest('.ed');if(!t)return;
  const c=t.closest('[data-login]');if(!c)return;
  const d=c.dataset;EDIT=d.login;
  $('mlog').textContent='#'+EDIT;
  $('f_name').value=d.n||'';$('f_name').placeholder=d.na||'';
  $('f_since').value=d.s||'';$('f_since').placeholder=d.sa||'например 15.11.2024';
  $('f_dep').value=d.d||'';$('f_dep').placeholder=d.da?('авто: '+d.da):'не задано';
  $('f_wd').value=d.w||'';$('f_wd').placeholder=d.wa?('авто: '+d.wa):'не задано';
  $('mdl').classList.add('open');$('f_name').focus();
});
$('m_cancel').onclick=()=>$('mdl').classList.remove('open');
$('mdl').addEventListener('click',e=>{if(e.target===$('mdl'))$('mdl').classList.remove('open');});
$('m_save').onclick=async()=>{
  const p={login:EDIT,name:$('f_name').value,since:$('f_since').value,deposits:$('f_dep').value,withdrawals:$('f_wd').value};
  if(await saveSettings(Object.assign({},p))){
    if(p.name||p.since||p.deposits||p.withdrawals)localStorage.setItem('fxset_'+EDIT,JSON.stringify(p));
    else localStorage.removeItem('fxset_'+EDIT);
    $('mdl').classList.remove('open');load();
  }else alert('Не удалось сохранить');
};
async function restore(){
  try{
    const s=await (await fetch('/api/settings',{cache:'no-store'})).json();let ch=false;
    for(let i=0;i<localStorage.length;i++){
      const k=localStorage.key(i);if(!k||!k.startsWith('fxset_'))continue;
      const login=k.slice(6);if(s[login])continue;
      const p=JSON.parse(localStorage.getItem(k));p.login=login;
      if(await saveSettings(p))ch=true;
    }
    if(ch)load();
  }catch(e){}
}
$('ddb').onclick=e=>{e.stopPropagation();$('ddm').classList.toggle('open');};
document.querySelectorAll('#ddm a').forEach(a=>a.onclick=()=>{VIEW=a.dataset.v;sync();load();});
document.addEventListener('click',()=>$('ddm').classList.remove('open'));
$('rf').onclick=load;
$('fs').onclick=()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();
drawCur();sync();stamp();restore();setInterval(tick,1000);setInterval(load,3000);
if(CUR!=='__CUR__')load();
</script></body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
