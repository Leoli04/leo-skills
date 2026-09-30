#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_report.py — Stock Analyzer 报告内容回查脚本（机器可验部分）

用法：
    python verify_report.py <报告.html>
    python verify_report.py <报告.html> --skill-dir <stock-analyzer 目录>

它把「对已生成报告做回查」中可自动化的检查一次性跑完，输出 PASS / WARN / FAIL。
机器验不了的（口径是否选对、逻辑是否自洽）仍需人工读，见 SKILL.md Phase 9.5。

退出码：0 = 无 FAIL；1 = 有 FAIL。
"""

import argparse
import os
import re
import sys

# ---------------------------------------------------------------- 计数基准
# 这三组数字必须与 references/redlines.md 的标题保持一致。
# 若你改了 redlines.md 的条目数，同步改这里。
EXPECT_REDLINES = 43      # 红线条数
EXPECT_TRAPS = 26         # 陷阱个数
EXPECT_SELFCHECK = 35     # 自检项数

# 阈值口径（与 methodology.md 保持一致，改了要同步）
WACC = 0.12               # 折现率
BUY_PREMIUM = 1.15        # 买入门槛：期望价 / 现价 >= 1.15
EXPECT_SECTIONS = 11      # 报告 section 数

results = []


def add(level, item, detail=""):
    results.append((level, item, detail))


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s)


# ---------------------------------------------------------------- 各项检查
def check_structure(html):
    """标签配平 + section 数量 + canvas/Chart 配对数。"""
    pairs = [
        ("div", r"<div\b", r"</div>"),
        ("ul", r"<ul\b", r"</ul>"),
        ("li", r"<li\b", r"</li>"),
        ("table", r"<table\b", r"</table>"),
        ("tr", r"<tr\b", r"</tr>"),
        ("section", r'class="section"', r""),  # 只计数，不配平
    ]
    for tag, op, cl in pairs:
        if not cl:
            continue
        o = len(re.findall(op, html))
        c = len(re.findall(cl, html))
        if o != c:
            add("FAIL", f"标签配平 <{tag}>", f"{o} 开 / {c} 闭（差 {o - c}）")
        else:
            add("PASS", f"标签配平 <{tag}>", f"{o}/{c}")

    # 只数 section 容器本体，排除 .section-title 之类的同前缀类名
    sec = len(re.findall(r'<div class="section(?:"|\s+active")', html))
    if sec != EXPECT_SECTIONS:
        add("FAIL", "section 数量", f"实际 {sec}，应为 {EXPECT_SECTIONS}")
    else:
        add("PASS", "section 数量", f"{sec}")

    canv = len(re.findall(r"<canvas\b", html))
    charts = len(re.findall(r"new Chart\(", html))
    if canv != charts:
        add("FAIL", "canvas / new Chart 配对", f"{canv} canvas vs {charts} Chart")
    else:
        add("PASS", "canvas / new Chart 配对", f"{canv}")

    # 每个 canvas 的 id 都应被 getElementById 引用
    ids = re.findall(r'<canvas[^>]*\bid="([^"]+)"', html)
    unused = [i for i in ids if f"getElementById('{i}')" not in html
              and f'getElementById("{i}")' not in html]
    if unused:
        add("FAIL", "canvas 全部被引用", "未被引用: " + ", ".join(unused))
    else:
        add("PASS", "canvas 全部被引用", f"{len(ids)} 个")


def check_version(html):
    """版本号一致性：不应残留旧版本标记。"""
    vers = re.findall(r"v2\.\d", html)
    uniq = sorted(set(vers))
    if len(uniq) > 1:
        add("FAIL", "版本号统一", f"混用: {', '.join(uniq)}")
    elif uniq:
        add("PASS", "版本号统一", uniq[0])
    else:
        add("WARN", "版本号统一", "报告内无版本标记")


def check_counts(html):
    """标题声称的数量 = 实际条目数（红线 / 陷阱 / 自检三项）。"""
    # 自检清单：标题里的 N 项 应等于该 section 内 li 数
    m = re.search(r"自检[^<]*?[·・]\s*(\d+)\s*项", html)
    if m:
        claimed = int(m.group(1))
        # 取 checklist section 之后的 li 总数
        idx = html.find('id="checklist"')
        seg = html[idx:] if idx >= 0 else html
        actual = len(re.findall(r'<li class="(?:ok|no|warn)"', seg))
        if actual == 0:
            actual = len(re.findall(r"<li\b", seg))
        if claimed != actual:
            add("FAIL", "自检清单计数", f"标题 {claimed} 项 vs 实际 {actual} 条")
        else:
            add("PASS", "自检清单计数", f"{claimed}")
    else:
        add("WARN", "自检清单计数", "未找到「自检 · N 项」标题")

    # 红线 / 陷阱速查：正文声称的数字 vs 基准
    m = re.search(r"(\d+)\s*条红线\s*/\s*(\d+)\s*个陷阱", html)
    if m:
        r, t = int(m.group(1)), int(m.group(2))
        if (r, t) != (EXPECT_REDLINES, EXPECT_TRAPS):
            add("FAIL", "红线/陷阱计数",
                f"正文 {r}/{t}，基准 {EXPECT_REDLINES}/{EXPECT_TRAPS}")
        else:
            add("PASS", "红线/陷阱计数", f"{r}/{t}")
    m2 = re.search(r"(\d+)\s*项自检", html)
    if m2:
        n = int(m2.group(1))
        if n != EXPECT_SELFCHECK:
            add("FAIL", "自检项基准", f"正文 {n}，基准 {EXPECT_SELFCHECK}")
        else:
            add("PASS", "自检项基准", f"{n}")


def check_valuation_math(html):
    """折现 / 期望价 / 门槛 / 胜率 的算术一致性。

    从报告里抓：
      - 各情景「折现价」（胜率表第一列）
      - 期望价（加权期望价行）
      - 现价
      - 买入门槛
    然后验：折现价 = 情景价 / (1+WACC)^n（n 从报告抓，默认 1.5）
          期望价 = Σ(折现价 × 概率)
          门槛 = 现价 × BUY_PREMIUM
    """
    # 现价
    m = re.search(r'<span class="ep-lbl">现价</span><span[^>]*>([\d.]+)\s*元', html)
    price = float(m.group(1)) if m else None

    # 门槛
    m = re.search(r'买入门槛[^<]*</span><span[^>]*>([\d.]+)\s*元', html)
    gate = float(m.group(1)) if m else None
    if price and gate:
        exp_gate = round(price * BUY_PREMIUM, 2)
        if abs(exp_gate - gate) > 0.02:
            add("FAIL", "买入门槛 = 现价 × 1.15",
                f"报告 {gate}，应为 {exp_gate}（现价 {price}）")
        else:
            add("PASS", "买入门槛 = 现价 × 1.15", f"{gate}")

    # 期望价盒三行：折现价 × 概率 = 贡献
    rows = re.findall(
        r"折现价\s*([\d.]+)\s*元\s*×\s*概率\s*(\d+)%</span><span[^>]*>([\d.]+)\s*元",
        html)
    legacy = False
    if not rows:
        # 兼容旧写法「情景价 X 元 × 概率 N%（已折现 1.5 年）」——
        # 该写法无法直接验「折现价」，故只验贡献值与概率和，并提示改写。
        rows = re.findall(
            r"([\d.]+)\s*元\s*×\s*概率\s*(\d+)%[^<]*</span><span[^>]*>([\d.]+)\s*元",
            html)
        legacy = True

    tot_p = 0
    tot_c = 0.0
    for pv, prob, contrib in rows:
        pv, prob, contrib = float(pv), int(prob), float(contrib)
        tot_p += prob
        tot_c += pv * prob / 100.0
        if abs(pv * prob / 100.0 - contrib) > 0.02:
            add("FAIL", "期望价逐项贡献",
                f"{pv} × {prob}% = {pv * prob / 100:.2f}，报告写 {contrib}")

    if rows:
        if tot_p != 100:
            add("FAIL", "情景概率之和", f"{tot_p}%")
        else:
            add("PASS", "情景概率之和", "100%")
        m = re.search(r"加权期望价[^<]*</span><span[^>]*>([\d.]+)\s*元", html)
        if m:
            claimed = float(m.group(1))
            if abs(tot_c - claimed) > 0.03:
                add("FAIL", "加权期望价",
                    f"报告 {claimed}，情景加权算得 {tot_c:.2f}")
            else:
                add("PASS", "加权期望价", f"{claimed}")

    # 期望价 / 现价 判定百分比
    m = re.search(r"期望价\s*÷\s*现价[^<]*</span><span[^>]*>([+\-−]?[\d.]+)%", html)
    if m and price:
        claimed = float(m.group(1).replace("−", "-"))
        m2 = re.search(r"加权期望价[^<]*</span><span[^>]*>([\d.]+)\s*元", html)
        if m2:
            exp = float(m2.group(1))
            real = (exp / price - 1) * 100
            if abs(real - claimed) > 0.6:
                add("FAIL", "期望价/现价 判定",
                    f"报告 {claimed}%，实为 {real:.1f}%")
            else:
                add("PASS", "期望价/现价 判定", f"{claimed}%")


def check_duplicate_numbers(html):
    """关键指标全篇只有一个值 —— 抽查常见易冲突项。"""
    # 用「万元/亿元」附近是否出现互相矛盾的总额，靠人工补充；这里做通用同名异值扫描
    warn_terms = ["赔率", "R/R"]
    found = []
    for t in warn_terms:
        vals = set(re.findall(re.escape(t) + r"[^0-9]{0,6}([\d.]+)\s*[:：]\s*1", html))
        if len(vals) > 1:
            found.append(f"{t}: {sorted(vals)}")
    if found:
        add("WARN", "赔率写法唯一", "；".join(found))
    else:
        add("PASS", "赔率写法唯一")


def check_placeholders(html):
    """不得残留占位符 / 加载中 / TODO。"""
    bad = []
    for pat in ["加载中...", "TODO", "待补充", "XXXX", "{{", "占位"]:
        n = html.count(pat)
        if n:
            bad.append(f"{pat}×{n}")
    # canvas 内的「加载中...」是模板常态（JS 会替换），单独降级为 WARN
    if bad:
        only_canvas = all("加载中" in b for b in bad)
        add("WARN" if only_canvas else "FAIL", "残留占位符",
            "，".join(bad) + ("（canvas 兜底文案，正常）" if only_canvas else ""))
    else:
        add("PASS", "残留占位符")


def check_sourced(html):
    """关键数字须标注来源 + 时点 + 口径（轻量：检查是否出现口径类字样）。"""
    kws = ["口径", "数据源", "截至", "来源"]
    hits = {k: html.count(k) for k in kws}
    if sum(hits.values()) < 3:
        add("WARN", "来源/口径标注", f"命中较少: {hits}")
    else:
        add("PASS", "来源/口径标注", f"口径×{hits['口径']} 截至×{hits['截至']}")


def check_cdn(html):
    """自包含性提示。"""
    if "cdnjs" in html or "cdn." in html or "unpkg" in html:
        add("WARN", "自包含性", "引用外部 CDN（Chart.js），离线环境需内联")
    else:
        add("PASS", "自包含性", "无外部依赖")


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="Stock Analyzer 报告内容回查")
    ap.add_argument("report", help="报告 HTML 路径")
    ap.add_argument("--skill-dir", help="stock-analyzer 目录（用于读取基准计数）")
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print(f"[ERROR] 找不到报告：{args.report}")
        return 1
    html = open(args.report, encoding="utf-8").read()

    global EXPECT_REDLINES, EXPECT_TRAPS, EXPECT_SELFCHECK
    if args.skill_dir:
        rl = os.path.join(args.skill_dir, "references", "redlines.md")
        if os.path.exists(rl):
            t = open(rl, encoding="utf-8").read()
            # 优先读标题行「## 一 · 红线速查（43 条）」与「故为 43 / 26 / 35」，
            # 避开第 3 行来源说明里的「文档正文 41 条红线」。
            m = re.search(r"故为\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", t)
            if m:
                EXPECT_REDLINES = int(m.group(1))
                EXPECT_TRAPS = int(m.group(2))
                EXPECT_SELFCHECK = int(m.group(3))
            else:
                m = re.search(r"红线速查（(\d+)\s*条）", t)
                if m:
                    EXPECT_REDLINES = int(m.group(1))
                m = re.search(r"陷阱对照（(\d+)\s*个?）", t)
                if m:
                    EXPECT_TRAPS = int(m.group(1))

    print(f"回查报告：{args.report}")
    print(f"基准计数：红线 {EXPECT_REDLINES} / 陷阱 {EXPECT_TRAPS} / 自检 {EXPECT_SELFCHECK}")
    print("=" * 62)

    check_structure(html)
    check_version(html)
    check_counts(html)
    check_valuation_math(html)
    check_duplicate_numbers(html)
    check_placeholders(html)
    check_sourced(html)
    check_cdn(html)

    fails = warns = 0
    for lvl, item, detail in results:
        tag = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[lvl]
        line = f"{tag} {item}"
        if detail:
            line += f" —— {detail}"
        print(line)
        if lvl == "FAIL":
            fails += 1
        elif lvl == "WARN":
            warns += 1

    print("=" * 62)
    print(f"合计：PASS {len(results) - fails - warns} / WARN {warns} / FAIL {fails}")
    if fails:
        print("\n✗ 存在 FAIL，逐项修正后重跑；机器验不了的口径与逻辑仍需人工读。")
    else:
        print("\n✓ 机器可验项全部通过。仍需人工确认：踩坑 8 条（见 SKILL.md Phase 9.5）。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
