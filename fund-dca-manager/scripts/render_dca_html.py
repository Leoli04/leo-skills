# -*- coding: utf-8 -*-
"""
定投台账 HTML 渲染器
------------------------------------------------------------
输入：dca_plan.json（配置）+ 定投记录/ledger.csv（台账）
输出：单文件 HTML，零 CDN、零 JS、双击即看、可打印

用法：
  python render_dca_html.py                    # 默认读同目录配置与台账
  python render_dca_html.py --out 定投台账.html
  python render_dca_html.py --weeks 12         # 历史表显示最近 N 周
------------------------------------------------------------
"""
import csv
import glob
import io
import json
import os
import sys
import time

TIER_ORDER = ["S", "A+", "A", "B", "C", "D", "E"]


# ---------- 读取 ----------
def load_config(path):
    with io.open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("accounts"):
        cap = cfg.get("total_capital", 0)
        base = cfg.get("weekly_budget_base") or (round(cap / 2 / 52) if cap else 0)
        cfg["accounts"] = [{
            "id": "A", "name": "默认账户", "total_capital": cap,
            "weekly_budget_base": base,
            "weekly_budget_cap": cfg.get("weekly_budget_cap") or base * 2,
        }]
    for a in cfg["accounts"]:
        a.setdefault("weekly_budget_cap", (a.get("weekly_budget_base") or 0) * 2)
    for f in cfg["funds"]:
        f.setdefault("account", cfg["accounts"][0]["id"])
    return cfg


def load_ledger(path):
    if not os.path.exists(path):
        return []
    rows = []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            for k in ("plan", "actual", "cumulative"):
                try:
                    r[k] = float(r.get(k) or 0)
                except (TypeError, ValueError):
                    r[k] = 0.0
            # 分位必须区分「无数据」与「真的 0.0%」：空串保留 None，
            # 否则无数据标的分位会被画成 0%、误判为历史极值区
            raw_pct = (r.get("percentile") or "").strip()
            try:
                r["percentile"] = float(raw_pct) if raw_pct != "" else None
            except (TypeError, ValueError):
                r["percentile"] = None
            try:
                r["pe"] = float(r["pe"]) if r.get("pe") else None
            except (TypeError, ValueError):
                r["pe"] = None
            rows.append(r)
    rows.sort(key=lambda r: (r.get("run_date", ""), r.get("account", "")))
    return rows


def load_snapshot(ledger_path):
    """读本轮分位快照（dca_weekly 落盘）。台账只记实际投出的标的，
    被砍到 0 的根本不在里面，光靠 ledger 画不出完整估值标尺。"""
    d = os.path.dirname(os.path.abspath(ledger_path))
    if not os.path.isdir(d):
        return None
    files = sorted(glob.glob(os.path.join(d, "snapshot_*.json")))
    if not files:
        return None
    try:
        with io.open(files[-1], encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def tier_of(pct, rules):
    if pct is None:
        return None
    for r in rules:
        if pct <= r["max_percentile"]:
            return r
    return rules[-1]


def next_triggers(pct, rules, base_w):
    """返回 (升档, 降档)：改变本周结论的临界分位。升档=分位下跌，降档=分位上涨。"""
    if pct is None:
        return None
    idx = None
    for i, r in enumerate(rules):
        if pct <= r["max_percentile"]:
            idx = i
            break
    if idx is None:
        return None
    cur = rules[idx]
    up = None
    if idx > 0:
        prev = rules[idx - 1]
        up = (prev["max_percentile"], prev["level"], prev["factor"],
              round(base_w * prev["factor"]))
    down = None
    if idx + 1 < len(rules):
        nxt = rules[idx + 1]
        down = (cur["max_percentile"], nxt["level"], nxt["factor"],
                round(base_w * nxt["factor"]))
    return up, down


def tier_action(factor, cap_ratio):
    """由系数与资金池上限推出该档的动作含义，规则改了含义跟着变，不写死在表里。"""
    if factor <= 0:
        return "停投持有，额度收紧" if cap_ratio < 0.3 else "停投持有"
    if factor <= 0.5:
        return "减速，只留底仓节奏"
    if factor <= 1.0:
        return "基准档，常规节奏"
    if factor <= 2.0:
        return "加码"
    if factor <= 3.0:
        return "大幅加码"
    return "全力加码"


def tier_range(i, rules):
    lo = rules[i - 1]["max_percentile"] if i > 0 else None
    hi = rules[i]["max_percentile"]
    if lo is None:
        return "＜%g%%" % hi
    if hi >= 100:
        return "＞%g%%" % lo
    return "%g–%g%%" % (lo, hi)


def rule_index(pct, rules):
    if pct is None:
        return None
    for i, r in enumerate(rules):
        if pct <= r["max_percentile"]:
            return i
    return None


def tier_table(rules, funds=None):
    """档位对照表。从 tier_rules 生成，改配置即改说明，避免说明与计算脱节。"""
    hits = {}
    for f in funds or []:
        i = rule_index(f.get("pct"), rules)
        if i is not None:
            hits.setdefault(i, []).append(f.get("short") or f.get("name", ""))
    p = ['<table><thead><tr><th>档</th><th>分位区间</th><th class="num">系数</th>'
         '<th class="num">资金池上限</th><th>动作</th><th>本周落此档</th></tr></thead><tbody>']
    for i, r in enumerate(rules):
        f = r["factor"]
        factor_txt = "停投" if f <= 0 else "%.1f×" % f
        names = hits.get(i) or []
        cell = "、".join(names) if names else '<span style="color:var(--ink3)">—</span>'
        p.append('<tr><td><span class="tier t-%s">%s</span></td><td class="src">%s</td>'
                 '<td class="num">%s</td><td class="num">%d%%</td>'
                 '<td style="white-space:nowrap">%s</td><td class="src" style="white-space:normal">%s</td></tr>'
                 % (esc(r["level"]), esc(r["level"]), tier_range(i, rules),
                    factor_txt, round(r.get("cap_ratio", 0) * 100),
                    esc(tier_action(f, r.get("cap_ratio", 0))), cell))
    p.append('</tbody></table>')
    return "".join(p)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def money(v):
    return "{:,.0f}".format(v)


# ---------- SVG：分位标尺 ----------
def svg_percentile(funds):
    n = len(funds)
    if not n:
        return ""
    row_h = 30
    top = 26
    h = top + n * row_h + 26
    left, bar_w = 150, 390
    parts = ['<svg viewBox="0 0 660 %d" role="img" aria-label="各基金估值分位标尺">' % h]
    parts.append('<title>各基金估值历史分位</title>')
    # 背景带按档位分五段（颜色走 CSS 变量，三套主题共用同一份 SVG）
    for a, b, color in [(0, 10, "var(--band1)"), (10, 22, "var(--band2)"), (22, 47, "var(--band3)"),
                        (47, 70, "var(--band4)"), (70, 100, "var(--band5)")]:
        parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s"/>'
                     % (left + bar_w * a / 100.0, top - 8, bar_w * (b - a) / 100.0, n * row_h, color))
    # 网格与刻度
    for pct in (0, 25, 50, 75, 100):
        x = left + bar_w * pct / 100.0
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="var(--line)" stroke-width="0.8"/>'
                     % (x, top - 14, x, top + n * row_h - 4))
        parts.append('<text x="%.1f" y="%d" font-size="10" fill="var(--ink3)" text-anchor="middle">%d%%</text>'
                     % (x, top + n * row_h + 12, pct))
    for i, f in enumerate(funds):
        y = top + i * row_h
        pct = f["pct"]
        name = f["short"]
        parts.append('<text x="%d" y="%d" font-size="11.5" fill="var(--ink)" text-anchor="end">%s</text>'
                     % (left - 12, y + 4, esc(name)))
        if pct is None:
            parts.append('<text x="%d" y="%d" font-size="11" fill="var(--ink3)">无数据</text>' % (left + 6, y + 4))
            continue
        x = left + bar_w * min(pct, 100) / 100.0
        color = "var(--buy)" if pct <= 22 else ("var(--amber)" if pct <= 47 else "var(--warn)")
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="2"/>'
                     % (x, y - 9, x, y + 9, color))
        parts.append('<circle cx="%.1f" cy="%d" r="4" fill="%s"/>' % (x, y, color))
        parts.append('<text x="%d" y="%d" font-size="11.5" fill="%s" font-weight="600" text-anchor="end">%.1f%%</text>'
                     % (620, y + 4, color, pct))
    parts.append('</svg>')
    return "".join(parts)


# ---------- SVG：累计投入曲线 ----------
def nice_max(v):
    """把上界取到好看的刻度值"""
    if v <= 0:
        return 1
    import math
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= base * m:
            return base * m
    return base * 10


def svg_cumulative(ledger, initial_total):
    by_date = {}
    for r in ledger:
        d = r.get("run_date", "")
        by_date[d] = by_date.get(d, 0) + r["actual"]
    if len(by_date) < 2:
        return ""
    dates = sorted(by_date)
    cum = []
    acc = initial_total
    for d in dates:
        acc += by_date[d]
        cum.append(acc)

    W, H = 660, 215
    left, right, top, bottom = 66, 640, 22, 170
    maxv = nice_max(max(cum) * 1.08)

    def px(i):
        return left + (right - left) * i / max(1, len(dates) - 1) if len(dates) > 1 else left

    def py(v):
        return bottom - (bottom - top) * v / maxv

    parts = ['<svg viewBox="0 0 %d %d" role="img" aria-label="累计投入曲线">' % (W, H)]
    parts.append('<title>累计投入曲线</title>')
    for i in range(4):
        v = maxv * i / 3
        y = py(v)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--line)" stroke-width="0.8"/>' % (left, y, right, y))
        parts.append('<text x="%d" y="%.1f" font-size="10" fill="var(--ink3)" text-anchor="end">%s</text>'
                     % (left - 8, y + 3, money(v)))
    pts = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, v in enumerate(cum))
    area = "%.1f,%.1f " % (px(0), bottom) + pts + " %.1f,%.1f" % (px(len(cum) - 1), bottom)
    parts.append('<polygon points="%s" fill="var(--buy)" opacity="0.12"/>' % area)
    parts.append('<polyline points="%s" fill="none" stroke="var(--buy)" stroke-width="2"/>' % pts)
    for i, v in enumerate(cum):
        if i == len(cum) - 1 or len(cum) <= 8:
            parts.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="var(--buy)"/>' % (px(i), py(v)))
            parts.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="var(--buy)" font-weight="600" text-anchor="middle">%s</text>'
                         % (px(i), py(v) - 8, money(v)))
    step = max(1, len(dates) // 6)
    for i, d in enumerate(dates):
        if i % step == 0 or i == len(dates) - 1:
            parts.append('<text x="%.1f" y="%d" font-size="10" fill="var(--ink3)" text-anchor="middle">%s</text>'
                         % (px(i), bottom + 16, d[5:]))
    parts.append('</svg>')
    return "".join(parts)


# ---------- 持仓评估 ----------
def load_holdings(cfg_path, cfg):
    """读持仓台账（市值/成本）+ 净值缓存。缺文件返回 None，评估节自动跳过。"""
    ref = cfg.get("holdings_ref")
    if not ref:
        return None
    base = os.path.dirname(os.path.abspath(cfg_path))
    p = ref if os.path.isabs(ref) else os.path.join(base, ref)
    if not os.path.exists(p):
        return None
    try:
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return None
    navs = {}
    cache = os.path.join(os.path.dirname(p), cfg.get("nav_cache") or "_nav_cache.json")
    if os.path.exists(cache):
        try:
            with io.open(cache, encoding="utf-8") as f:
                navs = (json.load(f) or {}).get("funds") or {}
        except (ValueError, OSError):
            navs = {}
    out = {}
    nav_date = ""
    for a in d.get("accounts", []):
        for f in a.get("funds", []):
            c = f.get("code")
            if not c:
                continue
            nv = navs.get(c) or {}
            if nv.get("date") and nv["date"] > nav_date:
                nav_date = nv["date"]
            out[c] = {
                "code": c,
                "name": f.get("name") or nv.get("name") or c,
                "amount": f.get("amount"), "cost": f.get("cost"),
                "nav": nv.get("nav"), "type": nv.get("type") or "",
                "account": a.get("id"),
            }
    return {"funds": out, "nav_date": nav_date, "file": os.path.basename(p)}


def assess(funds, hold, accounts, rules):
    """核账 → 诊断 → 建议。只依据可复算的两件事：仓位权重、估值分位。
    不做「看好/不看好」的主观评级，输出的是「矛盾点 + 可执行动作」。"""
    hm = hold["funds"]
    rows = []
    acct_mv = {}
    for f in funds:
        h = hm.get(f["code"]) or {}
        amt, cost, nav = h.get("amount"), h.get("cost"), h.get("nav")
        r = {"f": f, "amount": amt, "cost": cost, "nav": nav, "ok": False, "weight": None}
        if amt and cost and nav:
            inv = amt / nav * cost
            r.update(ok=True, invested=inv, pnl=amt - inv,
                     pnl_pct=(amt / inv - 1) * 100 if inv else 0.0,
                     need=(cost / nav - 1) * 100)
            acct_mv[f["account"]] = acct_mv.get(f["account"], 0) + amt
        rows.append(r)

    total_mv = sum(acct_mv.values())
    total_inv = sum(r["invested"] for r in rows if r["ok"])
    total_pnl = total_mv - total_inv

    for r in rows:
        f = r["f"]
        pct = f["pct"]
        t = tier_of(pct, rules) if pct is not None else None
        factor = t["factor"] if t else 0
        bw = f.get("base_w") or 0
        room = max(0, (f.get("pool") or 0) - (f.get("new") or 0))
        if r["ok"]:
            r["weight"] = r["amount"] / acct_mv.get(f["account"], 1) * 100
        if not r["ok"]:
            r["dg"], r["dgt"] = "mute", "市值待补"
            r["advice"] = "缺当前市值或成本价，只能看分位、算不出盈亏；补齐后本节自动重算"
        elif pct is None:
            r["dg"], r["dgt"] = "mute", "无分位"
            r["advice"] = "没有分位就不该定额，本周 0 元不是判断结论；补该指数的分位后再落档"
        elif pct > 47:
            if r["weight"] >= 15:
                r["dg"], r["dgt"] = "bad", "高位重仓"
                r["advice"] = ("停投已生效。占比最大 + 估值最贵 + 没有新钱摊薄，三条同时成立；"
                               "回本需涨 %.0f%%" % r["need"])
            elif r["pnl_pct"] <= -25:
                r["dg"], r["dgt"] = "bad", "深亏停投"
                r["advice"] = ("不加钱是对的，在贵的位置摊薄只会放大亏损；回本需涨 %.0f%%，"
                               "等分位回到 47%% 以下再用 C 档接" % r["need"])
            else:
                r["dg"], r["dgt"] = "warn", "偏贵持有"
                r["advice"] = "停投持有，不加仓；分位回落到 47%% 以下自动进 C 档（%.1f×）" % (
                    (tier_of(46.99, rules) or {}).get("factor", 0))
        elif pct <= 22:
            if r["weight"] < 5:
                r["dg"], r["dgt"] = "good", "低估轻仓"
                r["advice"] = ("钱该来这里：分位 %.1f%% 但只占 %.1f%%，额度还剩 %s；"
                               "要加只能提 base（现 %d 元/周）" %
                               (pct, r["weight"], money(room), bw))
            else:
                r["dg"], r["dgt"] = "good", "低估重仓"
                r["advice"] = "维持现额；占比已达 %.1f%%，不再提高单一权重" % r["weight"]
        else:
            r["dg"], r["dgt"] = "neutral", "中性档"
            r["advice"] = "按 %.1f× 常规投 %s 元/周，不加不减" % (factor, money(f["week"]))

    live = [r for r in rows if r["ok"]]
    by_w = sorted(live, key=lambda r: -r["weight"])
    top1 = by_w[0] if by_w else None
    top2 = sum(r["weight"] for r in by_w[:2])
    # 「高位重仓」按排名给不同措辞：只有第一名能说「占比最大」
    for i, r in enumerate(by_w):
        if r.get("dgt") != "高位重仓":
            continue
        if i == 0:
            r["advice"] = ("停投已生效。占比最大 + 估值最贵 + 没有新钱摊薄，三条同时成立；"
                           "回本需涨 %.0f%%" % r["need"])
        else:
            r["advice"] = ("权重 %.1f%%，与第一位合计 %.1f%%，同样处在停投区、没有新钱摊薄；"
                           "回本需涨 %.0f%%，减不减取决于你是否接受这个集中度" % (r["weight"], top2, r["need"]))
    stop_mv = sum(r["amount"] for r in live if r["f"]["pct"] is not None and r["f"]["pct"] > 47)
    stop_share = stop_mv / total_mv * 100 if total_mv else 0
    # 亏损贡献
    losers = sorted([r for r in live if r["pnl"] < 0], key=lambda r: r["pnl"])
    lose_sum = -sum(r["pnl"] for r in losers) or 1
    # 账户闲置预算
    idle = []
    for a in accounts:
        cap = a.get("weekly_budget_cap") or 0
        used = sum(f["week"] for f in funds if f["account"] == a["id"])
        idle.append({"id": a["id"], "name": a.get("name", ""), "cap": cap,
                     "used": used, "left": cap - used})
    idle_total = sum(max(0, x["left"]) for x in idle)
    cheap = [r for r in live if r["f"]["pct"] is not None and r["f"]["pct"] <= 22]
    cheap_week = sum(r["f"]["week"] for r in cheap)
    cheap_mv = sum(r["amount"] for r in cheap)
    week_total = sum(f["week"] for f in funds)
    # 权益占比：按净值缓存里的基金类型判，含「债/货币」才算非权益
    bond = [f for f in funds
            if any(k in ((hm.get(f["code"]) or {}).get("type") or "") for k in ("债", "货币"))]
    eq_n = len(funds) - len(bond)

    h = []
    h.append('<h2><span class="n">02</span>持仓评估与建议</h2>')
    h.append('<p class="note">口径：市值与成本价取 <b>%s</b>（净值日 %s），分位与档位取本周快照。'
             '判断只用两个可复算的量——<b>仓位权重</b>与<b>估值分位</b>；主题归类来自基金名称与'
             '合同业绩基准，<b>不做持仓穿透</b>，所以「同质化」只能算到指数层面。'
             '下面每条建议都带了数字或触发条件，不写「建议关注」这类无法验证的话。</p>'
             % (esc(hold["file"]), esc(hold["nav_date"] or "-")))

    # ---- 三条结论 ----
    h.append('<div class="cons">')
    if top1:
        cls = "bad" if (top1["f"]["pct"] is not None and top1["f"]["pct"] > 47) else "warn"
        pct_top = ("%.1f%%" % top1["f"]["pct"]) if top1["f"]["pct"] is not None else "无分位"
        h.append('<div class="%s"><div class="t">最大风险</div>'
                 '<div class="v">%s 占 %.1f%%</div>'
                 '<div class="d">分位 %s（%s 档）、浮亏 %.1f%%，回本需涨 %.0f%%。'
                 '它一只贡献了 %.0f%% 的浮亏——组合涨跌基本由它决定，而且现在没有新钱能摊薄。</div></div>'
                 % (cls, esc(top1["f"]["name"][:12]), top1["weight"], pct_top,
                    esc(top1["f"]["tier"]), top1["pnl_pct"], top1["need"],
                    (-top1["pnl"] / lose_sum * 100) if top1["pnl"] < 0 else 0))
    else:
        h.append('<div class="mute"><div class="t">最大风险</div><div class="v">无可用市值</div>'
                 '<div class="d">持仓文件里没有可核算的市值，先补金额与成本价。</div></div>')
    if idle_total > 0:
        h.append('<div class="warn"><div class="t">钱没花对</div>'
                 '<div class="v">闲置 %s 元/周</div>'
                 '<div class="d">%s。同期分位 ≤22%% 的资产只有 %d 只、占 %.1f%% 市值、本周拿到 %s 元。'
                 '预算闲置不是因为没钱，是因为便宜的不在名单上。</div></div>'
                 % (money(idle_total),
                    "、".join("%s 账户预算 %s 只用 %s" % (x["id"], money(x["cap"]), money(x["used"]))
                             for x in idle if x["left"] > 0),
                    len(cheap), cheap_mv / total_mv * 100 if total_mv else 0, money(cheap_week)))
    h.append('<div class="neutral"><div class="t">结构</div>'
             '<div class="v">停投区占 %.0f%% 市值</div>'
             '<div class="d">分位 &gt;47%% 的标的合计 %s 元，前二权重 %.1f%%；%d 只为权益类，'
             '债/货币 %d 只。想加仓只能靠分位回落，不是靠加钱。</div></div>'
             % (stop_share, money(stop_mv), top2, eq_n, len(bond)))
    h.append('</div>')

    # ---- 逐只诊断 ----
    h.append('<h3>逐只诊断</h3>')
    h.append('<table><thead><tr><th>基金</th><th class="num">权重</th><th class="num">浮盈亏</th>'
             '<th class="num">分位</th><th>诊断</th><th>建议</th></tr></thead><tbody>')
    for r in sorted(rows, key=lambda x: -(x["weight"] if x["weight"] is not None else -1)):
        f = r["f"]
        w = ("%.1f%%" % r["weight"]) if r["weight"] is not None else "—"
        if r["ok"]:
            # A 股习惯：红 = 盈利、绿 = 亏损
            pnl = '<span style="color:%s">%s<br><span class="src">%.1f%%</span></span>' % (
                "var(--warn)" if r["pnl"] >= 0 else "var(--buy)", money(r["pnl"]), r["pnl_pct"])
        else:
            pnl = '<span class="src">待补</span>'
        pct = ("%.1f%%" % f["pct"]) if f["pct"] is not None else "—"
        tier = ('<span class="tier t-%s">%s</span>' % (esc(f["tier"]), esc(f["tier"]))
                if f["tier"] and f["tier"] != "-" else '<span class="tier t--">-</span>')
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s %s</td>'
                 '<td><span class="dg dg-%s">%s</span></td>'
                 '<td class="src" style="white-space:normal">%s</td></tr>'
                 % (esc(f["name"]), w, pnl, pct, tier, r["dg"], r["dgt"], esc(r["advice"])))
    h.append('</tbody></table>')
    h.append('<p class="note">浮盈亏按 A 股习惯配色：<b>红 = 盈利、绿 = 亏损</b>；分位标尺里的绿色含义不同，'
             '那是「分位 ≤22%、估值便宜」。权重按账户内市值占比算，B 账户两只暂无市值故为「—」。</p>')

    # ---- 两个方案 ----
    cheap_low = sorted([r for r in cheap if r["weight"] < 5], key=lambda r: r["weight"])
    raise_base = cheap_low[0] if cheap_low else None
    a_raise = raise_base["f"]["week"] if raise_base else 0
    b_add = 150 if len(idle) > 1 else 0
    new_week = week_total + a_raise + b_add
    new_cheap = cheap_week + a_raise
    h.append('<h3>两个可执行方案</h3>')
    h.append('<p class="note">A 只动新钱，存量不动，随时可停；B 要动存量，需要更高确信。'
             '右边的动作要你自己判断是否执行，本页只负责把条件和幅度算清楚。</p>')
    h.append('<table><thead><tr><th style="width:22%">项目</th>'
             '<th>方案 A · 只调新钱（先做这个）</th><th>方案 B · 再动存量（条件触发）</th>'
             '</tr></thead><tbody>')
    a_rows = []
    a_rows.append(("账户预算",
                   "A 账户预算 %s 只用 %s，闲置 %s：要么把 cap 降到实际投入，"
                   "要么把闲置记为「低估加仓储备」，等分位下移一次性投"
                   % (money(idle[0]["cap"]), money(idle[0]["used"]), money(max(0, idle[0]["left"])))
                   if idle else "—",
                   "不动预算，只改配置口径"))
    if raise_base:
        a_rows.append(("给低估的加 base",
                       "%s 分位 %.1f%%、权重 %.1f%%：base %d → %d，周投 %s → %s（额度还剩 %s）"
                       % (raise_base["f"]["name"][:10], raise_base["f"]["pct"], raise_base["weight"],
                          raise_base["f"]["base_w"], raise_base["f"]["base_w"] * 2,
                          money(raise_base["f"]["week"]), money(raise_base["f"]["week"] * 2),
                          money(max(0, (raise_base["f"]["pool"] or 0) - (raise_base["f"]["new"] or 0)))),
                       "不涉及"))
    if len(idle) > 1:
        b_acct = idle[1]
        a_rows.append(("B 账户预算不够",
                       "预算 %s 全给分位最低那只（S 档要 %s），其余 B 档被挤成 0：cap 提到 %s 才能让 B 档落地"
                       % (money(b_acct["cap"]),
                          money(sum((f.get("base_w") or 0) * 4 for f in funds
                                    if f["account"] == b_acct["id"] and f["pct"] is not None
                                    and f["pct"] <= 3) or 0),
                          money(b_acct["cap"] + 150)),
                       "不涉及"))
    if top1:
        cut = top1["amount"] / 3
        a_rows.append(("处置高位重仓",
                       "不减仓，只设条件：分位涨过 70%%（E 档）或净值回到成本 %.4f（+%.0f%%）时再决定"
                       % (top1["cost"], top1["need"]),
                       "减 1/3 ≈ %s 元，转入分位 ≤22%% 的两只；单只上限设 30%%，"
                       "当前 %.1f%% 需减约 %s 元"
                       % (money(cut), top1["weight"],
                          money(max(0, top1["amount"] - total_mv * 0.3)))))
    for item, a_txt, b_txt in a_rows:
        h.append('<tr><td>%s</td><td class="src" style="white-space:normal">%s</td>'
                 '<td class="src" style="white-space:normal">%s</td></tr>'
                 % (esc(item), esc(a_txt), esc(b_txt)))
    h.append('</tbody></table>')
    h.append('<p class="note">方案 A 落地后周投从 %s 元升到约 %s 元，其中分位 ≤22%% 的部分从 %s 元升到约 %s 元——'
             '加的是便宜资产，不是把预算摊平。这不是收益预测，只是把「钱去哪」算清楚。</p>'
             % (money(week_total), money(new_week), money(cheap_week), money(new_cheap)))
    return h


# ---------- 主体 ----------

def build(cfg, ledger, weeks, snap=None, hold=None):
    rules = cfg["tier_rules"]
    accounts = cfg["accounts"]
    total_cap = sum(a.get("total_capital", 0) for a in accounts)

    # 每只基金的最新记录
    latest = {}
    for r in ledger:
        latest[(r["account"], r["fund_code"])] = r
    # 每只基金的累计
    cum = {}
    for r in ledger:
        cum[(r["account"], r["fund_code"])] = r["cumulative"]
    base_inv = {}
    for f in cfg["funds"]:
        base_inv[(f["account"], f["code"])] = f.get("invested", 0)

    # 本轮分位快照优先（含本周未投的标的），没快照才退回台账记录
    snap_map = {}
    if snap:
        for s in snap.get("funds", []):
            snap_map[(s.get("account"), s.get("code"))] = s

    last_date = max([r["run_date"] for r in ledger], default=time.strftime("%Y-%m-%d"))
    week_rows = [r for r in ledger if r["run_date"] == last_date]

    funds = []
    for f in cfg["funds"]:
        key = (f["account"], f["code"])
        rec = latest.get(key)
        s = snap_map.get(key)
        bi = base_inv.get(key, 0)
        if s:
            pct = s.get("pct")
            pe = s.get("pe")
            week_v = (s.get("done", 0) or 0) + (s.get("alloc", 0) or 0)
            tier_lv = s.get("tier") or "-"
            src = s.get("src", "-")
            proxy = s.get("index_proxy")
            cum_v = s.get("cum_total") or (s.get("invested", 0) or 0) + (s.get("alloc", 0) or 0)
            new_v = s.get("new_total")
            if new_v is None:
                new_v = (s.get("new_sum", 0) or 0) + (s.get("alloc", 0) or 0)
        else:
            pct = rec["percentile"] if rec else None
            pe = rec["pe"] if rec else None
            week_v = rec["actual"] if rec else 0
            t = tier_of(pct, rules) if pct is not None else None
            tier_lv = t["level"] if t else "-"
            src = "-"
            proxy = f.get("index_proxy")
            cum_v = cum.get(key, bi)
            new_v = max(0, cum_v - bi)
        funds.append({
            "code": f["code"], "name": f["name"], "short": f["name"][:10],
            "account": f["account"], "index": f.get("index_code", ""),
            "pe": pe, "pct": pct, "tier": tier_lv, "src": src, "proxy": proxy,
            "week": week_v, "cum": cum_v, "pool": f.get("pool", 0) or 1,
            "base_inv": bi, "new": new_v,
            "base_w": f.get("base_weekly", 0),
        })

    week_total = sum(f["week"] for f in funds)
    cum_total = sum(f["cum"] for f in funds)
    use_rate = cum_total / total_cap * 100 if total_cap else 0
    pcts = [f["pct"] for f in funds if f["pct"] is not None]
    avg_pct = sum(pcts) / len(pcts) if pcts else 0

    # 告警
    alerts = []
    seen_idx = {}
    for f in funds:
        if not f["index"]:
            continue
        seen_idx.setdefault(f["index"], []).append(f["name"])
    for ic, names in seen_idx.items():
        if len(names) > 1:
            alerts.append(("重复暴露", "%s 被 %d 只基金跟踪：%s" % (ic, len(names), "、".join(names)),
                           "同一风险押两次，建议合并或把 pool 合计控在单指数上限内"))
    for f in funds:
        if f["pct"] is None:
            alerts.append(("无估值分位", f["name"] + " 未取到对应指数估值",
                           "本周不分配，但不代表不该买。补法：在 dca_plan.json 里给这只加 "
                           "manual_percentile 字段手工填分位值，重跑即恢复档位"))
        if f["pct"] is not None and f["pct"] > 47:
            alerts.append(("停投", f["name"] + " 分位 %.1f%%" % f["pct"], "高于停投线，只持有不再买入"))
        if f["new"] / f["pool"] > 0.9:
            alerts.append(("新增额度将尽", f["name"] + " 已用 %.0f%%" % (f["new"] / f["pool"] * 100),
                           "该基金在本账户的加仓额度快用完，下档需等估值下移"))

    # ---- HTML ----
    css = """
/* 三套主题：night 暗夜（默认） / paper 纸感 / plain 简报。
   颜色全部走变量，SVG 内的 fill/stroke 也用 var()，换主题不需要重画图。 */
:root,[data-theme="night"]{--bg:#0E1114;--surface:#161B21;--surface2:#1B222A;
--ink:#E9E6DF;--ink2:#A9A69F;--ink3:#787670;
--line:#242C34;--line2:#3A434E;--brand:#7FA8C4;
--buy:#5BBA8C;--warn:#E2796A;--amber:#D9A94F;--track:#232B34;
--band1:rgba(91,186,140,.20);--band2:rgba(91,186,140,.11);--band3:rgba(233,230,223,.045);
--band4:rgba(217,169,79,.13);--band5:rgba(226,121,106,.15);
--tag-good-bg:rgba(91,186,140,.16);--tag-good-fg:#79CDA3;
--tag-neutral-bg:rgba(233,230,223,.09);--tag-neutral-fg:#BCB8AF;
--tag-amber-bg:rgba(217,169,79,.16);--tag-amber-fg:#E2B968;
--tag-bad-bg:rgba(226,121,106,.16);--tag-bad-fg:#EC9482;
--tag-mute-bg:rgba(233,230,223,.06);--tag-mute-fg:#807D76;
--alert-bg:rgba(226,121,106,.09);--alert-line:rgba(226,121,106,.3);--alert-fg:#D9A79C}
[data-theme="paper"]{--bg:#F5F3EE;--surface:#FFF;--surface2:#FBFAF6;
--ink:#1B1A17;--ink2:#5B5750;--ink3:#8A857C;
--line:#E4DFD5;--line2:#D0C9BB;--brand:#1F3A4D;
--buy:#1E6B4A;--warn:#9C2A20;--amber:#8A6410;--track:#EFEBE2;
--band1:#DCEBE3;--band2:#EAF1EC;--band3:#F0EDE6;--band4:#F6E8DA;--band5:#F8E5E2;
--tag-good-bg:#E4F0EA;--tag-good-fg:#0F5A3C;
--tag-neutral-bg:#F1EEE6;--tag-neutral-fg:#5B5750;
--tag-amber-bg:#FAF0DC;--tag-amber-fg:#8A6410;
--tag-bad-bg:#F8E6E3;--tag-bad-fg:#9C2A20;
--tag-mute-bg:#EFECE5;--tag-mute-fg:#8A857C;
--alert-bg:#FBF0EE;--alert-line:#EDD6D2;--alert-fg:#7A4A43}
[data-theme="plain"]{--bg:#FFF;--surface:#FFF;--surface2:#F7F7F7;
--ink:#111;--ink2:#3E3E3E;--ink3:#828282;
--line:#E1E1E1;--line2:#9E9E9E;--brand:#000;
--buy:#0F7A45;--warn:#B3261E;--amber:#7A5B0E;--track:#EEEEEE;
--band1:#E7F2EC;--band2:#F1F7F4;--band3:#F5F5F5;--band4:#FBF1E1;--band5:#FBE8E5;
--tag-good-bg:#E7F2EC;--tag-good-fg:#0B5E38;
--tag-neutral-bg:#F2F2F2;--tag-neutral-fg:#555;
--tag-amber-bg:#FBF1DC;--tag-amber-fg:#7A5B0E;
--tag-bad-bg:#FBE8E5;--tag-bad-fg:#9C1F16;
--tag-mute-bg:#F0F0F0;--tag-mute-fg:#888;
--alert-bg:#FDF2F0;--alert-line:#F0D5D0;--alert-fg:#8A4038}
/* 简报风：直角、更硬的横线、无卡片底色，接近打印稿 */
[data-theme="plain"] .kpi,[data-theme="plain"] .acc,[data-theme="plain"] .chartbox,
[data-theme="plain"] .cons>div,[data-theme="plain"] .alert,[data-theme="plain"] .themebar{border-radius:0}
[data-theme="plain"] header{border-bottom-width:3px}
[data-theme="plain"] th{border-bottom:2px solid var(--ink);color:var(--ink2)}
[data-theme="plain"] .themebar{box-shadow:none}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:920px;margin:0 auto;padding:44px 26px 72px}
.serif{font-family:Georgia,"Songti SC","SimSun",serif}
header{border-bottom:2px solid var(--ink);padding-bottom:20px}
.kicker{font-size:11px;letter-spacing:.18em;color:var(--ink3);text-transform:uppercase;margin-bottom:8px}
h1{font-size:27px;font-weight:400;margin:0 0 8px;line-height:1.3}
.sub{font-size:13.5px;color:var(--ink2);margin:0}
.meta{font-size:11.5px;color:var(--ink3);margin-top:12px;display:flex;gap:18px;flex-wrap:wrap}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:11px;margin:22px 0 6px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.kpi .l{font-size:10.5px;color:var(--ink3);letter-spacing:.05em;margin-bottom:5px}
.kpi .v{font-size:21px;font-weight:500;line-height:1.15;letter-spacing:-.02em}
.kpi .h{font-size:10.5px;color:var(--ink3);margin-top:3px}
h2{font-size:18px;font-weight:400;margin:38px 0 4px;letter-spacing:-.01em}
h2 .n{color:var(--ink3);font-size:12px;letter-spacing:.1em;margin-right:9px;vertical-align:1px}
h3{font-size:13.5px;font-weight:600;margin:22px 0 2px;color:var(--ink)}
.note{font-size:12.5px;color:var(--ink3);margin:6px 0 0}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:12.5px;background:var(--surface)}
th{text-align:left;font-weight:600;font-size:11px;color:var(--ink3);letter-spacing:.04em;
padding:8px 10px;border-bottom:1.5px solid var(--line2);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--line);color:var(--ink2)}
td:first-child{color:var(--ink);font-weight:500}
.num{text-align:right;font-variant-numeric:tabular-nums}
.src{font-size:11px;color:var(--ink3);white-space:nowrap}
.idx{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--ink3);white-space:nowrap}
.acc{background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin:12px 0;border-left:3px solid var(--brand)}
.acc__h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;flex-wrap:wrap;gap:8px}
.acc__t{font-size:14.5px;font-weight:600}
.acc__m{font-size:11.5px;color:var(--ink3)}
.bar{height:7px;background:var(--track);border-radius:4px;overflow:hidden;margin:8px 0 4px}
.bar>i{display:block;height:7px;background:var(--brand);border-radius:4px}
.bar.buy>i{background:var(--buy)}
.mini{height:5px;background:var(--track);border-radius:3px;overflow:hidden;width:88px;display:inline-block;vertical-align:middle}
.mini>i{display:block;height:5px;background:var(--buy);min-width:2px}
.tier{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;font-weight:600}
.t-S,.t-A,.t-A\\+{background:var(--tag-good-bg);color:var(--tag-good-fg)}
.t-B{background:var(--tag-neutral-bg);color:var(--tag-neutral-fg)}
.t-C{background:var(--tag-amber-bg);color:var(--tag-amber-fg)}
.t-D,.t-E{background:var(--tag-bad-bg);color:var(--tag-bad-fg)}
.t--{background:var(--tag-mute-bg);color:var(--tag-mute-fg)}
.dg{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:4px;font-weight:600;white-space:nowrap}
.dg-good{background:var(--tag-good-bg);color:var(--tag-good-fg)}
.dg-neutral{background:var(--tag-neutral-bg);color:var(--tag-neutral-fg)}
.dg-warn{background:var(--tag-amber-bg);color:var(--tag-amber-fg)}
.dg-bad{background:var(--tag-bad-bg);color:var(--tag-bad-fg)}
.dg-mute{background:var(--tag-mute-bg);color:var(--tag-mute-fg)}
.cons{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0 4px}
.cons>div{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--line2);
border-radius:8px;padding:12px 14px}
.cons>div.bad{border-left-color:var(--warn)}
.cons>div.warn{border-left-color:var(--amber)}
.cons>div.good{border-left-color:var(--buy)}
.cons .t{font-size:11px;letter-spacing:.06em;color:var(--ink3);margin-bottom:5px}
.cons .v{font-size:13px;font-weight:600;line-height:1.45;margin-bottom:5px}
.cons .d{font-size:11.5px;color:var(--ink2);line-height:1.6}
.chartbox{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 12px 6px}
.themebar{position:fixed;top:14px;right:14px;z-index:60;display:flex;align-items:center;gap:2px;
background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:3px 5px;
box-shadow:0 2px 10px rgba(0,0,0,.18)}
.themebar span{font-size:10px;color:var(--ink3);padding:0 4px 0 3px;letter-spacing:.08em}
.themebar button{font:inherit;font-size:11px;border:0;background:transparent;color:var(--ink3);
padding:3px 8px;border-radius:14px;cursor:pointer;line-height:1.4}
.themebar button:hover{color:var(--ink)}
.themebar button.on{background:var(--ink);color:var(--bg)}
.alert{background:var(--alert-bg);border:1px solid var(--alert-line);border-radius:9px;padding:12px 15px;margin:10px 0}
.alert .t{font-weight:600;color:var(--warn);font-size:12.5px;margin-bottom:2px}
.alert .d{font-size:12px;color:var(--alert-fg)}
svg{display:block;width:100%;height:auto}
footer{margin-top:46px;padding-top:16px;border-top:1px solid var(--line2);
font-size:11px;color:var(--ink3);line-height:1.75}
@media(max-width:720px){.wrap{padding:28px 16px 52px}.kpis{grid-template-columns:1fr 1fr}
.cons{grid-template-columns:1fr}
h1{font-size:22px}table{font-size:11.5px}th,td{padding:7px 6px}
.themebar{top:auto;bottom:12px;right:12px}}
/* 打印一律走浅色；选择器要与主题块同特异度且靠后，否则被 :root 覆盖不住 */
@media print{html[data-theme]{--bg:#fff;--surface:#fff;--surface2:#fff;--ink:#000;--ink2:#333;
--ink3:#666;--line:#ccc;--line2:#888;--track:#eee;--brand:#000;
--band1:#E7F2EC;--band2:#F1F7F4;--band3:#F5F5F5;--band4:#FBF1E1;--band5:#FBE8E5;
--alert-bg:#FDF2F0;--alert-line:#E0C6C1;--alert-fg:#8A4038}
body{background:#fff}.wrap{max-width:none;padding:0}
table,.acc,.cons>div{break-inside:avoid}
.themebar{display:none}}
"""

    h = []
    h.append('<!DOCTYPE html><html lang="zh-CN" data-theme="night"><head><meta charset="UTF-8">')
    h.append('<meta name="viewport" content="width=device-width,initial-scale=1.0">')
    h.append('<meta name="color-scheme" content="dark light">')
    h.append('<title>定投台账 %s</title>' % esc(last_date))
    h.append('<style>%s</style></head><body>' % css)
    h.append('<div class="themebar"><span>风格</span>'
             '<button type="button" data-t="night">暗夜</button>'
             '<button type="button" data-t="paper">纸感</button>'
             '<button type="button" data-t="plain">简报</button></div>')
    h.append('<div class="wrap">')

    # header
    h.append('<header><div class="kicker">定投执行台账 · DCA Ledger</div>')
    h.append('<h1 class="serif">多账户基金定投 · 执行记录</h1>')
    h.append('<p class="sub">每周按估值分位落档，账户内按分位优先分配预算；每只设资金池天花板防止低位超配</p>')
    h.append('<div class="meta"><span>记录日 %s</span><span>数据日 %s</span><span>账户 %d · 基金 %d</span></div>'
             % (esc(last_date), esc(week_rows[0]["data_date"] if week_rows else "-"),
                len(accounts), len(funds)))
    h.append('</header>')

    # KPI
    h.append('<div class="kpis">')
    h.append('<div class="kpi"><div class="l">本周投入</div><div class="v">%s</div><div class="h">本周记录合计</div></div>' % money(week_total))
    h.append('<div class="kpi"><div class="l">累计投入</div><div class="v">%s</div><div class="h">含台账全部记录</div></div>' % money(cum_total))
    h.append('<div class="kpi"><div class="l">资金使用率</div><div class="v">%.1f%%</div><div class="h">累计 / 总资金 %s</div></div>'
             % (use_rate, money(total_cap)))
    h.append('<div class="kpi"><div class="l">平均估值分位</div><div class="v">%.1f%%</div><div class="h">%d 只基金简单平均</div></div>'
             % (avg_pct, len(pcts)))
    h.append('</div>')

    # 01 本周执行
    h.append('<h2><span class="n">01</span>本周执行</h2>')
    h.append('<p class="note">账户预算互相独立、不可挪用；同一账户内按估值分位从低到高分配，最贵的先砍。'
             '「档」是分位落档的结果，各档对应的系数与周投额见「估值分位位置」节的档位表。</p>')
    for a in accounts:
        af = [f for f in funds if f["account"] == a["id"]]
        used = sum(f["week"] for f in af)
        cap = a.get("weekly_budget_cap") or 0
        base = a.get("weekly_budget_base") or 0
        ratio = min(100, used / cap * 100) if cap else 0
        h.append('<div class="acc"><div class="acc__h"><span class="acc__t">%s · %s</span>'
                 '<span class="acc__m">资金池 %s · 周预算 %d（上限 %d）</span></div>'
                 % (esc(a["id"]), esc(a.get("name", "")), money(a.get("total_capital", 0)), base, cap))
        h.append('<div class="bar buy"><i style="width:%.1f%%"></i></div>' % ratio)
        h.append('<div class="acc__m">本周已用 <b>%s</b> 元 · 结余 %s 元</div>'
                 % (money(used), money(cap - used)))
        if af:
            h.append('<table><thead><tr><th>基金</th><th class="num">PE</th><th class="num">分位</th>'
                     '<th>档</th><th>数据源</th><th class="num">本周投</th>'
                     '<th class="num">新增/额度</th></tr></thead><tbody>')
            for f in sorted(af, key=lambda x: (x["pct"] if x["pct"] is not None else 999)):
                src = f.get("src") or "-"
                h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                         '<td><span class="tier t-%s">%s</span></td><td class="src">%s</td>'
                         '<td class="num">%s</td><td class="num">%s/%s</td></tr>'
                         % (esc(f["name"]), "%.2f" % f["pe"] if f["pe"] else "-",
                            "%.1f%%" % f["pct"] if f["pct"] is not None else "-",
                            esc(f["tier"]), esc(f["tier"]), esc(src), money(f["week"]),
                            money(f["new"]), money(f["pool"])))
            h.append('</tbody></table>')
        else:
            h.append('<div class="acc__m">该账户暂无基金</div>')
        h.append('</div>')

    # 02 持仓评估与建议
    h.extend(assess(funds, hold, accounts, rules))

    # 03 估值分位
    if funds:
        h.append('<h2><span class="n">03</span>估值分位位置</h2>')
        h.append('<p class="note">色带与档位一一对应：<b>绿 ≤22%</b> 偏低可加码 · <b>米 22–47%</b> 中性减速 · '
                 '<b>橙 47–70%</b> 偏贵停投 · <b>红 &gt;70%</b> 高估。分位窗口自 2016-07 起约 10.3 年，'
                 '不含 2015 年那轮泡沫，所以严格说这是「2016-07 以来分位」而非「历史分位」。</p>')
        h.append('<div class="chartbox">')
        h.append(svg_percentile(funds))
        h.append('</div>')

        # 档位说明：只给徽标不给换算，读者无法自己复核金额
        h.append('<h3>档位怎么换算成周投额</h3>')
        h.append('<p class="note">档位由当前分位唯一决定，周投额 = 该基金的 <b>base_weekly</b> × 档位系数。'
                 'base_weekly 是「B 档时每周投多少」，由资金池 ÷ 计划投入周数定，所以<b>同为 B 档的两只基金，'
                 '绝对金额并不可比</b>。资金池上限是该档最多能动用本基金池子的比例，分位越低允许动用的越多，'
                 '这是「越跌越有钱买」的机制来源。</p>')
        h.append(tier_table(rules, funds))
        dup_levels = {}
        for r in rules:
            dup_levels.setdefault(r["level"], []).append(r)
        split = [lv for lv, rs in dup_levels.items() if len(rs) > 1]
        note = ['<b>- 徽标</b>表示这只没有取到分位数据，本周不分配——是「不知道」，不是「不该买」，'
                '补法见下方代理说明与告警节。',
                '<b>停投 ≠ 清仓</b>：D/E 档只是停止买入，已有持仓继续持有，卖出走单独的止盈规则。']
        if split:
            note.append('<b>%s 分了两段</b>：同一徽标下系数不同，所以两只都显示 %s 的基金，'
                        '周投额可以差一倍以上，要看分位具体落在哪一段。'
                        % ("、".join(split), split[0]))
        note.append('这张表的分档阈值、系数、资金池上限都可以改（配置里的 <b>tier_rules</b>），'
                    '改完重跑，表格与分配金额会一起同步，不存在「文档写一套、脚本算一套」。')
        for n_ in note:
            h.append('<p class="note">· %s</p>' % n_)

        # 代理指数说明：分位是按代理指数算的，必须让读者看见用的是哪一只
        proxied = [f for f in funds if f.get("proxy")]
        if proxied:
            h.append('<p class="note" style="margin-top:16px">下面这些基金没有对应的指数估值，'
                     '分位是用<b>代理指数</b>算的，可信度按代理关系的紧密程度打折：</p>')
            h.append('<table><thead><tr><th>基金</th><th>合同业绩基准</th>'
                     '<th>实际使用</th><th>代理说明</th></tr></thead><tbody>')
            for f in proxied:
                px = f["proxy"] or {}
                used = f["index"] or "无（本周不分配）"
                h.append('<tr><td>%s</td><td class="src">%s</td><td class="idx">%s</td>'
                         '<td class="src" style="white-space:normal">%s</td></tr>'
                         % (esc(f["name"]), esc(px.get("actual", "-")),
                            esc(used), esc(px.get("note", ""))))
            h.append('</tbody></table>')

    # 04 持仓与天花板
    h.append('<h2><span class="n">04</span>持仓与新增额度使用</h2>')
    h.append('<p class="note">「历史持仓」是启用台账之前的存量成本，不占新增额度；'
             '「新增/额度」逼近 100% 说明这只基金在本账户的加仓弹药快用完，下档要靠估值下移才会打开。</p>')
    h.append('<table><thead><tr><th>基金</th><th class="num">历史持仓</th><th class="num">新增累计</th>'
             '<th class="num">新增额度</th><th>已用率</th><th class="num">剩余</th></tr></thead><tbody>')
    for f in sorted(funds, key=lambda x: -x["new"]):
        r = f["new"] / f["pool"] * 100
        color = "var(--warn)" if r > 85 else ("var(--amber)" if r > 60 else "var(--buy)")
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td><span class="mini"><i style="width:%.0f%%;background:%s"></i></span> <span class="num">%.0f%%</span></td>'
                 '<td class="num">%s</td></tr>'
                 % (esc(f["name"]), money(f["base_inv"]), money(f["new"]), money(f["pool"]),
                    min(100, r), color, r, money(max(0, f["pool"] - f["new"]))))
    h.append('</tbody></table>')

    # 05 累计曲线
    initial_total = sum(f.get("invested", 0) for f in cfg["funds"])
    cur_svg = svg_cumulative(ledger, initial_total)
    h.append('<h2><span class="n">05</span>累计投入曲线</h2>')
    if cur_svg:
        h.append('<p class="note">含启用本台账前的历史持仓基数 %s 元，之后按每周记录累加。'
                 '曲线突然变陡 = 某周发生了超常投入，值得回看当时的判断依据。</p>' % money(initial_total))
        h.append('<div class="chartbox">')
        h.append(cur_svg)
        h.append('</div>')
    else:
        _days = len(set(r.get("run_date", "") for r in ledger))
        h.append('<p class="note">台账目前只有 %d 个记录日，至少需要两周才能画出趋势。'
                 '起点基数 %s 元（启用台账前的历史持仓成本），之后每周按 actual 累加。</p>'
                 % (_days, money(initial_total)))

    # 06 告警
    h.append('<h2><span class="n">06</span>告警与检查</h2>')
    if alerts:
        for t, d, tip in alerts:
            h.append('<div class="alert"><div class="t">%s · %s</div><div class="d">%s</div></div>'
                     % (esc(t), esc(d), esc(tip)))
    else:
        h.append('<p class="note">无重复暴露、无停投标的、无逼近天花板的持仓。</p>')

    # 07 下一次档位切换
    h.append('<h2><span class="n">07</span>下一次档位切换点</h2>')
    h.append('<p class="note">只报金额不报触发条件等于没给结论。下表给出改变本周判断的临界分位：'
             '<b>升档</b> = 分位跌到该值以下就加码，<b>降档</b> = 分位涨过该值就减速或停投。'
             '每只的周投额 = 该基金 base_weekly × 该档系数（系数表见「估值分位位置」节）。</p>')
    h.append('<table><thead><tr><th>基金</th><th class="num">当前分位</th><th>当前档</th>'
             '<th>升档触发</th><th>降档触发</th></tr></thead><tbody>')
    for f in sorted(funds, key=lambda x: (x["pct"] if x["pct"] is not None else 999)):
        tg = next_triggers(f["pct"], rules, f.get("base_w", 0))
        pct_txt = ("%.1f%%" % f["pct"]) if f["pct"] is not None else "-"
        if not tg:
            h.append('<tr><td>%s</td><td class="num">%s</td>'
                     '<td><span class="tier t--">-</span></td>'
                     '<td class="src" colspan="2">无分位数据，无法给出触发条件</td></tr>'
                     % (esc(f["name"]), pct_txt))
            continue
        up, down = tg
        up_txt = ("跌到 %.0f%% 以下 → %s %.1f× → %s 元/周" % up) if up else "已是最低档"
        down_txt = ("涨过 %.0f%% → %s %.1f× → %s 元/周" % down) if down else "已是最高档"
        h.append('<tr><td>%s</td><td class="num">%s</td>'
                 '<td><span class="tier t-%s">%s</span></td>'
                 '<td class="src" style="white-space:normal">%s</td>'
                 '<td class="src" style="white-space:normal">%s</td></tr>'
                 % (esc(f["name"]), pct_txt, esc(f["tier"]), esc(f["tier"]),
                    esc(up_txt), esc(down_txt)))
    h.append('</tbody></table>')

    # 08 历史台账
    h.append('<h2><span class="n">08</span>历史记录</h2>')
    h.append('<p class="note">最近 %d 条记录，倒序。完整数据见同目录 ledger.csv。</p>' % min(weeks * 4, len(ledger)))
    h.append('<table><thead><tr><th>周次</th><th>记录日</th><th>账户</th><th>基金</th>'
             '<th class="num">分位</th><th>档</th><th class="num">投入</th><th class="num">累计</th></tr></thead><tbody>')
    for r in list(reversed(ledger))[: weeks * 4]:
        rp = r["percentile"]
        pct_txt = ("%.1f%%" % rp) if rp is not None else "-"
        h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="num">%s</td>'
                 '<td><span class="tier t-%s">%s</span></td><td class="num">%s</td><td class="num">%s</td></tr>'
                 % (esc(r.get("iso_week", "")), esc(r.get("run_date", "")), esc(r.get("account", "")),
                    esc(r.get("fund_name", "")), pct_txt, esc(r.get("tier", "") or "-"),
                    esc(r.get("tier", "") or "-"), money(r["actual"]), money(r["cumulative"])))
    h.append('</tbody></table>')

    # footer
    h.append('<footer><b>口径</b>　估值分位来自蛋卷（雪球基金）指数估值，窗口自 2016-07 起约 10.3 年，'
             '不含 2015 年泡沫；PE 为 TTM 口径，跨指数不可直接用 PE 绝对值比较，只能比分位。'
             '台账按 ISO 自然周去重，同一周重复运行只记一次。<br><br>'
             '<b>说明</b>　本页为执行记录，不构成投资建议。累计投入 = 配置中的历史持仓基数 + 台账全部记录之和。'
             'actual 列可在 ledger.csv 中手工修正，下次渲染即生效。<br><br>'
             '生成时间 %s · 单文件零依赖</footer>' % time.strftime("%Y-%m-%d %H:%M"))

    h.append('</div>')
    # 主题切换：纯内联，无外部依赖；禁用 JS 时停在 HTML 上的 data-theme="night"
    h.append('<script>(function(){var r=document.documentElement,'
             'b=[].slice.call(document.querySelectorAll(".themebar button"));'
             'function set(t){r.setAttribute("data-theme",t);'
             'b.forEach(function(x){x.className=(x.getAttribute("data-t")===t)?"on":""})}'
             'b.forEach(function(x){x.onclick=function(){set(x.getAttribute("data-t"));'
             'try{localStorage.setItem("dca-theme",x.getAttribute("data-t"))}catch(e){}}});'
             'try{var s=localStorage.getItem("dca-theme");if(s)set(s);else set("night")}catch(e){set("night")}'
             '})();</script></body></html>')
    return "".join(h)


def main():
    args = sys.argv[1:]
    base = os.path.dirname(os.path.abspath(__file__))

    def arg(name, default):
        return args[args.index(name) + 1] if name in args else default

    cfg_path = arg("--config", os.path.join(base, "dca_plan.json"))
    ledger_path = arg("--ledger", os.path.join(base, "定投记录", "ledger.csv"))
    weeks = int(arg("--weeks", "12"))
    out = arg("--out", "")

    cfg = load_config(cfg_path)
    ledger = load_ledger(ledger_path)
    if not ledger:
        print("台账为空，先运行 dca_weekly.py 生成记录")
        return 1
    snap = load_snapshot(ledger_path)

    hold = load_holdings(cfg_path, cfg)
    html = build(cfg, ledger, weeks, snap, hold)
    if not out:
        last = max(r["run_date"] for r in ledger)
        out = os.path.join(base, "定投台账_%s.html" % last)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成 %s（%.1f KB）" % (out, len(html.encode("utf-8")) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
