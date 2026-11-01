#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同业归因核查（peer attribution audit）
=====================================

用途
----
做「行业横向 / 赛道景气」判断前，用本脚本把候选同业的三件事一次查清，
避免两类高频错误：

1. **把「报表利润负增长」当成「经营恶化」** —— 未剥离商誉减值、资产减值、
   非经常性损益，或只剥离了一个方向（只加回减值，忘掉非经常性收益）。
2. **把「收入结构不同」的公司当成「同赛道先行指标」** —— 只看「有没有该靶点
   的产品」，不看该产品占收入的多少。

典型误用案例（2026-11，艾力斯 vs 贝达）：
    贝达 2026 前三季报表归母 −12.20% → 被当作「三代 EGFR-TKI 赛道 β≈0」的证据。
    实际：① 1.52 亿元商誉减值 + 约 1.19 亿元非经常性收益并存，三个口径方向不同；
         ② 扣非同比 −52.86%、Q2/Q3 单季扣非连续为负，自身确实在恶化；
         ③ 但收入主体是一代埃克替尼与 ALK 恩沙替尼，三代贝福替尼仅小品种，
            不构成三代赛道的代理变量。
    结论差异：从「赛道不行」改为「份额在转移，个体在失血」。

用法
----
    python peer_attribution.py 300558 688578
    python peer_attribution.py 300558.SZ 688578.SH 002755
    python peer_attribution.py --json 300558 688578     # 机器可读

数据源（公开、无需鉴权）
------------------------
- 东方财富业绩报表 RPT_LICO_FN_CPD        ：累计营收 / 归母 / 同比 / 毛利率
- 东方财富利润表   RPT_DMSK_FN_INCOME     ：扣非归母 / 扣非同比 / 营业利润
- 东方财富 F10    BusinessAnalysis       ：主营构成（按产品）+ 经营评述原文

读取顺序与 SKILL.md 第 5 步一致：先查口径，再判可比性，最后才下结论。
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

EM_DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_F10 = "https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax"


# ---------------------------------------------------------------- 基础工具
def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX).read().decode(
        "utf-8", "ignore").lstrip("\ufeff")


def normalize_code(code: str) -> tuple[str, str]:
    """返回 (纯代码, SECUCODE)。支持 300558 / 300558.SZ / 688578.SH。"""
    c = code.strip().upper()
    if "." in c:
        pure, mkt = c.split(".", 1)
        return pure, "%s.%s" % (pure, mkt)
    if c.startswith(("6", "9")):
        return c, c + ".SH"
    if c.startswith(("0", "3")):
        return c, c + ".SZ"
    if c.startswith(("4", "8")):
        return c, c + ".BJ"
    return c, c + ".SZ"


def _num(v, default=None):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 数据获取
def fetch_perf(secucode: str, pages: int = 12) -> list[dict]:
    """业绩报表：累计营收 / 归母 / 同比。"""
    url = ("%s?reportName=RPT_LICO_FN_CPD&columns=ALL&filter=(SECUCODE%%3D%%22%s%%22)"
           "&pageNumber=1&pageSize=%d&sortColumns=REPORTDATE&sortTypes=-1"
           "&source=WEB&client=WEB") % (EM_DC, secucode, pages)
    d = json.loads(_get(url))
    res = d.get("result") or {}
    return res.get("data") or []


def fetch_income(secucode: str, pages: int = 12) -> list[dict]:
    """利润表：扣非归母 / 扣非同比 / 营业利润。"""
    url = ("%s?reportName=RPT_DMSK_FN_INCOME&columns=ALL&filter=(SECUCODE%%3D%%22%s%%22)"
           "&pageNumber=1&pageSize=%d&sortColumns=REPORT_DATE&sortTypes=-1"
           "&source=WEB&client=WEB") % (EM_DC, secucode, pages)
    d = json.loads(_get(url))
    res = d.get("result") or {}
    return res.get("data") or []


def fetch_f10(pure_code: str, secucode: str) -> dict:
    """F10：主营构成 + 经营评述。接口的 code 参数要带市场前缀。"""
    mkt = secucode.split(".")[-1]
    prefix = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(mkt, "SZ")
    url = "%s?code=%s%s" % (EM_F10, prefix, pure_code)
    try:
        return json.loads(_get(url))
    except Exception:
        return {}


# ---------------------------------------------------------------- 计算
def to_quarter_rows(perf: list[dict], income: list[dict]) -> list[dict]:
    """
    把累计口径拆成单季。只处理季报（03-31 / 06-30 / 09-30 / 12-31）。
    单季 = 本期累计 − 上期累计（同一年内）。
    """
    def build(rows, date_key, fields):
        out = {}
        for r in rows:
            dt = (r.get(date_key) or "")[:10]
            if len(dt) != 10:
                continue
            y, md = int(dt[:4]), dt[5:]
            out[(y, md)] = {f: _num(r.get(k)) for f, k in fields.items()}
        return out

    P = build(perf, "REPORTDATE", {
        "rev": "TOTAL_OPERATE_INCOME", "np": "PARENT_NETPROFIT",
        "rev_yoy": "YSTZ", "np_yoy": "SJLTZ", "gm": "XSMLL", "roe": "WEIGHTAVG_ROE"})
    I = build(income, "REPORT_DATE", {
        "dnp": "DEDUCT_PARENT_NETPROFIT", "dnp_yoy": "DPN_RATIO",
        "op": "OPERATE_PROFIT"})

    seq = ["03-31", "06-30", "09-30", "12-31"]
    years = sorted({y for (y, _) in P}, reverse=True)[:3]
    rows = []
    for y in sorted(years):
        prev_rev = 0.0     # 上一累计期营收
        prev_np = 0.0      # 上一累计期归母
        prev_dnp = 0.0     # 上一累计期扣非
        for md in seq:
            if (y, md) not in P:
                break
            cur = P[(y, md)]
            inc = I.get((y, md), {})
            dnp_cum = inc.get("dnp")
            rows.append({
                "year": y, "md": md, "label": "%d%s" % (y, _md_label(md)),
                "rev_q": (cur["rev"] or 0) - prev_rev,
                "np_q": (cur["np"] or 0) - prev_np,
                "dnp_q": (dnp_cum - prev_dnp) if dnp_cum is not None else None,
                "rev_cum": cur["rev"], "np_cum": cur["np"],
                "dnp_cum": dnp_cum,
                "rev_yoy": cur["rev_yoy"], "np_yoy": cur["np_yoy"],
                "dnp_yoy": inc.get("dnp_yoy"),
            })
            prev_rev = cur["rev"] or 0
            prev_np = cur["np"] or 0
            prev_dnp = dnp_cum if dnp_cum is not None else prev_dnp
    return rows


def _md_label(md: str) -> str:
    return {"03-31": "Q1", "06-30": "Q2", "09-30": "Q3", "12-31": "Q4"}.get(md, "")


def yoy(cur, base):
    """同比：处理「转亏 / 转盈」这类符号反转，避免百分比失真。"""
    if cur is None or base is None:
        return None
    if base > 0 and cur < 0:
        return "转亏"
    if base < 0 and cur > 0:
        return "转盈"
    if base == 0:
        return "—"
    return (cur / base - 1.0) * 100


def fmt_yoy(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    return "%+.1f%%" % v


# ---------------------------------------------------------------- 输出
def extract_review(f10: dict) -> list[str]:
    """经营评述中含「减值 / 剔除 / 一次性 / 非经常」的句子。"""
    import re
    jl = (f10 or {}).get("jyps") or []
    if not jl:
        return []
    raw = jl[0].get("BUSINESS_REVIEW") or ""
    txt = re.sub(r"<[^>]+>", "\n", raw)
    lines = [s.strip() for s in txt.split("\n") if s.strip()]
    kws = ("减值", "计提", "剔除", "一次性", "非经常", "商誉", "冲回")
    hits = [s for s in lines if any(k in s for k in kws)]
    # 长句切分，避免整段糊在一起
    out = []
    for s in hits:
        for seg in re.split(r"(?<=[。；])", s):
            seg = seg.strip()
            if seg and any(k in seg for k in kws):
                out.append(seg)
    return out[:8]


def extract_mix(f10: dict, limit: int = 2) -> list[tuple[str, list[dict]]]:
    """主营构成（按产品），取最近 limit 个报告期。"""
    rows = (f10 or {}).get("zygcfx") or []
    prod = [r for r in rows if r.get("MAINOP_TYPE") == "2"]
    if not prod:
        prod = [r for r in rows if r.get("MAINOP_TYPE") in ("1", "2")]
    dates = sorted({(r.get("REPORT_DATE") or "")[:10] for r in prod}, reverse=True)[:limit]
    out = []
    for dt in dates:
        sub = [r for r in prod if (r.get("REPORT_DATE") or "")[:10] == dt]
        sub.sort(key=lambda r: -(_num(r.get("MAIN_BUSINESS_INCOME"), 0) or 0))
        out.append((dt, sub))
    return out


def audit(code_input: str, as_json: bool = False) -> dict:
    pure, secu = normalize_code(code_input)
    perf = fetch_perf(secu)
    income = fetch_income(secu)
    f10 = fetch_f10(pure, secu)

    name = ""
    board = ""
    if perf:
        name = perf[0].get("SECURITY_NAME_ABBR") or ""
        board = perf[0].get("BOARD_NAME") or ""
    rows = to_quarter_rows(perf, income)
    latest = rows[-1] if rows else {}
    review = extract_review(f10)
    mix = extract_mix(f10)

    # 判读提示：只输出可自动判定的硬信号
    flags = []
    dnp_cum = latest.get("dnp_cum")
    np_cum = latest.get("np_cum")
    if dnp_cum is not None and np_cum is not None and (dnp_cum - np_cum) >= 0.5e8:
        flags.append("非经常性损益 %.2f 亿元（归母 − 扣非），引用利润前必须剥离" %
                     ((np_cum - dnp_cum) / 1e8))
    qs = [r for r in rows if r.get("dnp_q") is not None][-4:]
    neg = [r["label"] for r in qs if (r["dnp_q"] or 0) < 0]
    if len(neg) >= 2:
        flags.append("单季扣非连续为负：%s —— 拐点信号，累计口径不得掩盖" % "、".join(neg))
    if latest.get("rev_yoy") is not None and latest.get("rev_yoy") < 10:
        flags.append("累计营收同比仅 %+.1f%%，须拆单季确认是否已转负" % latest["rev_yoy"])
    if review:
        flags.append("经营评述含减值/剔除表述 %d 处，逐句核对后再引用利润数字" % len(review))

    result = {"code": pure, "secucode": secu, "name": name, "board": board,
              "rows": rows, "review": review,
              "mix": [{"date": d, "items": [
                  {"name": r.get("ITEM_NAME"),
                   "income": _num(r.get("MAIN_BUSINESS_INCOME")),
                   "ratio": _num(r.get("MBI_RATIO")),
                   "gm": _num(r.get("GROSS_RPOFIT_RATIO"))} for r in sub]}
                  for d, sub in mix],
              "flags": flags}
    if as_json:
        return result

    # ---------------- 文本输出
    print("=" * 78)
    print("%s %s   %s" % (pure, name, ("· " + board) if board else ""))
    print("-" * 78)
    print("[1] 单季拆解（亿元）—— 判拐点只看这一张，累计口径会平滑掉单季转负")
    print("    %-8s %10s %10s %10s %10s %10s" %
          ("季度", "营收", "营收同比", "归母", "扣非", "扣非同比"))
    prev_rev = {}
    for r in rows:
        base_rev = prev_rev.get((r["year"] - 1, r["md"]))
        base_dnp = prev_rev.get(("dnp", r["year"] - 1, r["md"]))
        print("    %-8s %10.2f %10s %10.2f %10s %10s" % (
            r["label"], r["rev_q"] / 1e8, fmt_yoy(yoy(r["rev_q"], base_rev)),
            r["np_q"] / 1e8, ("%.2f" % (r["dnp_q"] / 1e8)) if r["dnp_q"] is not None else "—",
            fmt_yoy(yoy(r["dnp_q"], base_dnp))
            if (r["dnp_q"] is not None and base_dnp is not None) else "—"))
        prev_rev[(r["year"], r["md"])] = r["rev_q"]
        if r["dnp_q"] is not None:
            prev_rev[("dnp", r["year"], r["md"])] = r["dnp_q"]

    print()
    print("[2] 三口径利润（最新累计期 %s）" % latest.get("label", ""))
    print("    报表归母      %8.2f 亿   同比 %s" % (
        (np_cum or 0) / 1e8, fmt_yoy(latest.get("np_yoy"))))
    if dnp_cum is not None:
        print("    扣非归母      %8.2f 亿   同比 %s   ← 经营质量的基准口径" % (
            dnp_cum / 1e8, fmt_yoy(latest.get("dnp_yoy"))))
    if dnp_cum is not None and np_cum is not None:
        diff = (np_cum - dnp_cum) / 1e8
        print("    非经常性损益  %8.2f 亿   %s" % (
            diff, "（正数=报表被非经常性收益抬高）" if diff > 0
            else "（负数=报表被非经常性损失压低）"))

    if mix:
        print()
        print("[3] 收入结构 —— 判「是不是同赛道代理」的唯一依据：该赛道收入占比")
        for dt, sub in mix:
            tot = sum((_num(r.get("MAIN_BUSINESS_INCOME"), 0) or 0) for r in sub)
            print("    %s（合计 %.2f 亿）" % (dt, tot / 1e8))
            for r in sub[:6]:
                inc = _num(r.get("MAIN_BUSINESS_INCOME"), 0) or 0
                ratio = _num(r.get("MBI_RATIO"))
                pct = ("%.1f%%" % (ratio * 100)) if ratio is not None and ratio <= 1.0001 \
                    else ("%.1f%%" % ((inc / tot * 100) if tot else 0))
                print("      %-28s %8.2f 亿  占 %6s" % (
                    (r.get("ITEM_NAME") or "")[:28], inc / 1e8, pct))

    if review:
        print()
        print("[4] 经营评述摘录（含 减值 / 剔除 / 一次性 的原文，引用利润前必读）")
        for s in review:
            print("    • " + s[:190])

    if flags:
        print()
        print("[5] 自动判读提示")
        for f in flags:
            print("    ⚠ " + f)

    print()
    print("判读顺序（缺一步就会归因错）：")
    print("  ① 先看[3]：该公司目标赛道收入占比是否 ≥50%？不是 → 只能作参照系，不能作先行指标")
    print("  ② 再看[2]：报表与扣非两个口径方向是否一致？不一致 → 读[4]找原因")
    print("  ③ 再看[1]：单季是否已转负？累计仍正不能否定单季转负")
    print("  ④ 最后才下结论：赛道萎缩（龙头增速转负）还是份额转移（本公司抢、对手失）")
    return result


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    as_json = "--json" in argv
    codes = [a for a in argv[1:] if not a.startswith("-")]
    if not codes:
        print(__doc__)
        return 1
    out = []
    for c in codes:
        try:
            r = audit(c, as_json=as_json)
            out.append(r)
        except urllib.error.URLError as e:
            print("  %s 取数失败（网络）：%s" % (c, e))
        except Exception as e:
            print("  %s 处理失败：%s" % (c, e))
    if as_json and out:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
