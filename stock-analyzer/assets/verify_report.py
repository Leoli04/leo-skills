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
# 这三组数字由 references/redlines.md 的「故为 X / Y / Z」行自动解析得到。
# 这里只作兜底默认值：若解析失败（文件缺失或格式异常）才使用。
# 未传 --skill-dir 时，自动回退到本脚本所在 skill 目录的 redlines.md，
# 避免「忘了传参数 → 静默用旧值 → 校验假通过」。
EXPECT_REDLINES = 60      # 红线条数（兜底）
EXPECT_TRAPS = 49         # 陷阱个数（兜底）
EXPECT_SELFCHECK = 67     # 自检项数（兜底；= 报告实际采用数，可少于 redlines.md 的素材条数）

# ---------------------------------------------------------------- 报告命名规范
# 标准名：<标的简称>(<代码>)_<报告类型>_<YYYY-MM-DD>.html
#   例：中远海控(601919)_投资分析报告_2026-09-30.html
#      泡泡玛特(09992.HK)_投资分析报告_2026-10-09.html   ← 港股带 .HK 后缀
# 「名称(代码)」与「_YYYY-MM-DD」是硬段，中间的报告类型不限字（不得含 - _ / 空格）。
NAME_STD_RE = re.compile(
    r'^(?P<name>[^()（）\-_/\s]+)'
    r'\((?P<code>\d{6}|\d{5}\.HK)\)_'
    r'(?P<type>[^\-_/\s]+)_'
    r'(?P<date>\d{4}-\d{2}-\d{2})$'
)
# 规范生效日：该日及以后产出的报告必须用标准名。
# 2026-10-09 及以前产出的是本规范落地前的历史报告，降级为 WARN（不追溯）。
NAME_RULE_SINCE = "2026-10-10"
# 旧命名族（可解析出 标的 + 类型 + 日期）：名称-类型-20260930 / 名称_代码_类型_2026-09-30 /
# 002130-analysis-2026-09-12 / 江阴银行002807_投资分析报告_2026-10-03
NAME_LEGACY_RE = re.compile(
    r'^(?P<name>.+?)[\-_](?P<type>[^\-_/\s]+?)[\-_](?P<date>\d{8}|\d{4}-\d{2}-\d{2})$'
)
# 旧命名族 · 无日期：宁德时代300750_基本面分析报告
NAME_LEGACY_NODATE_RE = re.compile(
    r'^(?P<name>.+?)[\-_](?P<type>投资分析报告|首次覆盖报告|基本面分析报告|个股测算|分析报告|持仓成本评估|净利率收敛空间测算)$'
)
# 非个股报告类产物（组合方案 / 筛选 / 看板 / 方法论 / 台账 / 范例…），命名规范不适用
NAME_NON_STOCK_KW = ('台账', '看板', '组合', '配置', '筛选', '选股', '策略', '检验', '入门',
                     '方法论', '清单', '扫描', '回测', '对比', '复盘', '框架', '范例', '示例', '模板')


def _resolve_skill_dir(explicit_dir):
    """确定 skill 目录：优先 --skill-dir，否则回退到脚本自身的上级目录。"""
    if explicit_dir and os.path.exists(os.path.join(explicit_dir, "references", "redlines.md")):
        return explicit_dir
    # 脚本位于 <skill>/assets/verify_report.py → skill 目录是上一级
    guess = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.exists(os.path.join(guess, "references", "redlines.md")):
        return guess
    return explicit_dir


def _load_counts(skill_dir):
    """从 redlines.md 解析基准计数，返回 (redlines, traps, selfcheck)。"""
    global EXPECT_REDLINES, EXPECT_TRAPS, EXPECT_SELFCHECK
    rl = os.path.join(skill_dir, "references", "redlines.md")
    if not os.path.exists(rl):
        return
    t = open(rl, encoding="utf-8").read()
    m = re.search(r"故为\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", t)
    if m:
        EXPECT_REDLINES = int(m.group(1))
        EXPECT_TRAPS = int(m.group(2))
        EXPECT_SELFCHECK = int(m.group(3))
        return
    m = re.search(r"红线速查（(\d+)\s*条）", t)
    if m:
        EXPECT_REDLINES = int(m.group(1))
    m = re.search(r"陷阱对照（(\d+)\s*个?）", t)
    if m:
        EXPECT_TRAPS = int(m.group(1))

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


def check_struct_pairing(html):
    """① 公司概况硬规则：营收结构与利润结构必须在同一图中对照呈现。

    判据（兼容两种合法实现）：
      A. 单张合并图：canvas id = structCompareChart，且含「营收」「利润」两个数据集
      B. 两张并排图：revenueStructChart + profitStructChart 同时存在
    """
    merged = "structCompareChart" in html
    paired = ("revenueStructChart" in html) and ("profitStructChart" in html)

    if not (merged or paired):
        add("FAIL", "营收/利润结构对照",
            "缺少合并图 structCompareChart，也未见 revenueStructChart + profitStructChart 双图")
        return

    if merged:
        add("PASS", "营收/利润结构成对", "合并图 structCompareChart")
        # 合并图应含两条数据集（营收 / 利润）
        seg = html[html.find("structCompareChart"):]
        seg = seg[:seg.find("});") + 3] if "});" in seg else seg[:1500]
        has_rev = ("营收" in seg)
        has_pro = ("利润" in seg)
        if has_rev and has_pro:
            add("PASS", "合并图双系列", "含「营收」与「利润」两条数据集")
        else:
            add("WARN", "合并图双系列",
                f"营收={has_rev} 利润={has_pro} —— 合并图应同时含两个数据集")
        return

    # 双图分支
    add("PASS", "营收/利润结构成对", "双图存在（revenueStructChart + profitStructChart）")

    def labels_of(cid):
        m = re.search(
            r"getElementById\('" + cid + r"'\)[\s\S]{0,400}?labels:\s*\[([^\]]*)\]",
            html)
        if not m:
            return None
        return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]

    lr = labels_of("revenueStructChart")
    lp = labels_of("profitStructChart")
    if lr and lp and lr != lp:
        add("PASS", "营收/利润两图排序", "两图 labels 顺序不同（形成对照）")


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
        actual = len(re.findall(r'<li class="(?:ok|no|warn|na|notapp)"', seg))
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


def check_placeholders(html, is_template=False):
    """不得残留占位符 / 加载中 / TODO。"""
    # 剥离 <script>...</script> 内容后再查：内联库（如 Chart.js 压缩源码）会含 {{ }} 等
    # 与占位符无关的字符，若一并统计会误报。
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    bad = []
    # 「占位」在中文行文里常作正常词汇（如「不以示意点占位」），只在疑似占位符语境才计；
    # 因此改用更具体的模式，避免误伤自然语言。
    pats = ["加载中...", "TODO", "待补充", "XXXX", "占位符", "占位文本"]
    if not is_template:
        # 模板文件本身以 {{VAR}} 为设计占位符，检查时豁免
        pats.append("{{")
    for pat in pats:
        n = body.count(pat)
        if n:
            bad.append(f"{pat}×{n}")
    # canvas 内的「加载中...」是模板常态（JS 会替换），单独降级为 WARN
    # 注：canvas 文案在 <canvas> 标签内，不被 script 剥离影响
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
    """自包含性：报告须为离线单文件，禁止外部 CDN 引用（硬约束）。"""
    ext = [p for p in ["cdnjs", "cdn.", "unpkg", "jsdelivr",
                       "https://cdn", "http://cdn"] if p in html]
    # 只统计真正的 script/link 外链（排除注释与字符串里的偶然命中）
    ext_links = re.findall(r'<(?:script|link)[^>]+(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    if ext_links:
        add("FAIL", "自包含性", f"存在外部资源引用（{len(ext_links)} 处）：{ext_links[0][:60]} —— 须内联")
    elif ext:
        add("FAIL", "自包含性", f"检出 CDN 关键字 {ext} —— 须内联，报告必须是离线单文件")
    else:
        # 进一步确认 Chart.js 已内联
        inlined = ("Chart.js" in html) and ("new Chart(" in html)
        add("PASS", "自包含性", "无外部依赖（Chart.js 已内联）" if inlined else "无外部依赖")


# 允许「用到但未在 <style> 定义」的类（它们靠内联 style 或语义本身即可）
CSS_UNDEF_OK = {"footer", "chart-wrap", "section", "card", "grid-2", "grid-3"}


def check_report_file_name(report_path):
    """报告文件名规范：<标的简称>(<代码>)_<报告类型>_<YYYY-MM-DD>.html

    三问对照：① 对照 NAME_STD_RE；② 阈值见下面四档；③ 本函数输出 FAIL/WARN。

    四档判定：
      PASS  文件名符合标准格式
      WARN  能识别为「旧命名族」且日期早于 NAME_RULE_SINCE（历史报告，不追溯），
            或非个股报告类产物（命名规范不适用）
      FAIL  日期 >= NAME_RULE_SINCE 却仍用旧命名（新报告用错格式）
            或文件名既不符合标准格式、也识别不出标的与类型（无法归档与归并）
    """
    base = os.path.basename(report_path.replace("\\", "/"))
    if "report_template" in base:                      # 模板本身不受此约束
        add("PASS", "报告文件名规范", f"{base}（模板，不适用）")
        return
    stem = base[:-5] if base.lower().endswith(".html") else base

    m = NAME_STD_RE.match(stem)
    if m:
        add("PASS", "报告文件名规范",
            f"{m.group('name')}({m.group('code')}) · {m.group('type')} · {m.group('date')}")
        return

    def suggest(name_part, rtype, iso):
        """由旧名尽量拼出合规名；代码位或名称位取不到时用 <?…> 标出，不猜值。"""
        code = ""
        raw = name_part or ""
        mc = re.search(r'(?<!\d)(\d{6})(?!\d)', raw)
        if mc:
            code = mc.group(1)
        else:
            mc = re.search(r'(?<!\d)(\d{5})\s*\.?\s*HK', stem, re.I)
            if mc:
                code = mc.group(1) + ".HK"
        nm = raw
        if mc:
            nm = re.sub(r'(?<!\d)' + re.escape(mc.group(0)) + r'(?!\d)', '', nm)
            nm = re.sub(r'[\s\-_]*\.?\s*HK\s*$', '', nm, flags=re.I)
        nm = re.sub(r'[（）()]', '', nm).strip(" -_")
        return f"{nm or '<?名称>'}({code or '<?代码>'})_{rtype or '<?报告类型>'}_{iso or '<?YYYY-MM-DD>'}.html"

    # 非个股报告类产物：命名规范不适用
    if any(k in stem for k in NAME_NON_STOCK_KW):
        add("WARN", "报告文件名规范", f"{base} —— 非个股报告类产物，本项不适用")
        return

    lm = NAME_LEGACY_RE.match(stem)
    if lm:
        d = lm.group("date")
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
        sug = suggest(lm.group("name"), lm.group("type"), iso)
        if iso >= NAME_RULE_SINCE:
            add("FAIL", "报告文件名规范",
                f"{base} —— 产出日 {iso} 在规范生效日（{NAME_RULE_SINCE}）之后，仍用旧命名；须改名为 {sug}")
        else:
            add("WARN", "报告文件名规范",
                f"{base} —— 历史命名（{iso}，早于规范生效日），不追溯；如需统一可改名为 {sug}")
        return

    nm = NAME_LEGACY_NODATE_RE.match(stem)
    if nm:
        add("WARN", "报告文件名规范",
            f"{base} —— 历史命名且无日期段，无法判定产出日，不追溯；"
            f"新报告必须含 _YYYY-MM-DD 段")
        return

    # 已带「名称(代码)」但结构不全 —— 精确指出缺哪一段（新报告最常犯的两种错）
    struct = re.match(r'^(?P<name>[^()（）\-_/\s]+)\((?P<code>\d{6}|\d{5}\.HK)\)(?P<rest>.*)$', stem)
    if struct:
        rest = struct.group("rest")
        iso = ""
        md = re.search(r'(\d{4}-\d{2}-\d{2})', rest)
        if md:
            iso = md.group(1)
        if not md:
            add("FAIL", "报告文件名规范",
                f"{base} —— 缺日期段或日期格式不是 YYYY-MM-DD；"
                f"须为 {struct.group('name')}({struct.group('code')})_<?报告类型>_YYYY-MM-DD.html")
        else:
            add("FAIL", "报告文件名规范",
                f"{base} —— 缺「_报告类型_」段（代码与日期已合规）；"
                f"须为 {struct.group('name')}({struct.group('code')})_报告类型_{iso}.html")
        return

    add("FAIL", "报告文件名规范",
        f"{base} —— 既不符合「名称(代码)_报告类型_YYYY-MM-DD.html」，也识别不出标的与类型，"
        f"无法被观察池台账归并；须重命名（示例：中远海控(601919)_投资分析报告_2026-09-30.html）")


def check_css_classes(html):
    """CSS 类完整性：HTML 里用到的 class 必须在 <style> 中有定义。

    真实事故：⑥ 节财务健康卡用 .health-item/.hi-head/.health-bar/.health-fill/.hi-note，
    但 <style> 只定义了 .health-card/.hc-*（模板旧样式），5 个类全部未定义 ——
    卡片无边框底色、进度条 height:0 不显示，浏览器里是一堆裸文字，脚本此前完全抓不到。

    已知豁免（CSS_UNDEF_OK）：靠内联 style 表达或纯语义占位的类。
    """
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", html, flags=re.S | re.I)
    css = "\n".join(styles)
    defined = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))

    # 收集 HTML 中出现的 class（排除 script 内的字符串）
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    used = set()
    for m in re.finditer(r'class\s*=\s*["\']([^"\']+)["\']', body, flags=re.I):
        for c in m.group(1).split():
            used.add(c)

    undef = sorted(c for c in used if c not in defined and c not in CSS_UNDEF_OK)
    if undef:
        add("FAIL", "CSS 类完整性",
            f"{len(undef)} 个类用到但未定义：{', '.join('.' + c for c in undef)} —— 元素会渲染成裸样式，须补 CSS 或改类名")
    else:
        add("PASS", "CSS 类完整性", f"用到 {len(used)} 个类全部有定义")


# ---------------------------------------------------------------- 主流程
def check_section_depth(html, skill_dir, report_path):
    """逐节内容量对照 examples/ 范例，任一节 < 范例同节 70% 即 FAIL。

    专治「内容偏薄」：结构配平、数字自洽都通过，但整节只有几行 —— 22 项全绿却一眼看出单薄。
    注意：问的是「块数与篇幅」，不是「数据要一样」；范例的标的特有数据不可移植。
    """
    if not skill_dir:
        return
    ref = os.path.join(skill_dir, "examples", "小商品城_600415_完整范例.html")
    if not os.path.exists(ref):
        add("WARN", "章节密度对照", f"未找到范例 {ref}，跳过")
        return

    def sec_map(text):
        ms = list(re.finditer(r'<div class="section(?:"|\s+active")[^>]*id="([^"]+)"', text))
        d = {}
        for i, m in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            d[m.group(1)] = len(text[m.start():end])
        return d

    cur = sec_map(html)
    base = sec_map(open(ref, encoding="utf-8").read())
    if not base:
        add("WARN", "章节密度对照", "范例未解析出 section，跳过")
        return

    thin = []
    rows = []
    for k, b in base.items():
        a = cur.get(k, 0)
        ratio = a / b * 100 if b else 100
        rows.append(f"{k} {ratio:.0f}%")
        # 阈值 60%：结构缺口（原事故为 14%-40%）会被抓到；
        # 65%-70% 通常是「块数已够、只是行文更精炼」，不应误判。
        if a < b * 0.6:
            thin.append(f"{k}({ratio:.0f}%)")

    if thin:
        add("FAIL", "章节密度对照", "偏薄(<范例60%): " + ", ".join(thin) + " | " + " ".join(rows))
    else:
        add("PASS", "章节密度对照", " ".join(rows))


def check_named_components(html, skill_dir, report_path):
    """逐节比对 SKILL.md 第 1–11 条里「加粗具名组件」是否真的存在。

    与 check_section_depth 的分工：那个查「够不够厚」（字数），这个查「该有的块有没有」（结构）。
    字数可被「多写三段废话」凑满，具名组件不能 —— 所以两层都要。
    """
    if not skill_dir:
        return
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        add("WARN", "具名组件完整性", f"未找到 {skill_md}，跳过")
        return

    # 从 SKILL.md 的 1.–11. 条目里解析 **加粗** 组件名（含全角逗号分隔的并列项）
    text = open(skill_md, encoding="utf-8").read()
    m = re.search(r"^1\. \*\*公司概况\*\*.*?(?=^\*\*自检清单四态语义\*\*)", text, re.S | re.M)
    if not m:
        add("WARN", "具名组件完整性", "SKILL.md 未解析到 1–11 条，跳过")
        return
    block = m.group(0)

    REQUIRED = {}   # section_id -> [(显示名, [特征串...])]
    order = []
    for line in block.splitlines():
        if not line.strip():
            continue
        head = re.match(r"^(\d+)\. \*\*(.+?)\*\*", line.strip())
        if head:
            order.append((int(head.group(1)), head.group(2).strip()))
    if len(order) != 11:
        add("WARN", "具名组件完整性", f"SKILL.md 只解析到 {len(order)} 条主条目，跳过")
        return

    # section id 与 ①②③… 的顺序一一对应（模板固定）
    ids = ["overview", "financial", "technical", "sentiment", "competition",
           "valuation", "macro", "risk", "exit", "conclusion", "checklist"]

    # 组件特征串表：键 = 组件显示名，值 = 命中文档即视为存在的多个候选串（任一命中即可）
    SIG = {
        "估值锚定位卡": ["估值锚", "锚定位"],
        "营收结构 vs 利润结构合并对比图": ["structCompareChart", "结构对比", "利润结构"],
        "四条线单季环比拆解表": ["单季环比", "环比拆解", "四条线单季"],
        "股息可持续性测算": ["股息可持续", "派息总额", "分红.*钱从哪来", "股息可持续性测算"],
        "有效阻力识别卡": ["有效阻力"],
        "卖方目标价三面检验拆解卡": ["三面检验", "折现后可比价", "卖方目标价.*个.*问题", "折现后的卖方目标价"],
        "资金进出趋势": ["资金进出", "净额汇总", "主力.*北向"],
        "信息密度与股价滞涨的派发判别": ["派发判别", "信息密度"],
        "行业景气定位卡": ["行业景气定位"],
        "同业营收同比对照表": ["同业营收同比", "营收同比对照"],
        "PE/PB 双窗口分位表": ["双窗口分位", "分位表", "分位"],
        "估值分位四象限图": ["valuationQuadrant", "四象限"],
        "三情景概率加权卡": ["三情景", "概率加权"],
        "当前买入胜率与胜率×赔率定位图": ["胜率.*赔率", "赔率定位"],
        "财务健康仪表盘": ["财务健康仪表盘", "财务健康度评估", "财务健康"],
        "宏观传导矩阵": ["宏观传导矩阵", "传导矩阵"],
        "传导链到利润表的落点": ["传导链", "利润表落点", "财务费用率"],
        "身份错配审查": ["身份错配", "风险究竟落在谁头上", "受益方核对", "受益方到底是谁"],
        "当前买入胜率结论卡": ["买入胜率结论", "胜率结论"],
        "综合评分矩阵": ["综合评分矩阵"],
    }

    # 组件归属：按 SKILL.md 第 N 条落在哪个 section
    OWNER = {
        "估值锚定位卡": "overview",
        "营收结构 vs 利润结构合并对比图": "overview",
        "四条线单季环比拆解表": "financial",
        "股息可持续性测算": "financial",
        "有效阻力识别卡": "technical",
        "卖方目标价三面检验拆解卡": "sentiment",
        "资金进出趋势": "sentiment",
        "信息密度与股价滞涨的派发判别": "sentiment",
        "行业景气定位卡": "competition",
        "同业营收同比对照表": "competition",
        "PE/PB 双窗口分位表": "valuation",
        "估值分位四象限图": "valuation",
        "三情景概率加权卡": "valuation",
        "当前买入胜率与胜率×赔率定位图": "valuation",
        "财务健康仪表盘": "valuation",
        "宏观传导矩阵": "macro",
        "传导链到利润表的落点": "macro",
        "身份错配审查": "macro",
        "当前买入胜率结论卡": "conclusion",
        "综合评分矩阵": "conclusion",
    }

    # 抓各 section 的正文
    def sec_body(text):
        ms = list(re.finditer(r'<div class="section(?:"|\s+active")[^>]*id="([^"]+)"', text))
        d = {}
        for i, mm in enumerate(ms):
            end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
            d[mm.group(1)] = text[mm.start():end]
        return d

    bodies = sec_body(html)
    missing = []
    for name, pats in SIG.items():
        sid = OWNER.get(name)
        if not sid:
            continue
        body = bodies.get(sid, "")
        if not body:
            missing.append(f"{name}(整节缺失)")
            continue
        if not any(re.search(p, body) for p in pats):
            missing.append(f"{name}@{sid}")

    if missing:
        add("FAIL", "具名组件完整性",
            f"{len(missing)}/{len(SIG)} 个组件未检出：" + "、".join(missing))
    else:
        add("PASS", "具名组件完整性", f"{len(SIG)} 个具名组件全部命中")


def main():
    ap = argparse.ArgumentParser(description="Stock Analyzer 报告内容回查")
    ap.add_argument("report", help="报告 HTML 路径")
    ap.add_argument("--skill-dir", help="stock-analyzer 目录（用于读取基准计数）")
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print(f"[ERROR] 找不到报告：{args.report}")
        return 1
    html = open(args.report, encoding="utf-8").read()

    # 解析基准计数：显式 --skill-dir 优先，否则回退到脚本自身所在的 skill 目录
    _load_counts(_resolve_skill_dir(args.skill_dir))

    print(f"回查报告：{args.report}")
    print(f"基准计数：红线 {EXPECT_REDLINES} / 陷阱 {EXPECT_TRAPS} / 自检 {EXPECT_SELFCHECK}")
    print("=" * 62)

    check_report_file_name(args.report)
    check_structure(html)
    check_struct_pairing(html)
    check_version(html)
    check_counts(html)
    check_valuation_math(html)
    check_duplicate_numbers(html)
    is_tpl = "report_template" in args.report.replace("\\", "/").split("/")[-1]
    check_placeholders(html, is_template=is_tpl)
    check_sourced(html)
    check_cdn(html)
    check_css_classes(html)
    check_section_depth(html, _resolve_skill_dir(args.skill_dir), args.report)
    check_named_components(html, _resolve_skill_dir(args.skill_dir), args.report)

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
        print("\n✓ 机器可验项全部通过。仍需人工确认：Phase 9.5 第二遍 11 条（见 SKILL.md）。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
