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
    """由系数与额度占用上限推出该档的动作含义，规则改了含义跟着变，不写死在表里。"""
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
        # 用修正后的档位归组，否则 PB 校验改过档的标的会显示在原始分位那一行
        lv = f.get("tier")
        i = (next((k for k, r in enumerate(rules) if r["level"] == lv), None)
             if lv and lv != "-" else rule_index(f.get("pct"), rules))
        if i is not None:
            hits.setdefault(i, []).append(f.get("short") or f.get("name", ""))
    p = ['<table><thead><tr><th>档</th><th>分位区间</th><th class="num">系数</th>'
         '<th class="num">额度占用上限</th><th>动作</th><th>本周落此档</th></tr></thead><tbody>']
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
    parts = ['<svg viewBox="0 0 700 %d" role="img" aria-label="各基金估值分位标尺">' % h]
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
        # PB 分位：空心方点，与 PE 分位差 ≥20pct 时用醒目色提示这一档被交叉修正过
        pb = f.get("pb_pct")
        if pb is not None:
            px = left + bar_w * min(pb, 100) / 100.0
            off = abs(pb - pct) >= 20
            pcolor = "var(--ink)" if off else "var(--ink3)"
            # 两个分位之间画虚线相连：不相连时读者会把 PB 方点误认为相邻基金的标记
            parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" '
                         'stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>'
                         % (min(x, px), y, max(x, px), y, pcolor))
            parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="1" '
                         'stroke-dasharray="2 2"/>' % (px, y - 9, px, y + 9, pcolor))
            parts.append('<rect x="%.1f" y="%.1f" width="5" height="5" fill="none" stroke="%s" '
                         'stroke-width="1.3"/>' % (px - 2.5, y - 2.5, pcolor))
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="2"/>'
                     % (x, y - 9, x, y + 9, color))
        parts.append('<circle cx="%.1f" cy="%d" r="4" fill="%s"/>' % (x, y, color))
        # PE 与 PB 两个数值必须错开，否则「58.6%」和「PB 58.5%」会叠在一起
        if pb is not None:
            parts.append('<text x="%d" y="%d" font-size="11" fill="%s" font-weight="600" '
                         'text-anchor="end">%.1f%%</text>'
                         % (600, y + 4, color, pct))
            parts.append('<text x="%d" y="%d" font-size="10.5" fill="var(--ink3)" '
                         'text-anchor="end">PB %.1f%%</text>' % (700, y + 4, pb))
        else:
            parts.append('<text x="%d" y="%d" font-size="11.5" fill="%s" font-weight="600" '
                         'text-anchor="end">%.1f%%</text>' % (700, y + 4, color, pct))
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
        # 用快照里的「修正后系数」，否则 02 节会按原始 PE 分位判停投，
        # 与 01 节 PB 校验后的档位自相矛盾（同一只基金一处说投 50、一处说停投）
        factor = f.get("factor")
        if factor is None:
            factor = t["factor"] if t else 0
        bw = f.get("base_w") or 0
        room = (max(0, (f.get("pool") or 0) - (f.get("new") or 0))
                if f.get("pool") else None)
        if r["ok"]:
            r["weight"] = r["amount"] / acct_mv.get(f["account"], 1) * 100
        if not r["ok"]:
            r["dg"], r["dgt"] = "mute", "市值待补"
            r["advice"] = "缺当前市值或成本价，只能看分位、算不出盈亏；补齐后本节自动重算"
        elif pct is None:
            r["dg"], r["dgt"] = "mute", "无分位"
            r["advice"] = "没有分位就无法定档，不落档不是判断结论；补该指数的分位后再定"
        elif factor <= 0:
            if r["weight"] >= 15:
                r["dg"], r["dgt"] = "bad", "高位重仓"
                r["advice"] = ("停投已生效。占比最大 + 估值最贵 + 没有新钱摊薄，三条同时成立；"
                               "回本需涨 %.0f%%" % r["need"])
            elif r["pnl_pct"] <= -25:
                r["dg"], r["dgt"] = "bad", "深亏停投"
                r["advice"] = ("不加钱是对的，在贵的位置摊薄只会放大亏损；回本需涨 %.0f%%，"
                               "等分位（或 PB 分位）确认回落后再用 C 档接" % r["need"])
            else:
                r["dg"], r["dgt"] = "warn", "偏贵持有"
                r["advice"] = "停投持有，不加仓；PE 与 PB 分位同向回落即自动进 C 档（%.1f×）" % (
                    (tier_of(46.99, rules) or {}).get("factor", 0))
        elif factor >= 1.0:
            if r["weight"] < 5:
                r["dg"], r["dgt"] = "good", "低估轻仓"
                r["advice"] = ("钱该来这里：分位 %.1f%% 但只占 %.1f%%；"
                               "档位已允许加码，要加大只能抬平台侧的单期定投额" %
                               (pct, r["weight"]))
            else:
                r["dg"], r["dgt"] = "good", "低估重仓"
                r["advice"] = "维持现额；占比已达 %.1f%%，不再提高单一权重" % r["weight"]
        else:
            r["dg"], r["dgt"] = "neutral", "中性档"
            r["advice"] = "C 档（%.1f×）：减速维持，不加不减；档位不改善就不值得加码" % factor

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
    def _fac(r):
        v = r["f"].get("factor")
        if v is not None:
            return v
        t = tier_of(r["f"]["pct"], rules) if r["f"]["pct"] is not None else None
        return t["factor"] if t else 0

    stop_mv = sum(r["amount"] for r in live if r["f"]["pct"] is not None and _fac(r) <= 0)
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
    cheap = [r for r in live if r["f"]["pct"] is not None and _fac(r) >= 1.0]
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
             '下面每条建议都带了数字或触发条件，不写「建议关注」这类无法验证的话。'
             '<b>本节合计只含能算出盈亏的 %d 只</b>（缺市值或缺成本价的 %d 只不计入，'
             '它们的成本仍算进 KPI 的累计投入，所以两处数字会有差额）。</p>'
             % (esc(hold["file"]), esc(hold["nav_date"] or "-"),
                len(live), len(funds) - len(live)))
    _reop = [f for f in funds if f.get("reopen")]
    if _reop:
        h.append('<p class="note"><b>成本基准提示</b>：%s 这几只是此前清仓后重新开仓的，'
                 '成本价从重开日算起。所以它们的浮亏<b>不含清仓前那一段</b>——'
                 '拿它们的浮亏率与一直持有的基金横比，会低估真实亏损。'
                 '清仓时的盈亏当时就已实现，不该再摊到现在这批持仓上。</p>'
                 % "、".join(esc(f["name"]) for f in _reop))

    # ---- 三条结论 ----
    h.append('<div class="cons">')
    if top1:
        cls = "bad" if ((top1["f"].get("factor") if top1["f"].get("factor") is not None
                         else 1) <= 0) else "warn"
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
             '<div class="d">两锚一致判停投的标的合计 %s 元，前二权重 %.1f%%；%d 只为权益类，'
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
             '本表只给<b>触发条件与相对幅度</b>，<b>不给具体执行金额</b>——'
             '每只投多少由你自己决定，这份台账不替你下这个判断。</p>')
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
        # 只给相对幅度不给绝对金额：绝对值是用户的执行决策
        a_rows.append(("给低估的抬定投额",
                       "%s 分位 %.1f%%、权重仅 %.1f%%，档位（%s）已允许加码；"
                       "若决定加，方向是把平台侧单期定投额抬到 2 倍量级，绝对额自定"
                       % (raise_base["f"]["name"][:10], raise_base["f"]["pct"],
                          raise_base["weight"], raise_base["f"]["tier"]),
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
    # 每只基金的累计：按 actual 逐条累加，**不读 cumulative 列**
    # cumulative 是历史快照，写入时的 invested 基数可能已被后来的基金拆分改动
    #（例：013125 拆出独立的 160222 后，旧 cumulative 仍含那笔 34,190，直接读会重复计入）
    cum = {}
    for r in ledger:
        k = (r["account"], r["fund_code"])
        cum[k] = cum.get(k, 0) + (r.get("actual") or 0)
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
            pb_pct = s.get("pb_pct")
            tier_raw = s.get("tier_raw") or ""
            tier_note = s.get("tier_note") or ""
            week_v = (s.get("done", 0) or 0) + (s.get("alloc", 0) or 0)
            tier_lv = s.get("tier") or "-"
            src = s.get("src", "-")
            # src=手工 时分位来自自建组合或研报，与 index_code 的接口 PE 不是同一个东西。
            # 同一行并列会出现「PE 24.52 却在 13.5% 分位」这种自相矛盾，宁可留空。
            if src == "手工":
                pe = None
            proxy = s.get("index_proxy")
            cum_v = s.get("cum_total") or (s.get("invested", 0) or 0) + (s.get("alloc", 0) or 0)
            new_v = s.get("new_total")
            if new_v is None:
                new_v = (s.get("new_sum", 0) or 0) + (s.get("alloc", 0) or 0)
        else:
            pct = rec["percentile"] if rec else None
            pe = rec["pe"] if rec else None
            pb_pct = None
            tier_raw, tier_note = "", ""
            week_v = rec["actual"] if rec else 0
            t = tier_of(pct, rules) if pct is not None else None
            tier_lv = t["level"] if t else "-"
            src = "-"
            proxy = f.get("index_proxy")
            cum_v = bi + cum.get(key, 0)
            new_v = max(0, cum_v - bi)
        funds.append({
            "code": f["code"], "name": f["name"], "short": f["name"][:10],
            "account": f["account"], "index": f.get("index_code", ""),
            "pe": pe, "pct": pct, "tier": tier_lv, "src": src, "proxy": proxy,
            "pb_pct": pb_pct, "tier_raw": tier_raw, "tier_note": tier_note,
            "factor": (s or {}).get("factor") if s else None,
            "change": (s or {}).get("change", "") if s else "",
            "change_dir": (s or {}).get("change_dir", 0) if s else 0,
            "reopen": ((s or {}).get("reopen") if s else None) or f.get("reopen"),
            "note": f.get("note") or "",
            "week": week_v, "cum": cum_v, "pool": f.get("pool") or None,
            "base_inv": bi, "new": new_v,
            "base_w": f.get("base_weekly", 0),
        })

    week_total = sum(f["week"] for f in funds)
    cum_total = sum(f["cum"] for f in funds)
    use_rate = cum_total / total_cap * 100 if total_cap else 0
    # 当前市值只取持仓快照的真实数字，不叠加任何估算额度
    mv_now = sum((v.get("amount") or 0) for v in ((hold or {}).get("funds") or {}).values())
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
                           "同一风险押两次，建议合并成一只；若都留着，只让其中一只继续定投，其余停止新增"))
    for f in funds:
        if f["pct"] is None:
            alerts.append(("无估值分位", f["name"] + " 未取到对应指数估值",
                           "无法用分位定档，不代表不该买。补法：在 dca_plan.json 里给这只加 "
                           "manual_percentile 字段手工填分位值，重跑即恢复档位"))
        _fac_al = f.get("factor")
        if f["pct"] is not None and _fac_al is not None and _fac_al <= 0:
            alerts.append(("停投", f["name"] + " 分位 %.1f%%" % f["pct"], "高于停投线，只持有不再买入"))
        if f.get("pool") and f["new"] / f["pool"] > 0.9:
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
.tag{display:inline-block;font-size:10.5px;line-height:1.6;padding:1px 6px;border-radius:4px;
background:var(--tag-neutral-bg);color:var(--tag-neutral-fg);white-space:nowrap}
/* 这里的绿/红是估值颜色（绿=便宜可加码），不是涨跌；与 02 节盈亏的红涨绿跌含义相反 */
.upc{color:var(--buy);font-weight:600}
.dnc{color:var(--warn);font-weight:600}
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
    h.append('<header><div class="kicker">估值档位台账 · DCA Tier Ledger</div>')
    h.append('<h1 class="serif">基金档位评估 · 持仓台账</h1>')
    h.append('<p class="sub">只给档位、不给金额——投哪只、投多少由你自己决定。'
             'PE 分位定档，PB 分位做 ±1 档交叉校验；档位一旦变化会单独列出。</p>')
    # 三个日期必须分开写：记录日是本周已执行的那天，数据日是估值快照日，
    # 出具日是这一版页面的生成日——规则改动当天重渲染时前两者不变、只有它变
    h.append('<div class="meta"><span>出具日 %s</span><span>记录日 %s</span><span>数据日 %s</span>'
             '<span>账户 %d · 基金 %d</span></div>'
             % (time.strftime("%Y-%m-%d"), esc(last_date),
                esc(week_rows[0]["data_date"] if week_rows else "-"),
                len(accounts), len(funds)))
    h.append('</header>')

    # KPI
    h.append('<div class="kpis">')
    h.append('<div class="kpi"><div class="l">本周投入</div><div class="v">%s</div><div class="h">本周记录合计</div></div>' % money(week_total))
    h.append('<div class="kpi"><div class="l">累计投入</div><div class="v">%s</div>'
             '<div class="h">历史成本 + 台账新增（%d 只全口径）</div></div>'
             % (money(cum_total), len(funds)))
    h.append('<div class="kpi"><div class="l">当前市值</div><div class="v">%s</div>'
             '<div class="h">%s</div></div>'
             % (money(mv_now) if mv_now else "—",
                "持仓快照日 %s" % esc((hold or {}).get("nav_date") or "-")
                if mv_now else "未接入持仓快照"))
    h.append('<div class="kpi"><div class="l">平均估值分位</div><div class="v">%.1f%%</div><div class="h">%d 只基金简单平均</div></div>'
             % (avg_pct, len(pcts)))
    h.append('</div>')

    # 01 今日档位评估（只给档位：金额属于执行决策，脚本不替用户拍）
    h.append('<h2><span class="n">01</span>今日档位评估</h2>')
    h.append('<p class="note">这一节只给档位，<b>不折算成金额</b>——投哪只、每只投多少由你自己决定。'
             '档位由 <b>PE 分位定档 + PB 分位 ±1 档交叉校验</b>得出，'
             '各档位对应的分位区间与系数在「估值分位位置」节；<b>较上次</b>列对比上一份记录。</p>')

    moved = [f for f in funds if f.get("change_dir")]
    if moved:
        h.append('<div class="alert"><div class="t">档位变化 %d 只</div><div class="d">%s</div></div>'
                 % (len(moved), "　·　".join(
                     "<b>%s</b> %s" % (esc(f["name"]), esc(f.get("change", ""))) for f in moved)))
    elif any(f.get("change") == "基线" for f in funds):
        h.append('<p class="note">本次是该口径下的首份记录，<b>较上次</b>一列全部为「基线」；'
                 '从下一份记录起会显示与上一周的档位对比，变化会单独汇总在表格上方。</p>')

    for a in accounts:
        af = [f for f in funds if f["account"] == a["id"]]
        dist = {}
        for f in af:
            k = f.get("tier")
            if not k or k in ("-", "?"):
                k = "无"
            dist[k] = dist.get(k, 0) + 1
        order = []
        for r in rules:
            if r["level"] not in order:
                order.append(r["level"])
        order.append("无")
        h.append('<div class="acc"><div class="acc__h"><span class="acc__t">%s · %s</span>'
                 '<span class="acc__m">档位分布　%s</span></div>'
                 % (esc(a["id"]), esc(a.get("name", "")),
                    "　".join("%s <b>%d</b>" % (esc(k), dist[k]) for k in order if k in dist)))
        if af:
            h.append('<table><thead><tr><th>基金</th><th class="num">PE</th>'
                     '<th class="num">PE分位</th><th class="num">PB分位</th>'
                     '<th>档位</th><th>较上次</th><th>备注</th></tr></thead><tbody>')
            for f in sorted(af, key=lambda x: (x["pct"] if x["pct"] is not None else 999)):
                raw = f.get("tier_raw") or ""
                tier_cell = ('%s <span class="src">←%s</span>' % (esc(f["tier"]), esc(raw))
                             if raw and raw != f["tier"] else esc(f["tier"]))
                chg = f.get("change") or ""
                if f.get("change_dir") and f["change_dir"] < 0:
                    chg = '<span class="upc">%s</span>' % esc(chg)
                elif f.get("change_dir"):
                    chg = '<span class="dnc">%s</span>' % esc(chg)
                else:
                    chg = '<span class="src">%s</span>' % esc(chg)
                tags = []
                if f.get("reopen"):
                    tags.append('<span class="tag">重开 %s</span>'
                                % esc(f["reopen"].get("opened", "")))
                if f.get("tier_note"):
                    tags.append('<span class="src">%s</span>' % esc(f["tier_note"]))
                if f.get("src") == "手工":
                    tags.append('<span class="src">手工分位</span>')
                h.append('<tr><td>%s</td><td class="num">%s</td>'
                         '<td class="num">%s</td><td class="num">%s</td>'
                         '<td><span class="tier t-%s">%s</span></td><td>%s</td><td>%s</td></tr>'
                         % (esc(f["name"]),
                            "%.2f" % f["pe"] if f["pe"] else "-",
                            "%.1f%%" % f["pct"] if f["pct"] is not None else "-",
                            "%.1f%%" % f["pb_pct"] if f.get("pb_pct") is not None else "-",
                            esc(f["tier"]), tier_cell, chg, " ".join(tags) or "—"))
            h.append('</tbody></table>')
        else:
            h.append('<div class="acc__m">该账户暂无基金</div>')
        h.append('</div>')

    if any(f.get("reopen") for f in funds):
        reop = [f for f in funds if f.get("reopen")]
        h.append('<p class="note"><b>「重开」标记</b>：%s 这几只此前已清仓，近期重新开仓。'
                 '成本基准从重开日算起，所以它们的浮亏<b>只反映重开这一轮</b>，'
                 '不含清仓前那一段亏损——和一直持有的基金直接比浮亏率会低估实际亏损。'
                 '清仓前的盈亏已在当时实现，不应再计入当前持仓成本。</p>'
                 % "、".join("%s（%s）" % (esc(f["name"]), esc(f["reopen"].get("opened", "")))
                            for f in reop))

    # 02 持仓评估与建议（holdings_ref 未配或台账缺失时只出提示，不中断渲染）
    if hold:
        h.extend(assess(funds, hold, accounts, rules))
    else:
        h.append('<h2><span class="n">02</span>持仓评估与建议</h2>')
        h.append('<p class="note">本节跳过：<b>dca_plan.json 未配置 holdings_ref</b>，'
                 '或它指向的持仓台账文件不存在。补齐方式：先跑 <b>sync_lib.py pull</b> '
                 '从资料库数据表拉取持仓生成本地 JSON，再把该文件名写进 '
                 '<b>dca_plan.json</b> 的 <b>holdings_ref</b> 字段。'
                 '未补之前，其余各节的估值、档位与投入结构照常有效，'
                 '只是缺「权重 × 分位」这一层的矛盾诊断。</p>')

    # 03 估值分位
    if funds:
        h.append('<h2><span class="n">03</span>估值分位位置</h2>')
        h.append('<p class="note">色带与档位一一对应：<b>绿 ≤22%</b> 偏低可加码 · <b>米 22–47%</b> 中性减速 · '
                 '<b>橙 47–70%</b> 偏贵停投 · <b>红 &gt;70%</b> 高估。'
                 '<b>●圆点 = PE 分位</b>（定档依据），<b>□方点 = PB 分位</b>（校验依据）——'
                 '两者拉开 20 个百分点以上时方点会变深，表示这一档被交叉修正过。'
                 '分位窗口自 2016-07 起约 10.3 年，不含 2015 年那轮泡沫，'
                 '所以严格说这是「2016-07 以来分位」而非「历史分位」。</p>')
        h.append('<div class="chartbox">')
        h.append(svg_percentile(funds))
        h.append('</div>')

        # 档位说明：只给徽标不给换算，读者无法自己复核金额
        h.append('<h3>档位是怎么划出来的</h3>')
        h.append('<p class="note">档位由当前分位唯一决定，跨指数可比，不需要先看 PE 绝对值。'
                 '这张表<b>只回答「贵还是便宜」</b>，不回答「该投多少」——'
                 '系数列是各档的相对强弱参考，具体投多少由你自己按账户资金决定，'
                 '页面不替你换算金额。<b>停投只是停止买入，不是清仓</b>：'
                 '已有持仓继续持有，卖出走单独的止盈规则。</p>')
        h.append(tier_table(rules, funds))

        # 双锚校验：说明「为什么不能只看 PE 分位」
        shifted = [f for f in funds if f.get("tier_raw") and f["tier_raw"] != f["tier"]]
        h.append('<h3>为什么单看 PE 分位会错，PB 分位怎么校正</h3>')
        h.append('<p class="note">恒等式 <b>PE = PB ÷ ROE</b>。PE 分位偏高可能只是盈利分母变小（ROE 下滑），'
                 '不是价格变贵；而 PB 分位不受盈利周期扭曲——净资产是累计量，不会因为一个季度利润波动而重构。'
                 '所以规则是：<b>PE 分位定档，PB 分位做 ±1 档校验</b>。PB 分位比 PE 分位低 20 个百分点以上，'
                 '说明「按净资产看并不贵、PE 高是盈利在下滑」，上修 1 档；反过来 PE 低而 PB 高，是盈利虚高，'
                 '下修 1 档。修正上限 ±1 档，绝不越级跳档。</p>')
        if shifted:
            h.append('<table><thead><tr><th>基金</th><th class="num">PE 分位</th>'
                     '<th class="num">PB 分位</th><th>差</th><th>原档</th><th>修正后</th>'
                     '<th class="num">周投额变化</th><th>依据</th></tr></thead><tbody>')
            for f in shifted:
                d = (f["pb_pct"] - f["pct"]) if f.get("pb_pct") is not None else None
                raw_fac = next((r["factor"] for r in rules
                                if r["level"] == f["tier_raw"]), 0)
                bw = f.get("base_w") or 0
                h.append('<tr><td>%s</td><td class="num">%.1f%%</td><td class="num">%.1f%%</td>'
                         '<td class="num">%s</td><td><span class="tier t-%s">%s</span></td>'
                         '<td><span class="tier t-%s">%s</span></td>'
                         '<td class="num">%s → <b>%s</b></td><td class="src">%s</td></tr>'
                         % (esc(f["name"]), f["pct"], f["pb_pct"],
                            ("%+.0fpct" % d) if d is not None else "—",
                            esc(f["tier_raw"]), esc(f["tier_raw"]),
                            esc(f["tier"]), esc(f["tier"]),
                            money(round(bw * raw_fac)),
                            money(round(bw * (f.get("factor") or 0))),
                            esc(f["tier_note"])))
            h.append('</tbody></table>')
            h.append('<p class="note">上面三只是<b>同一指数</b>（沪深300）的三只不同基金，'
                     '所以修正金额按各自 base_weekly 等比放大——不是重复计算。'
                     '本周金额已按旧规则执行，不追溯；修正从下一个 ISO 周生效。</p>')
        else:
            h.append('<p class="note">本周没有标的需要交叉修正：PE 与 PB 分位指向同一档，'
                     '或者差额未达 20 个百分点的修正门槛。</p>')
        h.append('<p class="note">这条规则针对的正是「慢牛中枢重定价」：企业盈利能力变强时，'
                 '同样的净资产能赚更多钱，PE 会被动走低、PB 分位先动；反过来盈利下滑时 PE 虚高而 PB 正常。'
                 '只用 PE 分位，会把「盈利下滑但价格没跌」误判成「很贵」，从而长期不给买点。</p>')
        dup_levels = {}
        for r in rules:
            dup_levels.setdefault(r["level"], []).append(r)
        split = [lv for lv, rs in dup_levels.items() if len(rs) > 1]
        note = ['<b>- 徽标</b>表示这只没有取到分位数据，本周不分配——是「不知道」，不是「不该买」，'
                '补法见下方代理说明与告警节。',
                '<b>停投 ≠ 清仓</b>：D/E 档只是停止买入，已有持仓继续持有，卖出走单独的止盈规则。',
                '<b>C←D 这样的写法</b>表示这一档被 PB 分位交叉修正过：箭头右边是 PE 分位原本的档位，'
                '左边是校验后实际执行的档位。没有箭头就是两锚一致。']
        if split:
            note.append('<b>%s 分了两段</b>：同一徽标下系数不同，所以两只都显示 %s 的基金，'
                        '周投额可以差一倍以上，要看分位具体落在哪一段。'
                        % ("、".join(split), split[0]))
        note.append('这张表的分档阈值、系数、额度占用上限都可以改（配置里的 <b>tier_rules</b>），'
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
                # 手工分位并不来自 index_code 的接口值，写成「SH000827」会让人以为
                # 13.5% 是该指数的分位（实际是 31.9%），必须点明两者关系。
                if f.get("src") == "手工":
                    used = "自建/研报测算（%s 仅作参照）" % (f["index"] or "-")
                h.append('<tr><td>%s</td><td class="src">%s</td><td class="idx">%s</td>'
                         '<td class="src" style="white-space:normal">%s</td></tr>'
                         % (esc(f["name"]), esc(px.get("actual", "-")),
                            esc(used), esc(px.get("note", ""))))
            h.append('</tbody></table>')

    # 04 持仓与投入结构
    # 原来这节是「新增额度使用率」，但用户从未设过单只限额（给的金额是当前市值），
    # 额度列全是脚本按 base×156 估出来的虚构值，已改为真实的三段结构：历史成本 / 台账新增 / 市值。
    h.append('<h2><span class="n">04</span>持仓与投入结构</h2>')
    h.append('<p class="note">「历史持仓」是启用台账之前的存量成本，「台账新增」是此后按周记录的投入，'
             '两者相加等于累计投入；「当前市值」取持仓快照，差额就是浮动盈亏。'
             '<b>本账户没有给任何一只基金设单只限额</b>，所以这里不显示额度占用——'
             '每只投多少由你自己决定，本页只负责把已有持仓与档位算清楚。</p>')
    hm = (hold or {}).get("funds") or {}
    h.append('<table><thead><tr><th>基金</th><th class="num">历史持仓</th><th class="num">台账新增</th>'
             '<th class="num">累计投入</th><th class="num">当前市值</th><th class="num">浮动盈亏</th>'
             '</tr></thead><tbody>')
    for f in sorted(funds, key=lambda x: -(x["new"] + (x.get("base_inv") or 0))):
        hh = hm.get(f["code"]) or {}
        amt = hh.get("amount")
        inv = (f.get("base_inv") or 0) + (f.get("new") or 0)
        if amt:
            pnl = amt - inv
            # 与 02 节同口径：A 股红涨绿跌，盈利走 warn（红）、亏损走 buy（绿）
            pc = "var(--warn)" if pnl >= 0 else "var(--buy)"
            pnl_cell = '<span class="num" style="color:%s">%s（%+.1f%%）</span>' % (
                pc, money(pnl), (amt / inv - 1) * 100 if inv else 0)
            mv_cell = money(amt)
        else:
            pnl_cell = '<span class="src">市值待补</span>'
            mv_cell = "—"
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
                 % (esc(f["name"]), money(f.get("base_inv") or 0), money(f.get("new") or 0),
                    money(inv), mv_cell, pnl_cell))
    h.append('</tbody></table>')
    # 本周买入的份额要等下一次净值确认才进快照，这一周内会出现「钱已出、份额未计」的假亏损
    _wk_in = [f for f in funds if (f.get("week") or 0) > 0]
    if _wk_in:
        h.append('<p class="note"><b>口径注意</b>：本周投入的 %s 元（%s）如果还没在市值快照里确认份额，'
                 '上表的浮动盈亏会<b>短暂偏负</b>——钱已经算进累计投入，市值却还是买之前的。'
                 '下一次快照确认份额后会自动恢复，不代表真的多亏了这么多。'
                 '本表不预判这笔钱买到了多少份额，宁可显示偏差也不填估算值。</p>'
                 % (money(sum(f["week"] for f in _wk_in)),
                    "、".join(esc(f["name"][:10]) for f in _wk_in)))

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
    h.append('<p class="note">只报档位不报触发条件等于没给结论。下表给出改变本周判断的临界分位：'
             '<b>升档</b> = 分位跌到该值以下就加码，<b>降档</b> = 分位涨过该值就减速或停投。'
             '这里只给<b>分位临界点与档位</b>，不给金额——分位穿过哪条线、档位变成什么，'
             '是客观可复核的；换成多少钱是你自己的事。'
             '临界点按 <b>PE 分位</b>算，没有把 PB 校验叠进去：所以「当前档」可能因 PB 修正'
             '已经高于「PE 分位本档」，此时升档点会显示成同一档位，实际要等 PB 分位同向回落后才生效。</p>')
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
        up_txt = ("跌到 %.0f%% 以下 → %s 档（%.1f×）" % up[:3]) if up else "已是最低档"
        down_txt = ("涨过 %.0f%% → %s 档（%.1f×）" % down[:3]) if down else "已是最高档"
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
             '<b>双锚校验</b>：PE 分位定档，PB 分位做 ±1 档交叉校验（差额门槛 20 个百分点）——'
             'PB 分位不受盈利周期扭曲，能分辨「PE 高是盈利下滑」还是「价格真贵」。'
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
