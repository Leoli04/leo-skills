# -*- coding: utf-8 -*-
"""
多账户 · 多基金定投周度执行表
------------------------------------------------------------
解决三个问题：
  1. 多只基金同时定投，钱不够时该先买哪只
  2. 多个账户可投金额不同，各自独立预算，互不挪用
  3. 每只基金在低位不能把钱提前投光

核心规则：
  · 统一排序依据 = 估值历史分位（PE 绝对值跨指数不可比）
  · 单只定「该不该加」（分位落档），账户定「能不能加」（预算优先分配）
  · 预算不足时按分位从低到高分配，最贵的先砍
  · 每只基金有资金池与该档天花板，防单只超配

结果落盘：
  终端打印 + records/YYYY-MM-DD.md（快照）+ records/ledger.csv（台账，追加）
  台账是累计投入的事实源；配置里的 invested 只填「启用本脚本之前的历史持仓」，之后不要再改。

用法：
  python dca_weekly.py                     # 跑表并落盘
  python dca_weekly.py --no-save           # 只看不存
  python dca_weekly.py --config other.json
  python dca_weekly.py --offline           # 不联网
------------------------------------------------------------
"""
import csv
import datetime
import json
import os
import ssl
import sys
import time
import urllib.request

API = "https://danjuanfunds.com/djapi/index_eva/detail/{}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

LEDGER_FIELDS = ["iso_week", "run_date", "data_date", "account", "fund_code",
                 "fund_name", "index_code", "pe", "percentile", "tier",
                 "plan", "actual", "cumulative"]


def week_key(d=None):
    """ISO 周标识，如 2026-W44。同一周内多次运行只记一次。"""
    d = d or datetime.date.today()
    y, wk, _ = d.isocalendar()
    return "%d-W%02d" % (y, wk)


# ---------- 文本对齐 ----------
def w(s):
    n = 0
    for ch in str(s):
        n += 2 if ord(ch) > 0x2E80 else 1
    return n


def pad(s, width, align="left"):
    s = str(s)
    gap = max(0, width - w(s))
    if align == "right":
        return " " * gap + s
    if align == "center":
        left = gap // 2
        return " " * left + s + " " * (gap - left)
    return s + " " * gap


class Out:
    """同时输出到终端与文件"""

    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        print(s)
        self.lines.append(s)

    def text(self):
        return "\n".join(self.lines)


# ---------- 取数 ----------
def fetch_eva(index_code):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        API.format(index_code),
        headers={"User-Agent": UA, "Referer": "https://danjuanfunds.com/"},
    )
    try:
        raw = urllib.request.urlopen(req, timeout=20, context=ctx).read()
        d = json.loads(raw).get("data")
        if not d:
            return None
        return {
            "pe": d.get("pe"),
            "pb": d.get("pb"),
            "percentile": d.get("pe_percentile"),
            "date": d.get("date"),
            "name": d.get("name"),
        }
    except Exception as e:
        print("  [警告] 查询 %s 失败：%s" % (index_code, e))
        return None


def match_tier(percentile, rules):
    if percentile is None:
        return None
    for r in rules:
        if percentile <= r["max_percentile"]:
            return r
    return rules[-1]


# ---------- 台账 ----------
def load_ledger(path, wk):
    """返回 (累计已投 {key: 金额}, 本周已投 {key: 金额})，key = account|fund_code"""
    total, this_week = {}, {}
    if not os.path.exists(path):
        return total, this_week
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            key = "%s|%s" % (row.get("account", ""), row.get("fund_code", ""))
            try:
                amt = float(row.get("actual") or 0)
            except ValueError:
                amt = 0
            total[key] = total.get(key, 0) + amt
            if row.get("iso_week") == wk:
                this_week[key] = this_week.get(key, 0) + amt
    return total, this_week


def append_ledger(path, rows, run_date, data_date, wk):
    """追加本周记录；同一 ISO 周同一基金已存在则跳过（幂等）"""
    exists = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                exists.add((row.get("iso_week"), row.get("account"), row.get("fund_code")))

    new_file = not os.path.exists(path)
    added = 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new_file:
            wr.writeheader()
        for r in rows:
            if r["alloc"] <= 0:
                continue
            key = (wk, r["account"], r["fund"]["code"])
            if key in exists:
                continue
            wr.writerow({
                "iso_week": wk,
                "run_date": run_date,
                "data_date": data_date,
                "account": r["account"],
                "fund_code": r["fund"]["code"],
                "fund_name": r["fund"]["name"],
                "index_code": r["fund"]["index_code"],
                "pe": "%.2f" % r["eva"]["pe"] if r["eva"] and r["eva"].get("pe") else "",
                "percentile": "%.1f" % r["pct"] if r["pct"] is not None else "",
                "tier": r["tier"]["level"] if r["tier"] else "",
                "plan": r["need"],
                "actual": r["alloc"],
                "cumulative": round(r["cum_total"]),
            })
            added += 1
    return added


# ---------- 配置归一化 ----------
def normalize(cfg):
    if cfg.get("accounts"):
        accounts = cfg["accounts"]
    else:
        cap = cfg.get("total_capital", 0)
        base = cfg.get("weekly_budget_base") or (
            round(cap / cfg.get("horizon_years", 2) / 52) if cap else 0
        )
        accounts = [{
            "id": "A", "name": "默认账户", "total_capital": cap,
            "weekly_budget_base": base,
            "weekly_budget_cap": cfg.get("weekly_budget_cap") or base * 2,
        }]
    default_id = accounts[0]["id"]
    for a in accounts:
        a.setdefault("weekly_budget_cap", (a.get("weekly_budget_base") or 0) * 2)
    for f in cfg["funds"]:
        f.setdefault("account", default_id)
    return accounts


# ---------- 主流程 ----------
def main():
    args = sys.argv[1:]
    cfg_path = "dca_plan.json"
    if "--config" in args:
        cfg_path = args[args.index("--config") + 1]
    offline = "--offline" in args
    no_save = "--no-save" in args

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(cfg_path):
        cfg_path = os.path.join(script_dir, cfg_path)
    cfg_dir = os.path.dirname(cfg_path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    accounts = normalize(cfg)
    rules = cfg["tier_rules"]
    out_dir = cfg.get("output_dir") or os.path.join(cfg_dir, "定投记录")
    ledger_path = os.path.join(out_dir, "ledger.csv")
    wk = week_key()
    ledger_sum, week_done = load_ledger(ledger_path, wk)

    # 取数分档
    eva_cache = {}
    rows = []
    for fund in cfg["funds"]:
        ic = fund.get("index_code") or ""
        if ic and ic not in eva_cache:
            eva_cache[ic] = None if offline else fetch_eva(ic)
        eva = eva_cache.get(ic) if ic else None
        pct = eva["percentile"] * 100 if eva and eva.get("percentile") is not None else None
        # PE=0 或分位为 0 的脏数据必须弃用（PB ÷ ROE ≈ PE 不自洽）
        if eva and not eva.get("pe"):
            eva = None
            pct = None
        src = "蛋卷" if pct is not None else "-"
        # manual_percentile：蛋卷无该指数时由用户或外部研报手工填分位，优先级高于接口
        manual = fund.get("manual_percentile")
        if manual is not None and manual != "":
            try:
                pct = float(manual)
                src = "手工"
            except (TypeError, ValueError):
                pass
        if pct is None and not ic:
            src = "无"
        tier = match_tier(pct, rules)

        base_w = fund.get("base_weekly", 0)
        want = round(base_w * tier["factor"]) if tier else 0

        pool = fund.get("pool", 0)
        ceiling = round(pool * tier["cap_ratio"]) if tier else 0
        # new_sum = 台账新增累计（不含历史持仓）；invested = 历史持仓成本 + new_sum
        key = "%s|%s" % (fund["account"], fund["code"])
        new_sum = ledger_sum.get(key, 0)
        invested = fund.get("invested", 0) + new_sum
        # 天花板管的是「新增额度」，不是「总持仓」——否则已重仓的老基金一进来就被判停投
        room = max(0, ceiling - new_sum)
        need = min(want, room) if pool else want

        rows.append({
            "fund": fund, "eva": eva, "pct": pct, "tier": tier, "src": src,
            "want": want, "ceiling": ceiling, "invested": invested,
            "new_sum": new_sum, "cum_total": invested, "room": room,
            "need": need, "alloc": 0,
            "account": fund["account"],
        })

    # 分账户分配
    for acc in accounts:
        mine = sorted(
            [r for r in rows if r["account"] == acc["id"]],
            key=lambda r: (r["pct"] if r["pct"] is not None else 999),
        )
        # 本周该账户已有任何记录 → 整周计划冻结，不再追加分配。
        # 否则「同一个 ISO 周重跑」会给上周没分到的标的补钱，破坏幂等。
        frozen = any("%s|%s" % (r["account"], r["fund"]["code"]) in week_done for r in mine)
        left = acc.get("weekly_budget_cap") or acc.get("weekly_budget_base") or 0
        for r in mine:
            key = "%s|%s" % (r["account"], r["fund"]["code"])
            if key in week_done:
                # 本周已执行过，不再分配、不重复累加
                r["done"] = week_done[key]
                r["alloc"] = 0
                r["cum_total"] = r["invested"]
                continue
            if frozen:
                r["alloc"] = 0
                r["frozen"] = True
                r["cum_total"] = r["invested"]
                continue
            give = min(r["need"], left)
            r["alloc"] = give
            left -= give
            r["cum_total"] = r["invested"] + give

    # ---------- 输出 ----------
    o = Out()
    asof = next((r["eva"]["date"] for r in rows if r["eva"]), "N/A")
    run_date = time.strftime("%Y-%m-%d")

    o()
    o("=" * 94)
    o("多账户定投周度执行表   数据日 %s   运行日 %s   账户 %d / 基金 %d"
      % (asof, run_date, len(accounts), len(rows)))
    o("=" * 94)

    head = (pad("序", 3) + pad("基金", 22) + pad("指数", 12) +
            pad("PE", 8, "right") + pad("分位", 7, "right") + pad("档", 4, "center") +
            pad("源", 5, "center") +
            pad("理论", 6, "right") + pad("本周投", 7, "right") +
            pad("新增/额度", 15, "right"))

    grand = 0
    for acc in accounts:
        mine = sorted(
            [r for r in rows if r["account"] == acc["id"]],
            key=lambda r: (r["pct"] if r["pct"] is not None else 999),
        )
        base_b = acc.get("weekly_budget_base") or 0
        cap_b = acc.get("weekly_budget_cap") or 0
        used_new = sum(r["alloc"] for r in mine)
        used_done = sum(r.get("done", 0) for r in mine)
        used = used_new + used_done
        grand += used

        o()
        o("─" * 94)
        o("【%s】%s   资金池 %s 元   周预算 %d（上限 %d）   本周已用 %d，结余 %d%s"
          % (acc["id"], acc.get("name", ""),
             "{:,}".format(acc.get("total_capital", 0)), base_b, cap_b,
             used, cap_b - used,
             "（含上周已执行 %d，本次新增 %d）" % (used_done, used_new) if used_done else ""))
        o("─" * 94)
        if not mine:
            o("  （该账户暂无基金，请在配置的 funds 里加 \"account\": \"%s\"）" % acc["id"])
            continue
        o(head)
        o("-" * 94)
        for i, r in enumerate(mine, 1):
            f, e, t = r["fund"], r["eva"], r["tier"]
            idx_name = (e["name"] if e else "-")[:6]
            pe = ("%.2f" % e["pe"]) if e and e.get("pe") else "-"
            pct = ("%.1f%%" % r["pct"]) if r["pct"] is not None else "-"
            lv = t["level"] if t else "?"
            mark = ""
            if r.get("done"):
                mark = "  ← 本周已执行 %d，本次不重复" % r["done"]
            elif r.get("frozen") and r["need"] > 0:
                mark = "  ← 本周账户计划已冻结（本应 %d）" % r["need"]
            elif r["need"] > 0 and r["alloc"] < r["need"]:
                mark = "  ← 预算不足，本应 %d" % r["need"]
            elif r["want"] > 0 and r["need"] < r["want"]:
                mark = "  ← 已达该档天花板 %d" % r["ceiling"]
            o(pad(i, 3) + pad(f["name"][:10], 22) + pad(idx_name, 12) +
              pad(pe, 8, "right") + pad(pct, 7, "right") + pad(lv, 4, "center") +
              pad(r.get("src", "-"), 5, "center") +
              pad(r["want"], 6, "right") + pad(r["alloc"], 7, "right") +
              pad("%d/%d" % (round(r["new_sum"] + r["alloc"]), f.get("pool", 0)), 15, "right") + mark)

    o()
    o("=" * 94)
    o(pad("本周全部账户合计投入", 24) + pad(grand, 8, "right") + " 元")
    o("=" * 94)

    # 重复暴露（空 index_code 表示无可用指数，不是「同一指数」）
    seen = {}
    for r in rows:
        ic = r["fund"].get("index_code") or ""
        if not ic:
            continue
        seen.setdefault(ic, []).append(r)
    dup = {k: v for k, v in seen.items() if len(v) > 1}
    if dup:
        o()
        o("⚠ 重复暴露：以下指数被多只基金跟踪，等于同一风险押两次：")
        for ic, v in dup.items():
            o("   %s → %s" % (ic, "、".join(x["fund"]["name"] for x in v)))
        o("   建议只保留费率最低的一只，或把 pool 合计控制在单指数目标上限内。")

    stopped = [r["fund"]["name"] for r in rows if r["tier"] and r["tier"]["factor"] == 0]
    if stopped:
        o()
        o("停投（分位高于停投线，只持有不再买入）：%s" % "、".join(stopped))

    proxied = [r for r in rows if r["fund"].get("index_proxy")]
    if proxied:
        o()
        o("代理指数（该基金无对应指数估值，用下列指数代替，分位可信度打折）：")
        for r in proxied:
            px = r["fund"]["index_proxy"]
            o("   %s ← %s → %s  %s"
              % (r["fund"]["name"][:14], px.get("actual", "?"),
                 r["fund"]["index_code"], px.get("note", "")))

    nodata = [r["fund"]["name"] for r in rows if r["pct"] is None]
    if nodata:
        o()
        o("⚠ 无估值分位（本周不分配，不代表不该买）：%s" % "、".join(nodata))
        o("   原因：蛋卷无对应指数数据。补法：在配置里给该只加 manual_percentile 字段填分位值。")

    if any(r["need"] > r["alloc"] for r in rows):
        o()
        o("预算不足的标的已按估值分位排后，不是不买；下周分位变化后可能重新排前。")

    # ---------- 落盘 ----------
    if no_save:
        o()
        o("（--no-save 已指定，本次未写入记录）")
        return

    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "%s.md" % run_date)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 定投周表 %s\n\n" % run_date)
        f.write("> 数据日 %s · 配置 %s\n\n```\n" % (asof, os.path.basename(cfg_path)))
        f.write(o.text())
        f.write("\n```\n\n")
        f.write("## 本周执行\n\n")
        for acc in accounts:
            mine = [r for r in rows if r["account"] == acc["id"] and r["alloc"] > 0]
            if mine:
                f.write("- **%s**：%s\n" % (
                    acc.get("name", acc["id"]),
                    "、".join("%s %d 元" % (r["fund"]["name"], r["alloc"]) for r in mine)))
            else:
                f.write("- **%s**：本周无操作\n" % acc.get("name", acc["id"]))

    added = append_ledger(ledger_path, rows, run_date, asof, wk)

    # 分位快照：本轮全部标的（含本周未投的），供渲染层画完整估值标尺。
    # 只靠 ledger 不够——被砍到 0 的标的不进台账，页面上会退化成「无数据」。
    snap = {
        "run_date": run_date,
        "data_date": asof,
        "week": wk,
        "accounts": [{"id": a["id"], "name": a.get("name", ""),
                      "total_capital": a.get("total_capital", 0),
                      "weekly_budget_base": a.get("weekly_budget_base", 0),
                      "weekly_budget_cap": a.get("weekly_budget_cap", 0)}
                     for a in accounts],
        "funds": [{
            "account": r["account"],
            "code": r["fund"]["code"],
            "name": r["fund"]["name"],
            "index_code": r["fund"].get("index_code", ""),
            "index_proxy": r["fund"].get("index_proxy"),
            "pct": r["pct"],
            "pe": (r["eva"] or {}).get("pe"),
            "tier": r["tier"]["level"] if r["tier"] else "",
            "src": r.get("src", "-"),
            "want": r["want"], "alloc": r["alloc"],
            "done": r.get("done", 0) or 0,
            "ceiling": r["ceiling"], "pool": r["fund"].get("pool", 0),
            "new_sum": round(r["new_sum"]), "invested": round(r["invested"]),
            "cum_total": round(r["cum_total"]),
            "new_total": round(r["cum_total"] - r["fund"].get("invested", 0)),
            "need": r["need"],
        } for r in rows],
    }
    snap_path = os.path.join(out_dir, "snapshot_%s.json" % run_date)
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    o()
    o("─" * 94)
    o("已保存：")
    o("  快照  %s" % md_path)
    o("  分位  %s" % snap_path)
    o("  台账  %s（本周 %s，本次新增 %d 条%s）"
      % (ledger_path, wk, added, "，本周已记录过则跳过" if added == 0 else ""))
    o("─" * 94)
    o("台账说明：actual 列即实际投入，事后可手工修改；下次运行按它累加。")
    o("          同一 ISO 周内重复运行不会重复记账。")
    o("          配置里的 invested 只填启用脚本之前的历史持仓，之后不再改。")
    o()


if __name__ == "__main__":
    main()
