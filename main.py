"""GTrade monitor (Расширенный / Доходы / Простой / Сводка + группы + ночная тема). Диагностика: /debug"""
import os
import sys
import json
import time
import threading
import urllib.request
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

try:
    import notify          # будущий модуль уведомлений; пока файла нет — ничего не происходит
except Exception:
    notify = None

app = FastAPI()
accounts_data = {}
last_seen = {}

PAGE_TITLE = os.environ.get("FX_TITLE", "GTrade")
API_KEY = os.environ.get("FX_API_KEY", "")
ADMIN_PASS = os.environ.get("FX_ADMIN_PASS", "")
CENT = os.environ.get("FX_CENT", "1") == "1"
TZ_HOURS = float(os.environ.get("FX_TZ", "3"))
SETTINGS_FILE = Path(os.environ.get("FX_SETTINGS", "settings.json"))
BASE_DIR = Path(__file__).resolve().parent
EXT_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg",
            ".jpe": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
BRAND = "FX Monitor (10с)"
RATES = {"USD": 1.0, "RUB": 90.0}
RATE_INFO = {"ok": False, "time": "", "src": "запасной курс"}
try:
    RATES.update(json.loads(os.environ.get("FX_RATES", "{}")))
except Exception:
    pass
SYMS = {"USD": "$", "RUB": "₽"}
GREEN_AT, YELLOW_AT = 2.0, 10.0                 # пороги плиток пар (в %): до 2 зелёный, 2-10 жёлтый, выше красный
DD_GREEN_BELOW, DD_YELLOW_BELOW = 10.0, 30.0    # пороги крупной просадки на карточке

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


def page_title():
    return str(SETTINGS.get("_page", {}).get("name") or PAGE_TITLE)


# ---------------------------------------------------------------- группы счетов
def new_gid(n=0):
    return f"g{int(time.time() * 1000)}{n}"


def clean_groups(raw):
    out, used, ids = [], set(), set()
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        lg = it.get("logins")
        if not isinstance(lg, list) or len(lg) != 2:
            continue
        lg = [str(x).strip() for x in lg]
        if not lg[0] or not lg[1] or lg[0] == lg[1] or lg[0] in used or lg[1] in used:
            continue
        gid = str(it.get("id") or "")[:30]
        if not gid or gid in ids:
            gid = new_gid(len(out))
        ids.add(gid)
        used.update(lg)
        out.append({"id": gid, "logins": lg, "title": str(it.get("title") or "")[:40]})
    return out


def get_groups():
    return clean_groups(SETTINGS.get("_groups"))


def fetch_cbr_rate():
    req = urllib.request.Request("https://www.cbr-xml-daily.ru/daily_json.js",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode("utf-8"))
    usd = data["Valute"]["USD"]
    return float(usd["Value"]) / float(usd.get("Nominal", 1) or 1)


def rate_worker():
    while True:
        wait = 300
        try:
            v = fetch_cbr_rate()
            if 20 < v < 500:
                RATES["RUB"] = v
                RATE_INFO.update(ok=True, src="ЦБ РФ",
                                 time=(datetime.utcnow() + timedelta(hours=TZ_HOURS)).strftime("%d.%m %H:%M"))
                wait = 3600
        except Exception:
            pass
        time.sleep(wait)


def start_rate_thread():
    threading.Thread(target=rate_worker, daemon=True).start()


def num(x, d=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else d
    except Exception:
        return d


def first_num(info, names):
    for n in names:
        v = info.get(n)
        if v is None or isinstance(v, (dict, list)):
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
    """Цвет плитки пары: до 2% зелёный, 2-10% жёлтый, выше 10% красный."""
    d = -p if p < 0 else 0.0
    return "g" if d <= GREEN_AT else ("y" if d <= YELLOW_AT else "r")


def dd_tone(p):
    """Цвет крупной просадки на карточке: до 10 зелёный, 10-30 жёлтый, от 30 красный."""
    d = -p if p < 0 else 0.0
    return "g" if d < DD_GREEN_BELOW else ("y" if d < DD_YELLOW_BELOW else "r")


def parse_date(s):
    for f in ("%d.%m.%Y", "%Y-%m-%d", "%Y.%m.%d", "%d.%m.%y"):
        try:
            return datetime.strptime(str(s).strip()[:10], f)
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
    if not isinstance(S, dict):
        S = {}

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
            bc_, sc_ = int(num(v.get("buy_cnt"))), int(num(v.get("sell_cnt")))
            if bc_ + sc_ == 0:
                continue                      # пары без ордеров не показываем
            nm = str(key).upper()
            short = nm[:6] if len(nm) > 6 and nm[:6].isalpha() else nm
            profit = num(v.get("profit")) * kb * r
            bid = v.get("bid")
            if bid is not None:
                dg = int(num(v.get("digits"), 5 if "JPY" not in short else 3))
                bid = f"{num(bid):.{dg}f}"
            syms.append(dict(name=short, buy=num(v.get("buy")), sell=num(v.get("sell")),
                             bc=bc_, sc=sc_, act=True,
                             pct=profit / bal * 100 if bal > 0 else 0.0, bid=bid))
    syms.sort(key=lambda s: s["name"])

    pair_cnt = sum(s["bc"] + s["sc"] for s in syms)
    tot_o = first_num(info, ORDER_KEYS)
    orders = int(tot_o) if tot_o is not None else pair_cnt

    algo = first_num(info, ("algo",))
    sush = first_num(info, ("sush_on",)) or 0
    forced = {"green": "g", "red": "r", "yellow": "y"}.get(str(info.get("badge_color", "")).lower())
    if forced:
        bcol = forced
    elif algo is not None and algo == 0:
        bcol = "r"
    elif sush == 1:
        bcol = "y"
    else:
        bcol = "g"

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
                syms=syms, orders=orders, bcol=bcol, algo=algo, sush=sush,
                time=str(info.get("time") or now_local().strftime("%d.%m.%Y | %H:%M:%S")),
                age=max(0, int(time.time() - ts)))


def attrs(c):
    def n(v):
        return "" if v is None else f"{v:.2f}"
    return (f'data-login="{escape(str(c["login"]))}" data-n="{escape(c["custom_name"])}" data-na="{escape(c["auto_name"])}" '
            f'data-s="{escape(c["custom_since"])}" data-sa="{escape(c["since"])}" '
            f'data-d="{n(c["dep_manual"])}" data-da="{n(c["dep_u"])}" data-w="{n(c["wd_manual"])}" data-wa="{n(c["wd_u"])}"')


BADGE_HINT = {"g": "Торговля идёт", "y": "Сушка", "r": "Алготрейдинг выключен"}


def age_html(c, short=False):
    if short:
        return f'<span class="ag" data-age="{c["age"]}"><span class="at"></span></span>'
    return (f'<span class="ag" data-age="{c["age"]}">{escape(BRAND)} | <span class="at"></span></span>')


def head_html(c):
    hint = BADGE_HINT.get(c["bcol"], "")
    return (f'<span class="name ed" title="Нажмите, чтобы переименовать">{escape(c["name"])}</span> '
            f'<span class="badge {c["bcol"]}" title="Ордеров: {c["orders"]}. {hint}">{c["orders"]}</span>')


def since_html(c):
    return f'работает с {escape(c["since"])}' if c["since"] else "&nbsp;"


def tile_html(s):
    t = tone(s["pct"])
    pct = "0%" if abs(s["pct"]) < 0.005 else f"{s['pct']:.2f}%"
    bid = f'<div class="p">{s["bid"]}</div>' if s["bid"] else ""
    return (f'<div class="t {t}"><div class="s">{escape(s["name"])}</div>{bid}'
            f'<div class="v">{pct}</div>'
            f'<div class="l">▲{lots(s["buy"])} /{s["bc"]}<br>▼{lots(s["sell"])} /{s["sc"]}</div></div>')


def margin_view(c):
    if c["lvl"] is None:
        return "—", ""
    return f"{c['lvl']:.0f}%", ("pos" if c["lvl"] >= 100 else "neg")


def pro_card(c, drag=False):
    cur, per = c["cur"], c["per"]
    ddcls = {"g": "pos", "y": "yel", "r": "neg"}[dd_tone(c["ddp"])]
    lvl, lcls = margin_view(c)
    dr = ' draggable="true"' if drag else ""

    def mini(label, v, p):
        return (f'<div class="mini"><i>{label}</i><span class="{cls(v)}">{fmt_money(v, cur)}</span>'
                f'{"" if v is None else " (" + fmt_pct(p) + ")"}</div>')

    dv = per["day"]["c"]
    big = f'{fmt_money(dv, cur)}' + ('' if dv is None else f' <small>({fmt_pct(per["day"]["cp"])})</small>')
    ping = f" ({c['ping']}мс)" if c["ping"] else ""
    return f'''<div class="card" {attrs(c)}{dr}>
  <div class="h"><div>{head_html(c)}<div class="since">{since_html(c)}</div></div>
    <div class="dt">{escape(c["time"])}<span class="mi ed" title="Настройки счёта">☰</span></div></div>
  <div class="mid">
    <div class="lm">
      <div><div class="lb">просадка</div><div class="bigp {ddcls}">{c["ddp"]:.2f}%</div><div class="sub {ddcls}">{fmt_money(c["dd"], cur)}</div></div>
      <div><div class="lb">маржа</div><div class="bigp {lcls}">{lvl}</div></div>
    </div>
    <div class="day">
      <div class="big {cls(dv)}">{big}</div>
      {mini("вчера", per["day"]["p"], per["day"]["pp"])}{mini("неделя", per["week"]["c"], per["week"]["cp"])}{mini("месяц", per["month"]["c"], per["month"]["cp"])}
    </div>
  </div>
  <div class="bar"><div>{fmt_money(c["bal"], cur)}</div><div>{fmt_money(c["eq"], cur)}</div></div>
  <div class="tiles">{"".join(tile_html(s) for s in c["syms"])}</div>
  <div class="foot"><span class="br">{escape(c["broker"])}{ping}</span>{age_html(c)}</div>
</div>'''


def pro_view(cs):
    by = {str(c["login"]): c for c in cs}
    groups = get_groups()
    gmap = {}
    for g in groups:
        for l in g["logins"]:
            if l in by:
                gmap.setdefault(l, g)
    parts, emitted = [], set()
    for c in cs:
        l = str(c["login"])
        g = gmap.get(l)
        if g is None:
            parts.append(pro_card(c, True))
            continue
        if g["id"] in emitted:
            continue
        emitted.add(g["id"])
        members = [by[x] for x in g["logins"] if x in by and gmap.get(x) is g]
        title = g["title"]
        gt_cls = "gt" if title else "gt empty"
        gid = escape(g["id"])
        parts.append(
            f'<div class="gbox" data-gid="{gid}"><div class="gh">'
            f'<span class="{gt_cls}" data-gid="{gid}" title="Нажмите, чтобы подписать группу">{escape(title) if title else "Группа"}</span>'
            f'<span class="gb"><button class="gx gswap" data-gid="{gid}" title="Поменять местами">⇄</button>'
            f'<button class="gx gdel" data-gid="{gid}" title="Разгруппировать">✕</button></span></div>'
            f'<div class="gcards">{"".join(pro_card(m) for m in members)}</div></div>')
    return f'<div class="grid">{"".join(parts)}</div>'


def simple_card(c):
    cur, per = c["cur"], c["per"]
    ddcls = {"g": "pos", "y": "yel", "r": "neg"}[dd_tone(c["ddp"])]
    lvl, lcls = margin_view(c)
    dv, dp = per["day"]["c"], per["day"]["cp"]
    big = fmt_pct(dp)
    sub = "" if dv is None else fmt_money(dv, cur)
    return f'''<div class="card sc" {attrs(c)}>
  <div class="c1"><div class="nm">{head_html(c)}</div>{age_html(c, True)}</div>
  <div class="c2">
    <div><span class="lb">просадка</span><b class="{ddcls}">{c["ddp"]:.2f}%</b></div>
    <div><span class="lb">маржа</span><b class="{lcls}">{lvl}</b></div>
  </div>
  <div class="c3"><div class="sbig {cls(dv)}">{big}</div><div class="ssub">{sub}</div></div>
  <span class="mi ed" title="Настройки счёта">☰</span>
</div>'''


def summary_html(cs, cur):
    bal = sum(x["bal"] for x in cs)
    eq = sum(x["eq"] for x in cs)
    tv = [x["per"]["day"]["c"] for x in cs if x["per"]["day"]["c"] is not None]
    today = sum(tv) if tv else None
    date = now_local().strftime("%d.%m.%Y")
    rows = ""
    for c in cs:
        ddcls = {"g": "pos", "y": "yel", "r": "neg"}[dd_tone(c["ddp"])]
        lvl, lcls = margin_view(c)
        dp = c["per"]["day"]["cp"]
        dv = c["per"]["day"]["c"]
        rows += (f'<tr {attrs(c)}><td>{head_html(c)}</td>'
                 f'<td class="{ddcls}">{c["ddp"]:.2f}%</td>'
                 f'<td class="{lcls}">{lvl}</td>'
                 f'<td class="{cls(dv)}">{fmt_pct(dp)}</td></tr>')
    return f'''<div class="card sumcard">
  <div class="sh">
    <div class="rows">
      <div class="row">баланс <b class="c1">{fmt_money(bal, cur)}</b></div>
      <div class="row">эквити <b class="c2">{fmt_money(eq, cur)}</b></div>
      <div class="row">сегодня <i>({date})</i> <b class="{cls(today)}">{fmt_money(today, cur)}</b></div>
    </div>
    <div class="cnt">кол-во счетов: <b>{len(cs)}</b></div>
  </div>
  <table class="st"><tr><th>счёт</th><th>просадка</th><th>маржа</th><th>доход</th></tr>{rows}</table>
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
        txt = "—" if v is None else f"{v:.2f}%"
        return f'<span class="{kind}">{kind.upper()} <b>{txt}</b></span>'

    dep_t = fmt_money(c["dep"] if c["known"] else None, cur)
    wd_t = fmt_money(c["wd"] if c["known"] else None, cur)
    return f'''<div class="card" {attrs(c)}>
  <div class="ig">
    <div>{head_html(c)}</div><div class="r2 dt">{escape(c["time"])}<span class="mi ed" title="Настройки счёта">☰</span></div>
    <div class="since">{since_html(c)}</div><div class="r2 bal">{fmt_money(c["bal"], cur)}</div>
    <div>ежедневно {pc(c["d"])}</div><div class="r2"><span class="lb2">пополнения</span> <span class="lnk">{dep_t}</span></div>
    <div>ежемесячно {pc(c["m"])}</div><div class="r2"><span class="lb2">снятия</span> <span class="lnk">{wd_t}</span></div>
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
                f'<div class="grid" style="margin-top:30px">{"".join(income_card(c) for c in cs)}</div>')
    if view == "simple":
        return f'<div class="grid sg">{"".join(simple_card(c) for c in cs)}</div>'
    if view == "summary":
        return f'<div class="grid sgrid">{summary_html(cs, cur)}</div>'
    return pro_view(cs)


VIEWS = {"pro": "pro", "income": "income", "inc": "income", "доходы": "income",
         "simple": "simple", "простой": "simple",
         "summary": "summary", "svodka": "summary", "сводка": "summary"}


def norm_view(v):
    return VIEWS.get(str(v).lower(), "pro")


def norm_mode(c):
    c = str(c or "ORIG").upper()
    return c if c in ("ORIG", "USD", "RUB") else "ORIG"


def real_cur(mode):
    return "USD" if mode == "ORIG" else mode


def find_logo():
    """Ищет logo.* (png, jpg, jpeg, jfif, webp, gif) рядом с main.py, регистр не важен."""
    try:
        for p in sorted(BASE_DIR.iterdir()):
            if p.is_file() and p.stem.lower() == "logo" and p.suffix.lower() in EXT_MIME:
                return p, EXT_MIME[p.suffix.lower()]
    except Exception:
        pass
    return None, ""


@app.get("/logo")
def logo():
    p, mime = find_logo()
    if p is not None:
        try:
            return Response(p.read_bytes(), media_type=mime, headers={"Cache-Control": "public, max-age=3600"})
        except Exception:
            pass
    return Response("logo not found (загрузите logo.png / logo.jpg / logo.jfif рядом с main.py)", status_code=404)


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


@app.get("/api/rates")
def api_rates():
    return {"RUB": round(RATES.get("RUB", 0), 4), "ok": RATE_INFO["ok"],
            "src": RATE_INFO["src"], "time": RATE_INFO["time"]}


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
        if not login or (login.startswith("_") and login != "_page"):
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


@app.get("/api/groups")
def api_groups_get():
    return {"groups": get_groups()}


@app.post("/api/groups")
async def api_groups_post(request: Request):
    try:
        data = json.loads((await request.body()).decode("utf-8-sig", "ignore"))
        if ADMIN_PASS and str(data.get("pass", "")) != ADMIN_PASS:
            return JSONResponse({"status": "error", "detail": "bad pass"}, status_code=403)
        act = str(data.get("action", ""))
        gid = str(data.get("id", ""))
        groups = get_groups()
        if act == "add":
            lg = [str(x).strip() for x in (data.get("logins") or [])]
            if len(lg) != 2 or not lg[0] or not lg[1] or lg[0] == lg[1]:
                return {"status": "error", "detail": "Нужно выбрать два разных счёта"}
            used = {x for g in groups for x in g["logins"]}
            if lg[0] in used or lg[1] in used:
                return {"status": "error", "detail": "Один из счетов уже в группе"}
            groups.append({"id": new_gid(len(groups)), "logins": lg, "title": ""})
        elif act == "del":
            groups = [g for g in groups if g["id"] != gid]
        elif act == "swap":
            for g in groups:
                if g["id"] == gid:
                    g["logins"].reverse()
        elif act == "title":
            for g in groups:
                if g["id"] == gid:
                    g["title"] = str(data.get("title") or "").strip()[:40]
        elif act == "set":
            groups = clean_groups(data.get("groups"))
        else:
            return {"status": "error", "detail": "Неизвестное действие"}
        SETTINGS["_groups"] = groups
        save_settings()
        return {"status": "success", "groups": groups}
    except Exception:
        return {"status": "error", "detail": "Ошибка сервера"}


@app.get("/debug", response_class=HTMLResponse)
def debug():
    checks = [("balance", ("balance",)), ("equity", ("equity",)), ("margin", ("margin",)),
              ("ордера (tot_orders)", ORDER_KEYS), ("algo (алготрейдинг)", ("algo",)),
              ("sush_on (сушка)", ("sush_on",)),
              ("connected (связь терминала)", ("connected",))]
    checks += [(k, v) for k, v in PERIOD_KEYS.items()]
    checks += [("deposits", DEP_KEYS), ("withdrawals", WD_KEYS)]
    out = ['<meta charset="utf-8"><body style="font:14px Arial;padding:16px;background:#f4f6fa"><h2>Диагностика: что прислал робот</h2>']
    rate_txt = f"1 $ = {RATES.get('RUB', 0):.2f} ₽ ({RATE_INFO['src']}" + (f", {RATE_INFO['time']}" if RATE_INFO["time"] else "") + ")"
    out.append(f"<p>Курс рубля: <b>{escape(rate_txt)}</b></p>")
    lp, _ = find_logo()
    out.append(f"<p>Логотип: <b>{'найден: ' + escape(lp.name) if lp else 'НЕ найден (загрузите logo.png / logo.jpg / logo.jfif рядом с main.py)'}</b></p>")
    out.append(f"<p>Групп счетов: <b>{len(get_groups())}</b></p>")
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
def fragment(view: str = "pro", cur: str = "ORIG"):
    return render_body(norm_view(view), real_cur(norm_mode(cur)))


@app.get("/", response_class=HTMLResponse)
@app.get("/u/{user}", response_class=HTMLResponse)
def home(user: str = "", view: str = "pro", cur: str = "ORIG"):
    v, m = norm_view(view), norm_mode(cur)
    title = escape(page_title())
    return (PAGE.replace("__TITLE__", title).replace("__VIEW__", v)
            .replace("__CUR__", m).replace("__BODY__", render_body(v, real_cur(m))))


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script>try{if(localStorage.getItem('fxtheme')==='dark')document.documentElement.classList.add('dark')}catch(e){}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--green:#28c76f;--red:#dc1e4b;--yellow:#e0a800;--blue:#3d5fd6;--blue2:#1aa7ff;
  --bg1:#e2eaf2;--bg2:#d5dfea;--card:#fff;--cardbd:transparent;--tx:#2b2f36;--st:#222;--mu:#888;--mu2:#999;
  --ln:#eef0f3;--ln2:#d5dbe4;--inp:#fff;--inpbd:#c5cedd;--ddbg:#fff;--hov:#eef2fb;--sh:rgba(40,60,90,.25);
  --th:#1f2328;--ago:#5fd39a;--totbg:linear-gradient(180deg,#adc3f3 0%,#dde8f8 45%,#d9f6e8 100%)}
html.dark{--green:#34d986;--red:#ff4d70;--yellow:#f5b800;--blue:#7b95ff;--blue2:#3db8ff;
  --bg1:#070d1a;--bg2:#0f1a30;--card:#141d2f;--cardbd:#23324d;--tx:#d6deec;--st:#f0f4fb;--mu:#8793a8;--mu2:#7c889d;
  --ln:#1f2b42;--ln2:#26344d;--inp:#0e1626;--inpbd:#2c3c5a;--ddbg:#16213a;--hov:#1d2b49;--sh:rgba(0,0,0,.5);
  --th:#0a111f;--ago:#4fd69a;--totbg:linear-gradient(180deg,#25365f 0%,#18233c 55%,#143229 100%)}
*{box-sizing:border-box}
html{background:var(--bg2)}
body{margin:0;font:13px/1.35 "Open Sans","Segoe UI",Roboto,Arial,sans-serif;color:var(--tx);
  background:linear-gradient(135deg,var(--bg1),var(--bg2));min-height:100vh}
.wrap{padding:8px 8px 70px}
.hero{position:relative;border-radius:10px;padding:12px 16px 14px;min-height:124px;box-shadow:0 4px 18px rgba(8,20,60,.35)}
.hero-bg{position:absolute;inset:0;border-radius:10px;overflow:hidden;
  background:
    radial-gradient(520px 200px at 82% 50%,rgba(0,229,255,.30),transparent 62%),
    radial-gradient(380px 180px at 8% 0%,rgba(90,70,255,.40),transparent 62%),
    linear-gradient(120deg,#050b1f 0%,#0a1a3d 55%,#04101f 100%)}
.hero-bg:before{content:"";position:absolute;inset:0;
  background-image:linear-gradient(rgba(0,229,255,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.09) 1px,transparent 1px);
  background-size:26px 26px;
  -webkit-mask-image:linear-gradient(90deg,transparent 0%,#000 45%,#000 100%);mask-image:linear-gradient(90deg,transparent 0%,#000 45%,#000 100%)}
.hero-bg:after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;
  background:linear-gradient(90deg,transparent,#00e5ff 25%,#28c76f 50%,#ff2d55 75%,transparent)}
.logo{position:absolute;right:14%;top:50%;transform:translateY(-50%);height:150%;width:auto;
  mix-blend-mode:screen;opacity:.95;
  -webkit-mask-image:radial-gradient(closest-side,#000 45%,transparent 100%);mask-image:radial-gradient(closest-side,#000 45%,transparent 100%)}
.hero-in{position:relative;z-index:1;display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.hl{display:flex;flex-direction:column;gap:10px}
.hr{display:flex;flex-direction:column;align-items:flex-end;gap:8px}
h1{margin:0;font-size:22px;font-weight:700;color:#fff;display:flex;align-items:center;gap:8px;text-shadow:0 0 14px rgba(0,229,255,.65)}
h1 svg{width:20px;height:20px;fill:#7fe9ff}
#ttl{cursor:pointer}
#ttl:hover{text-decoration:underline dotted}
.btn{border:0;border-radius:4px;color:#fff;cursor:pointer;width:38px;height:32px;display:inline-flex;align-items:center;justify-content:center;vertical-align:top}
.btn svg{width:15px;height:15px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.b-g{background:#2ecc71;box-shadow:0 0 10px rgba(46,204,113,.5)}
.b-th{background:#1d3a78;border:1px solid rgba(0,229,255,.5);width:34px}
.i-sun{display:none}
html.dark .i-sun{display:block}
html.dark .i-moon{display:none}
.spin svg{animation:sp .8s linear}
@keyframes sp{to{transform:rotate(360deg)}}
.dd{position:relative;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.ddbtn{background:#1d3a78;color:#fff;border:1px solid rgba(0,229,255,.5);border-radius:3px;padding:8px 14px;font-weight:600;cursor:pointer;font-size:13px;font-family:inherit;box-shadow:0 0 10px rgba(0,229,255,.28)}
.ddbtn:after{content:"";display:inline-block;margin-left:8px;border:4px solid transparent;border-top-color:#fff;vertical-align:-2px}
.ddbtn.plain:after{display:none}
body.gm #gm{background:#2ecc71;color:#06260f;border-color:#2ecc71}
.ddm{display:none;position:absolute;top:38px;left:0;background:var(--ddbg);border-radius:3px;box-shadow:0 3px 12px rgba(0,0,0,.35);z-index:9;min-width:160px}
.ddm.open{display:block}
.ddm a{display:block;padding:8px 14px;color:var(--tx);cursor:pointer}
.ddm a:hover{background:var(--hov)}
.curbox{text-align:right}
.crow{display:inline-flex;gap:6px;align-items:center}
.cur{display:inline-flex;border:1px solid #3f7cf0;border-radius:3px;overflow:hidden;background:var(--card);height:32px}
.cur button{border:0;border-left:1px solid #3f7cf0;background:var(--card);color:#3f7cf0;width:34px;cursor:pointer;font-size:13px;font-weight:700;font-family:inherit}
.cur button:first-child{border-left:0}
.cur button.on{background:#3f7cf0;color:#fff}
.cur svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2}
.rate{color:#a8c4ea;font-size:10.5px;margin-top:3px;min-height:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,440px),1fr));gap:30px;margin:16px 0 0;align-items:stretch}
.grid.sg{grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:8px}
.grid.sgrid{grid-template-columns:minmax(0,620px)}
.card{background:var(--card);border:1px solid var(--cardbd);border-radius:3px;box-shadow:0 1px 4px var(--sh);padding:14px 16px 8px;position:relative;display:flex;flex-direction:column}
.name{font-weight:700;font-size:13px;color:var(--st)}
.ed{cursor:pointer}
.name.ed:hover{text-decoration:underline dotted}
.badge{display:inline-block;min-width:22px;padding:0 6px;margin-left:4px;border-radius:12px;color:#fff;font-weight:600;font-size:12px;text-align:center}
.g{background:var(--green)}.r{background:var(--red)}.y{background:#f6b90f}
.since{color:var(--mu2);font-size:11px}
.dt{color:var(--mu);font-size:10.5px;text-align:right}
.mi{color:var(--mu);font-size:13px;display:block;text-align:right;line-height:1}
.pos{color:var(--green)}.neg{color:var(--red)}.yel{color:var(--yellow)}
.h{display:flex;justify-content:space-between}
.mid{display:flex;justify-content:space-between;margin-top:2px;gap:8px}
.lm{display:flex;gap:16px;flex-wrap:wrap}.lm .lb{color:var(--mu2);font-size:13px}
.bigp{font-size:25px;font-weight:700;line-height:1.15}
.sub{font-size:12px}
.day{text-align:right}
.day .big{font-size:24px;font-weight:700;color:var(--st);line-height:1.1;white-space:nowrap}
.day .big small{font-size:18px;font-weight:600;color:var(--mu)}
.day .big.pos{color:var(--green)}.day .big.neg{color:var(--red)}
.mini{font-size:11.5px;color:var(--tx);white-space:nowrap}.mini i{font-style:normal;color:var(--mu2);font-size:10px;margin-right:3px}
.bar{display:flex;height:31px;margin-top:6px;color:#fff;font-weight:700;font-size:16px}
.bar div{flex:1;display:flex;align-items:center;justify-content:center;white-space:nowrap;overflow:hidden}
.bar div:first-child{background:#4169e1}.bar div:last-child{background:#1aa7ff}
.tiles{display:flex;flex-wrap:wrap;gap:4px;margin-top:10px;min-height:20px}
.t{width:66px;text-align:center;color:#fff;background:#3dc47e;border-radius:6px;overflow:hidden;padding-top:1px}
.t.y{background:#f4b32a}.t.r{background:#dc1e4b}
.t .s{color:#1e2226;font-weight:700;font-size:11px;line-height:1.2;padding:4px 0 3px}
.t .p{background:#33383e;color:#fff;font-size:11px;font-weight:600;line-height:1.3;padding:1px 0;margin:0 3px;border-radius:3px}
.t .v{color:#111;font-size:15px;font-weight:700;line-height:1.2;padding:5px 0 3px;white-space:nowrap;letter-spacing:-.2px}
.t .l{color:#1e2226;font-size:10.5px;font-weight:600;line-height:1.35;padding:3px 0 4px;background:rgba(0,0,0,.09);border-top:1px solid rgba(0,0,0,.12);white-space:nowrap}
.t.r .s{color:#1e2226}
.t.r .v{color:#fff}
.t.r .l{color:#fff;background:rgba(0,0,0,.14);border-top-color:rgba(255,255,255,.3)}
.foot{display:flex;justify-content:space-between;margin-top:auto;padding-top:10px;font-size:9.5px}
.foot .br{color:var(--mu2)}
.ag{color:var(--ago)}.ag.stale{color:var(--red)}
/* простой: компактная строка */
.sc{flex-direction:row;align-items:center;gap:10px;padding:6px 22px 6px 12px;min-height:48px}
.sc .c1{flex:1;min-width:0}
.sc .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc .ag{display:block;font-size:9px;line-height:1.2}
.sc .c2{display:flex;flex-direction:column;font-size:13px;line-height:1.25;white-space:nowrap}
.sc .c2 .lb{color:var(--mu2);font-size:10.5px;margin-right:4px}
.sc .c2 b{font-weight:700}
.sc .c3{text-align:right;min-width:78px}
.sbig{font-size:21px;font-weight:700;line-height:1.05;color:var(--st);white-space:nowrap}
.sbig.pos{color:var(--green)}.sbig.neg{color:var(--red)}
.ssub{font-size:11px;color:var(--mu);line-height:1.2;min-height:13px}
.sc .mi{position:absolute;top:3px;right:6px;font-size:12px}
/* сводка */
.sumcard{padding:0;overflow:hidden}
.sh{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;padding:10px 16px 8px}
.sh .row{font-size:12px;font-weight:700;color:var(--tx);text-transform:uppercase;margin:0;line-height:1.55}
.sh .row b{font-size:17px;margin-left:6px;font-weight:700}
.sh .row i{font-style:normal;color:var(--mu);font-weight:600}
.sh .c1{color:var(--blue)}.sh .c2{color:var(--blue2)}
.sh .cnt{text-align:right;color:var(--mu);font-size:11.5px;text-transform:uppercase;white-space:nowrap;margin-top:3px}
.sh .cnt b{color:var(--tx)}
table.st{width:100%;border-collapse:collapse}
.st th{background:var(--th);color:#fff;font-weight:700;text-align:right;padding:9px 10px;font-size:12.5px}
.st th:first-child{text-align:left;padding-left:18px}
.st td{padding:9px 10px;text-align:right;border-top:1px solid var(--ln);font-weight:600;white-space:nowrap}
.st td:first-child{text-align:left;padding-left:18px}
/* доходы */
.tot{background:var(--totbg);padding-bottom:12px}
.tot .ttl{display:flex;justify-content:space-between;align-items:center;margin:6px 0 10px}
.tot .ttl b{font-size:14px;text-transform:uppercase;color:var(--st)}
.bal{font-size:18px;font-weight:600;color:var(--blue)}
.ig{display:grid;grid-template-columns:1fr auto;column-gap:10px;row-gap:1px;align-items:center}
.ig .r2{text-align:right}
.lnk{color:var(--blue)}
.lb2{color:var(--mu);font-size:13px}
.roi,.rom{display:inline-block;padding:0 6px;margin-top:1px;font-size:13px;color:#222;border-radius:2px}
.roi{background:linear-gradient(90deg,#8bf0b5,#3fd48a)}
.rom{background:linear-gradient(90deg,#73e6f6,#4a9df8)}
.roi b,.rom b{font-weight:700}
table.pt{width:100%;border-collapse:collapse;margin-top:10px}
.pt th{font-weight:400;color:var(--mu);text-align:right;padding:1px 0}
.pt td{text-align:right;padding:2px 0;border-top:1px solid var(--ln2);white-space:nowrap}
.pt td:first-child,.pt th:first-child{text-align:left;color:var(--mu);width:20%}
.pt td b{font-weight:700;color:var(--st)}
.pt td b.pos{color:var(--green)}.pt td b.neg{color:var(--red)}
.pt td em{font-style:normal;color:var(--tx)}
.empty{margin:40px 8px;color:var(--mu)}
/* группы */
.gbox{background:rgba(63,124,240,.09);border:1px solid rgba(63,124,240,.4);border-radius:8px;padding:6px 8px 8px;display:flex;flex-direction:column}
.gh{display:flex;justify-content:space-between;align-items:center;min-height:24px;margin-bottom:4px}
.gt{font-weight:700;font-size:12px;color:var(--st);cursor:pointer;letter-spacing:.4px}
.gt.empty{color:var(--mu);font-weight:600}
.gx{border:0;background:transparent;color:var(--mu);font-size:15px;cursor:pointer;padding:2px 7px;border-radius:3px;font-family:inherit}
.gx:hover{background:rgba(63,124,240,.25);color:var(--st)}
.gcards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;flex:1}
.card.sel{outline:3px solid #3f7cf0;outline-offset:-1px}
.card.dov{outline:3px dashed #2ecc71;outline-offset:-1px}
.card.dragging{opacity:.5}
body.gm .card[data-login]{cursor:pointer}
body.gm .gbox .card{opacity:.55}
#gbar{display:none;position:fixed;left:50%;transform:translateX(-50%);bottom:14px;z-index:40;background:#1d3a78;color:#fff;border-radius:8px;padding:8px 12px;gap:10px;align-items:center;box-shadow:0 4px 18px rgba(0,0,0,.45);font-size:13px;max-width:96vw}
#gbar button{border:0;border-radius:4px;padding:7px 12px;font-weight:600;cursor:pointer;font-family:inherit}
#gok{background:#2ecc71;color:#06260f}
#gok:disabled{opacity:.45;cursor:default}
#gend{background:#e6ebf3;color:#223}
/* модальное окно */
.mdl{display:none;position:fixed;inset:0;background:rgba(10,16,30,.55);z-index:50;align-items:center;justify-content:center}
.mdl.open{display:flex}
.mbox{background:var(--card);color:var(--tx);border:1px solid var(--cardbd);border-radius:4px;padding:18px 20px;width:min(92vw,360px);box-shadow:0 8px 30px rgba(0,0,0,.35)}
.mbox h3{margin:0 0 6px;font-size:15px;color:var(--st)}
.mbox label{display:block;color:var(--mu);font-size:12px;margin-top:9px}
.mbox input{width:100%;padding:7px 9px;border:1px solid var(--inpbd);background:var(--inp);color:var(--st);border-radius:3px;font-size:14px;margin-top:3px;font-family:inherit}
.mbtn{display:flex;gap:8px;margin-top:14px}
.mbtn button{flex:1;padding:9px;border:0;border-radius:3px;cursor:pointer;font-weight:600;font-family:inherit}
#m_save{background:#1d3a78;color:#fff}#m_cancel{background:var(--hov);color:var(--tx)}
.mhint{color:var(--mu2);font-size:11px;margin-top:8px}
@media(min-width:930px){.gbox{grid-column:span 2}}
@media(max-width:880px){
  .gbox{padding:5px 5px 6px}
  .gbox .card{padding:8px 8px 6px}
  .gbox .name{font-size:12px}
  .gbox .badge{min-width:18px;padding:0 4px;font-size:11px}
  .gbox .dt{font-size:0;line-height:0}
  .gbox .mi{font-size:14px;line-height:1}
  .gbox .since{font-size:9.5px}
  .gbox .mid{flex-direction:column;gap:2px}
  .gbox .lm{gap:10px}
  .gbox .lm .lb{font-size:11px}
  .gbox .bigp{font-size:19px}
  .gbox .sub{font-size:10.5px}
  .gbox .day{text-align:left}
  .gbox .day .big{font-size:18px}
  .gbox .day .big small{font-size:13px}
  .gbox .mini{font-size:10px}
  .gbox .bar{height:25px;font-size:12px}
  .gbox .tiles{gap:3px}
  .gbox .t{width:50px}
  .gbox .t .s{font-size:10px}.gbox .t .p{font-size:9.5px}.gbox .t .v{font-size:12px}.gbox .t .l{font-size:9px}
  .gbox .foot{justify-content:flex-end}
  .gbox .foot .br{display:none}
  .gbox .ag{font-size:8.5px}
}
@media(max-width:700px){
  .logo{right:auto;left:50%;transform:translate(-50%,-50%);height:135%;opacity:.7}
}
@media(max-width:560px){
  h1{font-size:20px}
}
</style></head><body><div class="wrap">
<div class="hero">
  <div class="hero-bg"><img class="logo" src="/logo" alt="" onerror="this.style.display='none'"></div>
  <div class="hero-in">
    <div class="hl">
      <h1><svg viewBox="0 0 24 24"><path d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2c-4 0-8 2-8 5v3h16v-3c0-3-4-5-8-5z"/></svg><span id="ttl" title="Нажмите, чтобы переименовать">__TITLE__</span></h1>
      <div class="dd"><button class="ddbtn" id="ddb">Расширенный</button>
        <button class="ddbtn plain" id="gm" title="Объединить два счёта рядом">Группы</button>
        <div class="ddm" id="ddm"><a data-v="pro">Расширенный</a><a data-v="income">Доходы</a><a data-v="simple">Простой</a><a data-v="summary">Сводка</a></div></div>
    </div>
    <div class="hr">
      <button class="btn b-g" id="rf" title="Обновить"><svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7M21 3v6h-6"/></svg></button>
      <div class="curbox">
        <div class="crow">
          <button class="btn b-th" id="th" title="Тема: день / ночь">
            <svg class="i-moon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
            <svg class="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
          </button>
          <div class="cur" id="cur"></div>
        </div>
        <div class="rate" id="rate"></div>
      </div>
    </div>
  </div>
</div>
<div id="app">__BODY__</div>
</div>
<div id="gbar"><span id="gtx">Выберите 2 счёта (0/2)</span><button id="gok" disabled>Объединить</button><button id="gend">Готово</button></div>
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
let VIEW="__VIEW__", CUR="__CUR__", EDIT=null, RATE=null, GM=false, SEL=[], DRAG=null;
const NAMES={pro:'Расширенный',income:'Доходы',simple:'Простой',summary:'Сводка'};
const q=new URLSearchParams(location.search);
const OKC=['ORIG','USD','RUB'];
if(!q.get('cur')){const s=localStorage.getItem('fxcur');if(OKC.includes(s))CUR=s;}
const CURS=[['ORIG','<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/></svg>'],['USD','$'],['RUB','₽']];
const $=id=>document.getElementById(id);

/* ---- тема ---- */
$('th').onclick=()=>{
  const d=!document.documentElement.classList.contains('dark');
  document.documentElement.classList.toggle('dark',d);
  try{localStorage.setItem('fxtheme',d?'dark':'light');}catch(e){}
};

/* ---- валюта ---- */
function drawCur(){
  $('cur').innerHTML=CURS.map(([k,l])=>`<button data-c="${k}" class="${CUR===k?'on':''}">${l}</button>`).join('');
  $('cur').querySelectorAll('button').forEach(b=>b.onclick=()=>{CUR=b.dataset.c;localStorage.setItem('fxcur',CUR);sync();drawCur();showRate();load();});
}
function showRate(){
  const el=$('rate');
  if(CUR==='RUB'&&RATE){el.textContent='1 $ = '+RATE.RUB.toFixed(2)+' ₽ ('+RATE.src+(RATE.time?', '+RATE.time:'')+')';}
  else el.textContent='';
}
async function loadRate(){try{RATE=await (await fetch('/api/rates',{cache:'no-store'})).json();showRate();}catch(e){}}
function sync(){
  $('ddb').textContent=NAMES[VIEW]||NAMES.pro;
  $('gm').style.display=VIEW==='pro'?'':'none';
  if(VIEW!=='pro'&&GM){GM=false;SEL=[];applySel();}
  const u=new URL(location);u.searchParams.set('view',VIEW);u.searchParams.set('cur',CUR);history.replaceState(null,'',u);
}

/* ---- время "сек. назад" ---- */
function stamp(){document.querySelectorAll('.ag').forEach(e=>e.dataset.base=Date.now());tick();}
function tick(){document.querySelectorAll('.ag').forEach(e=>{
  const s=Math.round(+e.dataset.age+(Date.now()-(+e.dataset.base||Date.now()))/1000);
  e.querySelector('.at').textContent=s<60?s+' сек. назад':s<3600?Math.floor(s/60)+' мин. назад':Math.floor(s/3600)+' ч. назад';
  e.classList.toggle('stale',s>60);});}

/* ---- загрузка ---- */
async function load(){
  if(DRAG)return;
  $('rf').classList.add('spin');setTimeout(()=>$('rf').classList.remove('spin'),800);
  try{const r=await fetch('/fragment?view='+VIEW+'&cur='+CUR,{cache:'no-store'});
    if(r.ok){const t=await r.text();if(!DRAG){$('app').innerHTML=t;stamp();applySel();}}}catch(e){}
}

/* ---- запросы с паролем ---- */
async function api(url,p){
  p.pass=sessionStorage.getItem('fxpass')||'';
  try{
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
    if(r.status===403){const w=prompt('Пароль на изменение настроек:');if(w){sessionStorage.setItem('fxpass',w);return api(url,p);}return null;}
    return await r.json();
  }catch(e){return null;}
}
async function saveSettings(p){const j=await api('/api/settings',p);return !!j&&j.status==='success';}

/* ---- название страницы ---- */
$('ttl').onclick=async()=>{
  const v=prompt('Название страницы (пусто = по умолчанию):',$('ttl').textContent);
  if(v===null)return;
  const p={login:'_page',name:v};
  if(await saveSettings(Object.assign({},p))){
    if(v.trim())localStorage.setItem('fxset__page',JSON.stringify(p));else localStorage.removeItem('fxset__page');
    location.reload();
  }else alert('Не удалось сохранить');
};

/* ---- настройки счёта ---- */
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
    if(ch&&!sessionStorage.getItem('fxrestored')){sessionStorage.setItem('fxrestored','1');location.reload();}
  }catch(e){}
}

/* ---- группы счетов ---- */
function applySel(){
  document.querySelectorAll('#app .card[data-login]').forEach(c=>c.classList.toggle('sel',SEL.includes(c.dataset.login)));
  document.body.classList.toggle('gm',GM);
  $('gbar').style.display=GM?'flex':'none';
  $('gtx').textContent=SEL.length===2?'Выбрано 2 счёта':'Выберите 2 счёта ('+SEL.length+'/2)';
  $('gok').disabled=SEL.length!==2;
}
async function gact(p){
  const j=await api('/api/groups',p);
  if(!j||j.status!=='success'){alert((j&&j.detail)||'Не удалось сохранить группу');return false;}
  try{localStorage.setItem('fxgroups',JSON.stringify(j.groups||[]));}catch(e){}
  await load();return true;
}
$('gm').onclick=()=>{GM=!GM;SEL=[];applySel();};
$('gend').onclick=()=>{GM=false;SEL=[];applySel();};
$('gok').onclick=async()=>{
  if(SEL.length!==2)return;
  if(await gact({action:'add',logins:SEL.slice()})){SEL=[];GM=false;applySel();}
};
document.addEventListener('click',e=>{
  if(!GM)return;
  const c=e.target.closest('#app .card[data-login]');
  if(!c)return;
  e.stopPropagation();e.preventDefault();
  if(c.closest('.gbox'))return;
  const l=c.dataset.login,i=SEL.indexOf(l);
  if(i>=0)SEL.splice(i,1);else{SEL.push(l);if(SEL.length>2)SEL.shift();}
  applySel();
},true);
$('app').addEventListener('click',e=>{
  const b=e.target.closest('.gswap,.gdel,.gt');
  if(!b)return;
  const id=b.dataset.gid;
  if(b.classList.contains('gdel')){if(confirm('Разгруппировать счета?'))gact({action:'del',id:id});}
  else if(b.classList.contains('gswap'))gact({action:'swap',id:id});
  else{
    const v=prompt('Подпись группы (например EURUSD):',b.classList.contains('empty')?'':b.textContent);
    if(v!==null)gact({action:'title',id:id,title:v});
  }
});
function clearDrag(){document.querySelectorAll('.dov,.dragging').forEach(x=>x.classList.remove('dov','dragging'));}
$('app').addEventListener('dragstart',e=>{
  const c=e.target.closest&&e.target.closest('.card[draggable="true"]');
  if(!c||GM)return;
  DRAG=c.dataset.login;
  e.dataTransfer.effectAllowed='move';
  try{e.dataTransfer.setData('text/plain',DRAG);}catch(_){}
  c.classList.add('dragging');
});
$('app').addEventListener('dragover',e=>{
  if(!DRAG)return;
  const c=e.target.closest&&e.target.closest('.card[draggable="true"]');
  if(c&&c.dataset.login!==DRAG){
    e.preventDefault();e.dataTransfer.dropEffect='move';
    document.querySelectorAll('.dov').forEach(x=>{if(x!==c)x.classList.remove('dov');});
    c.classList.add('dov');
  }
});
$('app').addEventListener('drop',async e=>{
  if(!DRAG)return;
  const c=e.target.closest&&e.target.closest('.card[draggable="true"]');
  if(!c||c.dataset.login===DRAG)return;
  e.preventDefault();
  const a=c.dataset.login,b=DRAG;DRAG=null;clearDrag();
  await gact({action:'add',logins:[a,b]});
});
$('app').addEventListener('dragend',()=>{DRAG=null;clearDrag();});
async function restoreGroups(){
  try{
    const g=await (await fetch('/api/groups',{cache:'no-store'})).json();
    const srv=g.groups||[];
    if(srv.length){localStorage.setItem('fxgroups',JSON.stringify(srv));return;}
    const loc=JSON.parse(localStorage.getItem('fxgroups')||'[]');
    if(loc.length){const j=await api('/api/groups',{action:'set',groups:loc});if(j&&j.status==='success')load();}
  }catch(e){}
}

/* ---- меню ---- */
$('ddb').onclick=e=>{e.stopPropagation();$('ddm').classList.toggle('open');};
document.querySelectorAll('#ddm a').forEach(a=>a.onclick=()=>{VIEW=a.dataset.v;sync();load();});
document.addEventListener('click',()=>$('ddm').classList.remove('open'));
$('rf').onclick=load;
drawCur();sync();applySel();stamp();loadRate();restore();restoreGroups();
setInterval(tick,1000);setInterval(load,3000);setInterval(loadRate,600000);
if(CUR!=='__CUR__')load();
</script></body></html>"""


start_rate_thread()
if notify is not None:
    try:
        notify.init(sys.modules[__name__], app)
    except Exception:
        pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
