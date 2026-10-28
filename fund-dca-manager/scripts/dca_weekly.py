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
  · 单只限额（pool）可选：不填即不设上限；填了才按 档位×cap_ratio 截断，防单只超配

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


def rank_of(level, rules):
    """档位在规则里的序号，越小越便宜。同名字的 A+ 两格只算第一次出现。"""
    for i, r in enumerate(rules):
        if r["level"] == level:
            return i
    return len(rules)


def load_prev_tiers(out_dir, run_date, week, cfg_funds=None):
    """上一份「不同 ISO 周」的分位快照 -> ({code: level}, 快照日期)。

    同周快照不能当基线：同周重跑通常是改了规则，档位变化来自规则而不是市场，
    把它当「档位变了」会误导。
    """
    import glob
    import re
    best = None
    for p in glob.glob(os.path.join(out_dir, "snapshot_*.json")):
        m = re.search(r"snapshot_(\d{4}-\d{2}-\d{2})\.json$", p)
        if not m:
            continue
        d = m.group(1)
        if d >= run_date:
            continue
        try:
            with open(p, "r", encoding="utf-8") as fp:
                snap = json.load(fp)
        except Exception:
            continue
        if snap.get("week") == week:
            continue
        if best is None or d > best[0]:
            best = (d, snap)
    if not best:
        return {}, None
    d, snap = best
    return {f["code"]: (f.get("tier") or "") for f in snap.get("funds", [])}, d


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
            "roe": d.get("roe"),
            "percentile": d.get("pe_percentile"),
            "pb_percentile": d.get("pb_percentile"),
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


def tier_index(percentile, rules):
    if percentile is None:
        return None
    for i, r in enumerate(rules):
        if percentile <= r["max_percentile"]:
            return i
    return len(rules) - 1


def pb_check(pct, pb_pct, rules, gap=20.0):
    """PB 分位校验 PE 分位，返回 (档位dict, 原始档位dict, 说明)。

    为什么需要这一步：PE = PB ÷ ROE，PE 分位偏高可能只是盈利分母变小，
    而不是价格变贵。PB 分位不受盈利周期扭曲——PB 不比历史贵、PE 却贵，
    说明是盈利下滑（周期底部的典型形态），此时停投是错误的。
    反向同理：PE 便宜而 PB 贵，是盈利虚高，该降档。

    修正上限 ±1 档，绝不越级；差额未达 gap 个百分点则不动。
    """
    idx = tier_index(pct, rules)
    if idx is None:
        return None, None, ""
    raw = rules[idx]
    if pb_pct is None or pb_pct == "":
        return raw, raw, ""
    try:
        d = float(pb_pct) - float(pct)
    except (TypeError, ValueError):
        return raw, raw, ""
    if d <= -gap:
        ni = max(0, idx - 1)
        return rules[ni], raw, "PB 分位比 PE 低 %.0fpct，上修 1 档" % (-d)
    if d >= gap:
        ni = min(len(rules) - 1, idx + 1)
        return rules[ni], raw, "PB 分位比 PE 高 %.0fpct，下修 1 档" % d
    return raw, raw, ""


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
    # 默认只输出档位：给到具体金额等于替用户做执行决策，而档位是可复核的估值事实
    show_amounts = "--amounts" in args

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
    anc = cfg.get("anchors") or {}
    pbc = anc.get("pb_check") or {}
    gap_pct = float(pbc.get("gap_pct", 20.0))
    prev_tiers, prev_date = load_prev_tiers(out_dir, time.strftime("%Y-%m-%d"), wk)
    for fund in cfg["funds"]:
        ic = fund.get("index_code") or ""
        if ic and ic not in eva_cache:
            eva_cache[ic] = None if offline else fetch_eva(ic)
        eva = eva_cache.get(ic) if ic else None
        pct = eva["percentile"] * 100 if eva and eva.get("percentile") is not None else None
        pb_pct = (eva["pb_percentile"] * 100
                  if eva and eva.get("pb_percentile") is not None else None)
        # PE=0 或分位为 0 的脏数据必须弃用（PB ÷ ROE ≈ PE 不自洽）
        if eva and not eva.get("pe"):
            eva = None
            pct = None
            pb_pct = None
        src = "蛋卷" if pct is not None else "-"
        # manual_percentile：蛋卷无该指数时由用户或外部研报手工填分位，优先级高于接口
        manual = fund.get("manual_percentile")
        if manual is not None and manual != "":
            try:
                pct = float(manual)
                src = "手工"
                pb_pct = None      # 手工分位没有配套 PB 分位，不做校验
            except (TypeError, ValueError):
                pass
        if pct is None and not ic:
            src = "无"
        # 双锚定档：PE 分位定档，PB 分位做 ±1 档校验（可在 anchors 里关掉）
        if pbc.get("enabled", True):
            tier, tier_raw, tier_note = pb_check(pct, pb_pct, rules, gap=gap_pct)
        else:
            tier, tier_raw, tier_note = match_tier(pct, rules), None, ""

        base_w = fund.get("base_weekly", 0)
        want = round(base_w * tier["factor"]) if tier else 0
        want_raw = round(base_w * tier_raw["factor"]) if tier_raw else want

        # 单只限额 pool 可选：不填（None / 0）＝不设上限，本周额只受档位系数与账户预算约束。
        # 用户提供的「金额」是当前市值（holdings.json），不是计划投入总额度，绝不能拿来当限额。
        pool = fund.get("pool") or 0
        key = "%s|%s" % (fund["account"], fund["code"])
        new_sum = ledger_sum.get(key, 0)
        invested = fund.get("invested", 0) + new_sum
        if pool:
            # 天花板管的是「新增额度」，不是「总持仓」——否则已重仓的老基金一进来就被判停投
            ceiling = round(pool * tier["cap_ratio"]) if tier else 0
            room = max(0, ceiling - new_sum)
            need = min(want, room)
        else:
            ceiling = None
            room = None
            need = want

        # 与上一份不同周的记录比档位（首份记录 = 基线，不假装「持平」）
        lv_now = tier["level"] if tier else ""
        lv_prev = prev_tiers.get(fund["code"])
        if not prev_tiers:
            change, change_dir = "基线", 0
        elif lv_prev is None:
            change, change_dir = "新入", 0
        elif lv_prev == lv_now:
            change, change_dir = "持平", 0
        else:
            d = rank_of(lv_now, rules) - rank_of(lv_prev, rules)
            # 序号变小 = 档位变便宜（S 在最前），用 ↑ 表示可以加码；变大 = 收紧
            change = "%s→%s%s" % (lv_prev, lv_now, "↑" if d < 0 else "↓")
            change_dir = -1 if d < 0 else 1

        rows.append({
            "fund": fund, "eva": eva, "pct": pct, "tier": tier, "src": src,
            "change": change, "change_dir": change_dir,
            "pb_pct": pb_pct, "tier_raw": tier_raw, "tier_note": tier_note,
            "want": want, "want_raw": want_raw, "ceiling": ceiling, "invested": invested,
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
    o("基金档位评估表   数据日 %s   运行日 %s   账户 %d / 基金 %d"
      % (asof, run_date, len(accounts), len(rows)))
    o("只给档位，不给金额：投哪只、投多少由你自己决定；档位发生变化会单独列出。")
    o("=" * 94)

    if show_amounts:
        head = (pad("序", 3) + pad("基金", 19) + pad("指数", 11) +
                pad("PE", 7, "right") + pad("PE分位", 8, "right") + pad("PB分位", 8, "right") +
                pad("档", 6, "center") + pad("较上次", 9, "center") +
                pad("理论", 6, "right") + pad("建议", 6, "right"))
    else:
        head = (pad("序", 3) + pad("基金", 21) + pad("指数", 12) +
                pad("PE", 7, "right") + pad("PE分位", 8, "right") + pad("PB分位", 8, "right") +
                pad("档", 6, "center") + pad("较上次", 9, "center") + pad("备注", 8))

    grand = 0
    for acc in accounts:
        mine = sorted(
            [r for r in rows if r["account"] == acc["id"]],
            key=lambda r: (r["pct"] if r["pct"] is not None else 999),
        )
        used_new = sum(r["alloc"] for r in mine)
        used_done = sum(r.get("done", 0) for r in mine)
        used = used_new + used_done
        grand += used

        o()
        o("─" * 94)
        if show_amounts:
            base_b = acc.get("weekly_budget_base") or 0
            cap_b = acc.get("weekly_budget_cap") or 0
            o("【%s】%s   周预算 %d（上限 %d）   本周已用 %d，结余 %d%s"
              % (acc["id"], acc.get("name", ""), base_b, cap_b, used, cap_b - used,
                 "（含已执行 %d，本次新增 %d）" % (used_done, used_new) if used_done else ""))
        else:
            # 只给档位时，账户层面唯一有信息量的汇总是档位分布
            dist = {}
            for r in mine:
                k = r["tier"]["level"] if r["tier"] else "?"
                dist[k] = dist.get(k, 0) + 1
            order = []
            for rr in rules:
                if rr["level"] not in order:
                    order.append(rr["level"])
            order.append("?")
            o("【%s】%s   档位分布  %s"
              % (acc["id"], acc.get("name", ""),
                 " · ".join("%s %d" % (k, dist[k]) for k in order if k in dist)))
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
            pbp = ("%.1f%%" % r["pb_pct"]) if r.get("pb_pct") is not None else "-"
            lv = t["level"] if t else "?"
            if r.get("tier_raw") and t and r["tier_raw"]["level"] != t["level"]:
                lv = "%s←%s" % (t["level"], r["tier_raw"]["level"])
            chg = r.get("change", "")
            note = "重开" if f.get("reopen") else ""
            if r.get("tier_note"):
                note = (note + " ⚑") if note else "⚑"
            if show_amounts:
                o(pad(i, 3) + pad(f["name"][:9], 19) + pad(idx_name[:6], 12) +
                  pad(pe, 7, "right") + pad(pct, 8, "right") + pad(pbp, 8, "right") +
                  pad(lv, 6, "center") + pad(chg, 9, "center") +
                  pad(r["want"], 6, "right") + pad(r["alloc"], 6, "right"))
            else:
                o(pad(i, 3) + pad(f["name"][:10], 21) + pad(idx_name[:6], 12) +
                  pad(pe, 7, "right") + pad(pct, 8, "right") + pad(pbp, 8, "right") +
                  pad(lv, 6, "center") + pad(chg, 9, "center") + pad(note, 8))

    # 档位变化：用户明确要求「档位变了要给出」，所以单独成段而不是藏在表格里
    moved = [r for r in rows if r.get("change_dir")]
    o()
    o("=" * 94)
    if prev_tiers:
        o("档位变化（对比 %s 那份记录）：" % prev_date)
        if not moved:
            o("  无变化。全部 %d 只维持原档位。" % len(rows))
        for r in moved:
            f = r["fund"]
            o("  %s %s   %s 档位 %s%s"
              % ("↑" if r["change_dir"] < 0 else "↓",
                 pad(f["name"][:14], 28),
                 ("PE分位 %.1f%% / PB分位 %.1f%%" % (r["pct"], r["pb_pct"]))
                 if r.get("pb_pct") is not None
                 else ("PE分位 %.1f%%" % r["pct"] if r["pct"] is not None else "无分位"),
                 r.get("change", ""),
                 "　（%s）" % r["tier_note"] if r.get("tier_note") else ""))
        if moved:
            o("   ↑ = 档位变便宜（可加码）　↓ = 档位变贵（收紧）")
    else:
        o("档位变化：本次为该口径下的第一份记录，从下次起显示与上一周的档位对比。")
    o("=" * 94)

    shifted = [r for r in rows if r.get("tier_note")]
    if shifted:
        o()
        o("双锚校验修正 %d 只（档位层面，不折算金额）：" % len(shifted))
        for r in shifted:
            o("   %s  %s 档 → %s 档　%s" % (
                pad(r["fund"]["name"][:14], 28),
                r["tier_raw"]["level"], r["tier"]["level"], r["tier_note"]))
        o("   标记 ⚑ 的行即被 PB 分位交叉修正过的标的。")

    if show_amounts:
        budget_all = sum((acc.get("weekly_budget_cap") or 0) for acc in accounts)
        o()
        o(pad("账户周预算合计", 24) + pad(round(budget_all), 8, "right") + " 元"
          + "      使用率 %.0f%%   未动用 %d 元"
          % (grand * 100.0 / budget_all if budget_all else 0,
             round(budget_all - grand)))

    # 档位图例（从 tier_rules 生成，避免说明与计算脱节）
    o()
    lo = None
    parts = []
    for r in rules:
        hi = r["max_percentile"]
        if lo is None:
            rng = "<%g%%" % hi
        elif hi >= 100:
            rng = ">%g%%" % lo
        else:
            rng = "%g-%g%%" % (lo, hi)
        fac = "停投" if r["factor"] <= 0 else "%.1f×" % r["factor"]
        parts.append("%s %s→%s" % (r["level"], rng, fac))
        lo = hi
    o("档位图例（分位→档位；系数只在 --amounts 模式下折算金额）：")
    for i in range(0, len(parts), 4):
        o("   " + "   ".join(parts[i:i + 4]))
    o("   「?」= 无分位数据，不代表不该买，只是无法用分位定档。")
    o("   「重开」= 该只此前已清仓、近期重新开仓，成本基准从重开日算起。")
    o("   只给档位、不给金额：投多少、投不投由你自己决定；档位变化会单独列出。")
    if pbc.get("enabled", True):
        o("   双锚校验：PB 分位比 PE 分位低 %.0fpct 以上 → 上修 1 档（PE 高是盈利下滑，"
          "不是价格贵）；高 %.0fpct 以上 → 下修 1 档（盈利虚高）。上限 ±1 档。"
          % (gap_pct, gap_pct))

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
        o("   建议只保留费率最低的一只；若决定都留着，可只给其中一只设 pool 上限。")

    stopped = [r for r in rows if r["tier"] and r["tier"]["factor"] == 0]
    if stopped:
        o()
        o("停投（高于停投线，只持有不再买入）：")
        for r in stopped:
            pb_txt = ("%.1f%%" % r["pb_pct"]) if r.get("pb_pct") is not None else "无"
            dual = r.get("pb_pct") is not None and r["pb_pct"] >= 47
            o("   %s  PE分位 %s / PB分位 %s　%s" % (
                pad(r["fund"]["name"][:14], 28),
                ("%.1f%%" % r["pct"]) if r["pct"] is not None else "-", pb_txt,
                "两锚共振确认偏贵" if dual else "仅 PE 分位偏高，PB 未同向确认"))

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
        f.write("## 档位变化\n\n")
        if moved:
            for r in moved:
                f.write("- **%s**：%s（%s）\n" % (
                    r["fund"]["name"], r.get("change", ""),
                    r["tier_note"] or "分位变化"))
        else:
            f.write("- 本次无档位变化\n")

    added = append_ledger(ledger_path, rows, run_date, asof, wk)

    # 分位快照：本轮全部标的（含本周未投的），供渲染层画完整估值标尺。
    # 只靠 ledger 不够——被砍到 0 的标的不进台账，页面上会退化成「无数据」。
    snap = {
        "run_date": run_date,
        "data_date": asof,
        "week": wk,
        "prev_date": prev_date,
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
            "pb": (r["eva"] or {}).get("pb"),
            "pb_pct": r.get("pb_pct"),
            "tier": r["tier"]["level"] if r["tier"] else "",
            "factor": r["tier"]["factor"] if r["tier"] else None,
            "cap_ratio": r["tier"].get("cap_ratio") if r["tier"] else None,
            "tier_raw": (r["tier_raw"] or {}).get("level", ""),
            "tier_note": r.get("tier_note", ""),
            "change": r.get("change", ""),
            "change_dir": r.get("change_dir", 0),
            "reopen": r["fund"].get("reopen"),
            "src": r.get("src", "-"),
            "want": r["want"], "alloc": r["alloc"],
            "done": r.get("done", 0) or 0,
            "ceiling": r["ceiling"], "pool": r["fund"].get("pool") or None,
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
