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
            for k in ("plan", "actual", "cumulative", "percentile"):
                try:
                    r[k] = float(r.get(k) or 0)
                except (TypeError, ValueError):
                    r[k] = 0.0
            try:
                r["pe"] = float(r["pe"]) if r.get("pe") else None
            except (TypeError, ValueError):
                r["pe"] = None
            rows.append(r)
    rows.sort(key=lambda r: (r.get("run_date", ""), r.get("account", "")))
    return rows


def tier_of(pct, rules):
    if pct is None:
        return None
    for r in rules:
        if pct <= r["max_percentile"]:
            return r
    return rules[-1]


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
    left, bar_w = 116, 420
    parts = ['<svg viewBox="0 0 660 %d" role="img" aria-label="各基金估值分位标尺">' % h]
    parts.append('<title>各基金估值历史分位</title>')
    # 背景带按档位分五段
    for a, b, color in [(0, 10, "#DCEBE3"), (10, 22, "#EAF1EC"), (22, 47, "#F0EDE6"),
                        (47, 70, "#F6E8DA"), (70, 100, "#F8E5E2")]:
        parts.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s"/>'
                     % (left + bar_w * a / 100.0, top - 8, bar_w * (b - a) / 100.0, n * row_h, color))
    # 网格与刻度
    for pct in (0, 25, 50, 75, 100):
        x = left + bar_w * pct / 100.0
        parts.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#DCD6CA" stroke-width="0.8"/>'
                     % (x, top - 14, x, top + n * row_h - 4))
        parts.append('<text x="%.1f" y="%d" font-size="10" fill="#8A857C" text-anchor="middle">%d%%</text>'
                     % (x, top + n * row_h + 12, pct))
    for i, f in enumerate(funds):
        y = top + i * row_h
        pct = f["pct"]
        name = f["short"]
        parts.append('<text x="%d" y="%d" font-size="11.5" fill="#3F3B33" text-anchor="end">%s</text>'
                     % (left - 12, y + 4, esc(name)))
        if pct is None:
            parts.append('<text x="%d" y="%d" font-size="11" fill="#A8A296">无数据</text>' % (left + 6, y + 4))
            continue
        x = left + bar_w * min(pct, 100) / 100.0
        color = "#1E6B4A" if pct <= 22 else ("#8A6410" if pct <= 47 else "#9C2A20")
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
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#EAE5DA" stroke-width="0.8"/>' % (left, y, right, y))
        parts.append('<text x="%d" y="%.1f" font-size="10" fill="#8A857C" text-anchor="end">%s</text>'
                     % (left - 8, y + 3, money(v)))
    pts = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, v in enumerate(cum))
    area = "%.1f,%.1f " % (px(0), bottom) + pts + " %.1f,%.1f" % (px(len(cum) - 1), bottom)
    parts.append('<polygon points="%s" fill="#1E6B4A" opacity="0.09"/>' % area)
    parts.append('<polyline points="%s" fill="none" stroke="#1E6B4A" stroke-width="2"/>' % pts)
    for i, v in enumerate(cum):
        if i == len(cum) - 1 or len(cum) <= 8:
            parts.append('<circle cx="%.1f" cy="%.1f" r="3.2" fill="#1E6B4A"/>' % (px(i), py(v)))
            parts.append('<text x="%.1f" y="%.1f" font-size="10.5" fill="#1E6B4A" font-weight="600" text-anchor="middle">%s</text>'
                         % (px(i), py(v) - 8, money(v)))
    step = max(1, len(dates) // 6)
    for i, d in enumerate(dates):
        if i % step == 0 or i == len(dates) - 1:
            parts.append('<text x="%.1f" y="%d" font-size="10" fill="#8A857C" text-anchor="middle">%s</text>'
                         % (px(i), bottom + 16, d[5:]))
    parts.append('</svg>')
    return "".join(parts)


# ---------- 主体 ----------
def build(cfg, ledger, weeks):
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

    last_date = max([r["run_date"] for r in ledger], default=time.strftime("%Y-%m-%d"))
    week_rows = [r for r in ledger if r["run_date"] == last_date]

    funds = []
    for f in cfg["funds"]:
        key = (f["account"], f["code"])
        rec = latest.get(key)
        pct = rec["percentile"] if rec else None
        tier = tier_of(pct, rules) if pct else None
        cum_v = cum.get(key, base_inv.get(key, 0))
        bi = base_inv.get(key, 0)
        funds.append({
            "code": f["code"], "name": f["name"], "short": f["name"][:10],
            "account": f["account"], "index": f.get("index_code", ""),
            "pe": rec["pe"] if rec else None,
            "pct": pct, "tier": tier["level"] if tier else "-",
            "week": rec["actual"] if rec else 0,
            "cum": cum_v, "pool": f.get("pool", 0) or 1,
            "base_inv": bi, "new": max(0, cum_v - bi),
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
        seen_idx.setdefault(f["index"], []).append(f["name"])
    for ic, names in seen_idx.items():
        if len(names) > 1:
            alerts.append(("重复暴露", "%s 被 %d 只基金跟踪：%s" % (ic, len(names), "、".join(names)),
                           "同一风险押两次，建议合并或把 pool 合计控在单指数上限内"))
    for f in funds:
        if f["pct"] is not None and f["pct"] > 47:
            alerts.append(("停投", f["name"] + " 分位 %.1f%%" % f["pct"], "高于停投线，只持有不再买入"))
        if f["new"] / f["pool"] > 0.9:
            alerts.append(("新增额度将尽", f["name"] + " 已用 %.0f%%" % (f["new"] / f["pool"] * 100),
                           "该基金在本账户的加仓额度快用完，下档需等估值下移"))

    # ---- HTML ----
    css = """
:root{--bg:#F5F3EE;--surface:#FFF;--ink:#1B1A17;--ink2:#5B5750;--ink3:#8A857C;
--line:#E4DFD5;--line2:#D0C9BB;--brand:#1F3A4D;--buy:#1E6B4A;--warn:#9C2A20;--amber:#8A6410}
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
.note{font-size:12.5px;color:var(--ink3);margin:6px 0 0}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:12.5px;background:var(--surface)}
th{text-align:left;font-weight:600;font-size:11px;color:var(--ink3);letter-spacing:.04em;
padding:8px 10px;border-bottom:1.5px solid var(--line2);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--line);color:var(--ink2)}
td:first-child{color:var(--ink);font-weight:500}
.num{text-align:right;font-variant-numeric:tabular-nums}
.acc{background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin:12px 0;border-left:3px solid var(--brand)}
.acc__h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;flex-wrap:wrap;gap:8px}
.acc__t{font-size:14.5px;font-weight:600}
.acc__m{font-size:11.5px;color:var(--ink3)}
.bar{height:7px;background:#EFEBE2;border-radius:4px;overflow:hidden;margin:8px 0 4px}
.bar>i{display:block;height:7px;background:var(--brand);border-radius:4px}
.bar.buy>i{background:var(--buy)}
.mini{height:5px;background:#EFEBE2;border-radius:3px;overflow:hidden;width:88px;display:inline-block;vertical-align:middle}
.mini>i{display:block;height:5px;background:var(--buy);min-width:2px}
.tier{display:inline-block;font-size:10.5px;padding:1px 6px;border-radius:4px;font-weight:600}
.t-S{background:#E4F0EA;color:#0F5A3C}.t-A{background:#E9F1EC;color:#1E6B4A}
.t-B{background:#F1EEE6;color:#5B5750}.t-C{background:#FAF0DC;color:#8A6410}
.t-D,.t-E{background:#F8E6E3;color:#9C2A20}
.alert{background:#FBF0EE;border:1px solid #EDD6D2;border-radius:9px;padding:12px 15px;margin:10px 0}
.alert .t{font-weight:600;color:var(--warn);font-size:12.5px;margin-bottom:2px}
.alert .d{font-size:12px;color:#7A4A43}
svg{display:block;width:100%;height:auto}
footer{margin-top:46px;padding-top:16px;border-top:1px solid var(--line2);
font-size:11px;color:var(--ink3);line-height:1.75}
@media(max-width:720px){.wrap{padding:28px 16px 52px}.kpis{grid-template-columns:1fr 1fr}
h1{font-size:22px}table{font-size:11.5px}th,td{padding:7px 6px}}
@media print{body{background:#fff}.wrap{max-width:none;padding:0}table,.acc{break-inside:avoid}}
"""

    h = []
    h.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
    h.append('<meta name="viewport" content="width=device-width,initial-scale=1.0">')
    h.append('<title>定投台账 %s</title>' % esc(last_date))
    h.append('<style>%s</style></head><body><div class="wrap">' % css)

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
    h.append('<p class="note">账户预算互相独立、不可挪用；同一账户内按估值分位从低到高分配，最贵的先砍。</p>')
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
                     '<th>档</th><th class="num">本周投</th><th class="num">新增/额度</th></tr></thead><tbody>')
            for f in sorted(af, key=lambda x: (x["pct"] if x["pct"] is not None else 999)):
                h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
                         '<td><span class="tier t-%s">%s</span></td><td class="num">%s</td><td class="num">%s/%s</td></tr>'
                         % (esc(f["name"]), "%.2f" % f["pe"] if f["pe"] else "-",
                            "%.1f%%" % f["pct"] if f["pct"] is not None else "-",
                            esc(f["tier"]), esc(f["tier"]), money(f["week"]),
                            money(f["new"]), money(f["pool"])))
            h.append('</tbody></table>')
        else:
            h.append('<div class="acc__m">该账户暂无基金</div>')
        h.append('</div>')

    # 02 估值分位
    if funds:
        h.append('<h2><span class="n">02</span>估值分位位置</h2>')
        h.append('<p class="note">色带与档位一一对应：<b>绿 ≤22%</b> 偏低可加码 · <b>米 22–47%</b> 中性减速 · '
                 '<b>橙 47–70%</b> 偏贵停投 · <b>红 &gt;70%</b> 高估。分位窗口自 2016-07 起约 10.3 年。</p>')
        h.append('<div style="background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 12px 6px">')
        h.append(svg_percentile(funds))
        h.append('</div>')

    # 03 持仓与天花板
    h.append('<h2><span class="n">03</span>持仓与新增额度使用</h2>')
    h.append('<p class="note">「历史持仓」是启用台账之前的存量成本，不占新增额度；'
             '「新增/额度」逼近 100% 说明这只基金在本账户的加仓弹药快用完，下档要靠估值下移才会打开。</p>')
    h.append('<table><thead><tr><th>基金</th><th class="num">历史持仓</th><th class="num">新增累计</th>'
             '<th class="num">新增额度</th><th>已用率</th><th class="num">剩余</th></tr></thead><tbody>')
    for f in sorted(funds, key=lambda x: -x["new"]):
        r = f["new"] / f["pool"] * 100
        color = "#9C2A20" if r > 85 else ("#8A6410" if r > 60 else "#1E6B4A")
        h.append('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td><span class="mini"><i style="width:%.0f%%;background:%s"></i></span> <span class="num">%.0f%%</span></td>'
                 '<td class="num">%s</td></tr>'
                 % (esc(f["name"]), money(f["base_inv"]), money(f["new"]), money(f["pool"]),
                    min(100, r), color, r, money(max(0, f["pool"] - f["new"]))))
    h.append('</tbody></table>')

    # 04 累计曲线
    initial_total = sum(f.get("invested", 0) for f in cfg["funds"])
    cur_svg = svg_cumulative(ledger, initial_total)
    if cur_svg:
        h.append('<h2><span class="n">04</span>累计投入曲线</h2>')
        h.append('<p class="note">含启用本台账前的历史持仓基数 %s 元，之后按每周记录累加。'
                 '曲线突然变陡 = 某周发生了超常投入，值得回看当时的判断依据。</p>' % money(initial_total))
        h.append('<div style="background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 12px 6px">')
        h.append(cur_svg)
        h.append('</div>')

    # 05 告警
    h.append('<h2><span class="n">05</span>告警与检查</h2>')
    if alerts:
        for t, d, tip in alerts:
            h.append('<div class="alert"><div class="t">%s · %s</div><div class="d">%s</div></div>'
                     % (esc(t), esc(d), esc(tip)))
    else:
        h.append('<p class="note">无重复暴露、无停投标的、无逼近天花板的持仓。</p>')

    # 06 历史台账
    h.append('<h2><span class="n">06</span>历史记录</h2>')
    h.append('<p class="note">最近 %d 条记录，倒序。完整数据见同目录 ledger.csv。</p>' % min(weeks * 4, len(ledger)))
    h.append('<table><thead><tr><th>周次</th><th>记录日</th><th>账户</th><th>基金</th>'
             '<th class="num">分位</th><th>档</th><th class="num">投入</th><th class="num">累计</th></tr></thead><tbody>')
    for r in list(reversed(ledger))[: weeks * 4]:
        h.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="num">%.1f%%</td>'
                 '<td><span class="tier t-%s">%s</span></td><td class="num">%s</td><td class="num">%s</td></tr>'
                 % (esc(r.get("iso_week", "")), esc(r.get("run_date", "")), esc(r.get("account", "")),
                    esc(r.get("fund_name", "")), r["percentile"], esc(r.get("tier", "")),
                    esc(r.get("tier", "")), money(r["actual"]), money(r["cumulative"])))
    h.append('</tbody></table>')

    # footer
    h.append('<footer><b>口径</b>　估值分位来自蛋卷（雪球基金）指数估值，窗口自 2016-07 起约 10.3 年，'
             '不含 2015 年泡沫；PE 为 TTM 口径，跨指数不可直接用 PE 绝对值比较，只能比分位。'
             '台账按 ISO 自然周去重，同一周重复运行只记一次。<br><br>'
             '<b>说明</b>　本页为执行记录，不构成投资建议。累计投入 = 配置中的历史持仓基数 + 台账全部记录之和。'
             'actual 列可在 ledger.csv 中手工修正，下次渲染即生效。<br><br>'
             '生成时间 %s · 单文件零依赖</footer>' % time.strftime("%Y-%m-%d %H:%M"))

    h.append('</div></body></html>')
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

    html = build(cfg, ledger, weeks)
    if not out:
        last = max(r["run_date"] for r in ledger)
        out = os.path.join(base, "定投台账_%s.html" % last)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已生成 %s（%.1f KB）" % (out, len(html.encode("utf-8")) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
