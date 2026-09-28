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
  <div class="h"><div>{head_html(c)}<div class="since">работает с {escape(c["since"])}</div></div>
    <div class="dt">{escape(c["time"])}<span class="mi">☰</span></div></div>
  <div class="mid">
    <div class="lm">
      <div><div class="lb">просадка</div><div class="bigp {ddcls}">{c["ddp"]:.2f}%</div><div class="sub {ddcls}">{fmt_money(c["dd"], cur)}</div></div>
      <div><div class="lb">маржа</div><div class="bigp {lcls}">{lvl}</div></div>
    </div>
    <div class="day">
      <div class="big">{fmt_money(per["day"]["c"], cur)} <small>({fmt_pct(per["day"]["cp"])})</small></div>
      {mini("вчера", per["day"])}{mini("неделя", per["week"])}{mini("месяц", per["month"])}
    </div>
  </div>
  <div class="bar"><div class="a" style="width:{wa:.1f}%">{fmt_money(c["bal"], cur)}</div><div class="b">{fmt_money(c["eq"], cur)}</div></div>
  <div class="tiles">{"".join(tile_html(s) for s in c["syms"])}</div>
  <div class="foot"><span class="br">{escape(c["broker"])}{f" ({c['ping']}мс)" if c["ping"] else ""}</span>{age_html(c)}</div>
</div>'''


def table_html(rows, cur, plus, zero_pct, total_v, total_p):
    def cell(v, p):
        return f'<b class="{cls(v)}">{fmt_money(v, cur)}</b> <em>({fmt_pct(p, plus, zero_pct)})</em>'
    names = {"day": "день", "week": "неделя", "month": "месяц"}
    h = '<table class="pt"><tr><th></th><th>текущий</th><th>прошлый</th></tr>'
    for k in ("day", "week", "month"):
        o = rows[k]
        h += f'<tr><td>{names[k]}</td><td>{cell(o["c"], o["cp"])}</td><td>{cell(o["p"], o["pp"])}</td></tr>'
    h += f'<tr><td>всего</td><td>{cell(total_v, total_p)}</td><td></td></tr></table>'
    return h


def income_card(c):
    cur = c["cur"]

    def pc(v, dec=2):
        v = 0.0 if abs(v) < 0.005 else v
        return f'<b class="{cls(v)}">{v:.{dec}f}%</b>'

    return f'''<div class="card">
  <div class="ig">
    <div>{head_html(c)}</div><div class="r2 dt">{escape(c["time"])}<span class="mi">☰</span></div>
    <div class="since">работает с {escape(c["since"])}</div><div class="r2 bal">{fmt_money(c["bal"], cur)}</div>
    <div>ежедневно {pc(c["d"])}</div><div class="r2"><span class="lb2">пополнения</span> <span class="lnk">{fmt_money(c["dep"], cur)}</span></div>
    <div>ежемесячно {pc(c["m"])}</div><div class="r2"><span class="lb2">снятия</span> <span class="lnk">{fmt_money(c["wd"], cur)}</span></div>
    <div>годовых {pc(c["y"], 0)}</div><div class="r2"><span class="roi">ROI <b>{c["roi"]:.2f}%</b></span></div>
    <div></div><div class="r2"><span class="rom">ROM <b>{c["rom"]:.2f}%</b></span></div>
  </div>
  {table_html(c["per"], cur, True, "0%", c["total"], c["tp"])}
  <div class="foot"><span></span>{age_html(c)}</div>
</div>'''


def total_card(cs, cur):
    rows = {}
    for k in ("day", "week", "month"):
        c = sum(x["per"][k]["c"] for x in cs)
        p = sum(x["per"][k]["p"] for x in cs)
        bc = sum(x["per"][k]["bc"] for x in cs if abs(x["per"][k]["c"]) >= 0.005)
        bp = sum(x["per"][k]["bp"] for x in cs if abs(x["per"][k]["p"]) >= 0.005)
        rows[k] = dict(c=c, p=p, cp=c / bc * 100 if bc > 0 else 0.0, pp=p / bp * 100 if bp > 0 else 0.0)
    bal = sum(x["bal"] for x in cs)
    dep = sum(x["dep"] for x in cs)
    tot = sum(x["total"] for x in cs)
    return (f'<div class="card tot"><div class="ttl"><b>Общий баланс</b><span class="bal">{fmt_money(bal, cur)}</span></div>'
            f'{table_html(rows, cur, False, "0.00%", tot, tot / dep * 100 if dep > 0 else 0.0)}</div>')


def render_body(view, cur):
    if not accounts_data:
        return '<div class="empty">Ожидание данных от MT5… (POST /api/update)</div>'
    cs = [calc(login, info, cur) for login, info in list(accounts_data.items())]
    cs.sort(key=lambda c: (c["order"], c["name"], str(c["login"])))
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


# ============================ API ============================
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


@app.get("/fragment", response_class=HTMLResponse)
def fragment(view: str = "pro", cur: str = "USD"):
    return render_body(norm_view(view), norm_cur(cur))


@app.get("/", response_class=HTMLResponse)
@app.get("/u/{user}", response_class=HTMLResponse)
def home(user: str = "", view: str = "pro", cur: str = "USD"):
    v, c = norm_view(view), norm_cur(cur)
    return (PAGE.replace("__TITLE__", escape(PAGE_TITLE)).replace("__VIEW__", v)
            .replace("__CUR__", c).replace("__BODY__", render_body(v, c)))


# ============================ СТРАНИЦА ============================
PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--green:#28c76f;--red:#dc1e4b;--blue:#3d5fd6;--yellow:#e0a800}
*{box-sizing:border-box}
body{margin:0;font:13px/1.35 "Segoe UI","Open Sans",Roboto,Arial,sans-serif;color:#2b2f36;
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
.ddbtn{background:#1d3a78;color:#fff;border:0;border-radius:3px;padding:8px 14px;font-weight:600;cursor:pointer;font-size:13px}
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
.badge{display:inline-block;min-width:22px;padding:0 6px;margin-left:4px;border-radius:12px;color:#fff;font-weight:600;font-size:12px;text-align:center}
.g{background:var(--green)}.r{background:var(--red)}.y{background:#f6b90f}
.since{color:#aaa;font-size:11px}
.dt{color:#888;font-size:10.5px;text-align:right}
.mi{color:#888;font-size:11px;display:block;text-align:right;line-height:1}
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
.bar div{display:flex;align-items:center;justify-content:center;white-space:nowrap;overflow:hidden}
.bar .a{background:#4169e1}.bar .b{background:#1aa7ff;flex:1}
.tiles{display:flex;flex-wrap:wrap;gap:3px;margin-top:10px;min-height:20px}
.t{width:64px;text-align:center;color:#fff;background:#3ec27b}
.t.y{background:#f6b90f}.t.r{background:var(--red)}.t.n{background:#eee;color:#333}
.t .s{color:#1b1b1b;font-weight:700;font-size:10px;padding:2px 0}
.t .p{background:#3a3f45;color:#fff;font-size:10.5px;padding:1px 0;margin:0 1px}
.t .v{font-size:13px;font-weight:700;padding:3px 0 1px}
.t .l{font-size:9.5px;line-height:1.3;padding-bottom:2px}
.t.n .l{color:#555}
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
<script>
let VIEW="__VIEW__", CUR="__CUR__";
const q=new URLSearchParams(location.search);
if(!q.get('cur')&&localStorage.getItem('fxcur'))CUR=localStorage.getItem('fxcur');
const CURS=[['USD','<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/></svg>'],['USD','$'],['EUR','€'],['RUB','₽'],['UAH','₴']];
function drawCur(){
  const el=document.getElementById('cur');
  el.innerHTML=CURS.map(([k,l],i)=>`<button data-c="${k}" class="${(CUR===k&&i>0)||(CUR==='USD'&&i===0)?'on':''}">${l}</button>`).join('');
  el.querySelectorAll('button').forEach(b=>b.onclick=()=>{CUR=b.dataset.c;localStorage.setItem('fxcur',CUR);sync();drawCur();load();});
}
function sync(){
  document.getElementById('ddb').textContent=VIEW==='pro'?'Расширенный':'Доходы';
  document.getElementById('newb').style.display=VIEW==='pro'?'':'none';
  const u=new URL(location);u.searchParams.set('view',VIEW);u.searchParams.set('cur',CUR);history.replaceState(null,'',u);
}
function stamp(){document.querySelectorAll('.ag').forEach(e=>e.dataset.base=Date.now());tick();}
function tick(){document.querySelectorAll('.ag').forEach(e=>{
  const s=Math.round(+e.dataset.age+(Date.now()-(+e.dataset.base||Date.now()))/1000);
  e.querySelector('.at').textContent=s<60?s+' сек. назад':s<3600?Math.floor(s/60)+' мин. назад':Math.floor(s/3600)+' ч. назад';
  e.classList.toggle('stale',s>60);});}
async function load(){
  const b=document.getElementById('rf');b.classList.add('spin');setTimeout(()=>b.classList.remove('spin'),800);
  try{const r=await fetch('/fragment?view='+VIEW+'&cur='+CUR,{cache:'no-store'});
    if(r.ok){document.getElementById('app').innerHTML=await r.text();stamp();}}catch(e){}
}
document.getElementById('ddb').onclick=e=>{e.stopPropagation();document.getElementById('ddm').classList.toggle('open');};
document.querySelectorAll('#ddm a').forEach(a=>a.onclick=()=>{VIEW=a.dataset.v;sync();load();});
document.addEventListener('click',()=>document.getElementById('ddm').classList.remove('open'));
document.getElementById('rf').onclick=load;
document.getElementById('fs').onclick=()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();
drawCur();sync();stamp();setInterval(tick,1000);setInterval(load,3000);
if(CUR!=='__CUR__')load();
</script></body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
