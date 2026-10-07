# -*- coding: utf-8 -*-
"""
A股粗筛器 · 把 stock-analyzer 的选股判据落成 12 条可执行横截面筛选
=====================================================================
本脚本是 `stock-screener` skill 的执行体。设计原则：

  1. **独立、幂等**。输出已存在则跳过，除非 --refresh。
  2. **所有阈值都写在 PROFILES 里**，改策略只改这张表，不动逻辑。
  3. **行业去重是可选增强**，走独立缓存；取不到行业时降级但不阻塞。
  4. **绝不用行业去重掩盖结果**。行业字段缺失时在输出里显式标注。

用法：
    python screen.py                      # 跑全部类型
    python screen.py --type value,dividend   # 只跑指定类型（逗号分隔）
    python screen.py --refresh            # 强制刷新（会重新联网）
    python screen.py --list               # 列出全部类型与判据
    python screen.py --no-industry        # 跳过行业补全（不联网取行业）
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, "candidates.json")
OUT_HTML = os.path.join(HERE, "候选池看板.html")
IND_CACHE = os.path.join(HERE, "industry_cache.json")

# 全市场横截面筛选工具（腾讯自选股数据），单文件、无需 npm install。
# ⚠️ 该工具是 WorkBuddy 插件缓存里的东西，不在本仓库内。搬到别的机器时
# 用环境变量 WESTOCK_TOOL_DIR 指向它的实际位置；未设置则回退到本机默认路径，
# 找不到时 _cli() 会明确报错而不是静默返回空。
CLI = "node scripts/index.js"
_ENV_DIR = os.environ.get("WESTOCK_TOOL_DIR", "").strip()
CLI_DIR = (_ENV_DIR if _ENV_DIR else
           "C:/Users/86130/.workbuddy/plugins/cache/cb_teams_marketplace"
           "/finance-data/1.6.0/skills/westock-tool")

# ⚠️ 筛选接口只回传「参与筛选的字段」。要展示的判据必须出现在条件里，
# 否则看板该列全是空值。恒真条件仅为取值，勿删。
_SHOW = ("ROETTM > 0, GrossIncomeRatio > 0, TORGrowRate > -999, "
         "NPParentCompanyYOY > -999, DividendRatioTTM > -999, PB > 0, "
         "DebtAssetsRatio > 0, ChgYtd > -999, Chg52W > -999, TurnoverRate > 0, "
         "RangePCT > 0, ORComGrowRate3Y > -999, NPPCCGrowRate3Y > -999, "
         "PE_TTMPct10Y > -999, PB_LFPct10Y > -999")


# ================================================================= 类型定义
# kind: core    = 找机会（可作候选）
#       danger  = 排雷（命中即风险提示，不作候选）
# money: 赚什么钱，用于分类展示
PROFILES = {

    # ---------------- 赚结构改善的钱 ----------------
    "prelude": dict(
        name="严格前奏池", kind="core", money="结构改善",
        desc="六道门槛核心全过：利润弹性≥3x ＋ 估值分位双低 ＋ 小自由流通",
        logic="G1 利润弹性≥3x / G1b 绝对增速≥15% / G3 PE·PB十年分位双<30% / "
              "G4 自由流通≤100亿。文档实测淘汰率 99.92%，是全池最严的一档。",
        order="PE_TTMPct10Y",
        cond=("intersect([TORGrowRate > 2, NPParentCompanyYOY >= 15, "
              "NPParentCompanyYOY / TORGrowRate >= 3, "
              "PE_TTM > 0, PE_TTMPct10Y > 0, PE_TTMPct10Y < 30, "
              "PB_LFPct10Y > 0, PB_LFPct10Y < 30, "
              "NegotiableMV < 10000000000, TotalMV > 3000000000, "
              "ROETTM > 12, " + _SHOW + "])"),
    ),
    "quality": dict(
        name="质量宽口径", kind="core", money="结构改善",
        desc="估值分位与盈利质量达标，暂不要求利润弹性倍数",
        logic="给前奏池兜底。适合还在筑底、结构改善尚未体现在利润上的标的。",
        order="PE_TTMPct10Y",
        cond=("intersect([PE_TTM > 0, PE_TTMPct10Y > 0, PE_TTMPct10Y < 35, "
              "PB_LFPct10Y > 0, PB_LFPct10Y < 35, "
              "NegotiableMV > 3000000000, NegotiableMV < 15000000000, "
              "TotalMV > 5000000000, ROETTM > 13, GrossIncomeRatio > 25, "
              "NPParentCompanyYOY > 0, " + _SHOW + "])"),
    ),
    "growth": dict(
        name="成长股", kind="core", money="业绩成长",
        desc="3年复合增速＋高毛利率＋盈利为正",
        logic="营收与利润3年复合双高 ＋ 毛利率>35%。"
              "⚠️ 实测单一强赛道会染满整个池（曾出现6只全是半导体存储），"
              "故本池默认开启行业去重。",
        order="NPPCCGrowRate3Y",
        ind_cap=3,
        cond=("intersect([TORGrowRate > 15, NPParentCompanyYOY > 25, "
              "ORComGrowRate3Y > 15, NPPCCGrowRate3Y > 20, "
              "GrossIncomeRatio > 35, ROETTM > 12, "
              "PE_TTM > 0, PE_TTM < 60, TotalMV > 5000000000, "
              "NegotiableMV > 3000000000, " + _SHOW + "])"),
    ),
    "smallgrowth": dict(
        name="小盘成长", kind="core", money="高弹性",
        desc="小市值＋高复合增速＋流通盘小",
        logic="市值 30~100亿 ＋ 利润3年复合>25%。"
              "⚠️ 小盘流动性差，务必用 NegotiableMV 约束，"
              "且须看筹码集中度，skill 对自由流通<30亿明确判为流动性差。",
        order="NPPCCGrowRate3Y",
        ind_cap=3,
        cond=("intersect([TotalMV < 10000000000, TotalMV > 3000000000, "
              "NPPCCGrowRate3Y > 25, ROETTM > 10, GrossIncomeRatio > 30, "
              "PE_TTM > 0, NegotiableMV < 8000000000, " + _SHOW + "])"),
    ),

    # ---------------- 赚估值修复的钱 ----------------
    "oversold": dict(
        name="超跌反弹", kind="core", money="估值修复",
        desc="52周位置低＋估值分位低＋年内大幅下跌",
        logic="Chg52W < -25% ＋ 现价处52周区间 35% 分位以下 ＋ PE十年分位<25%。"
              "用价格位置而非单纯跌幅 —— skill 禁用「跌了一半就是便宜」。",
        order="Chg52W",
        cond=("intersect([Chg52W < -25, PE_TTM > 0, "
              "PE_TTMPct10Y > 0, PE_TTMPct10Y < 25, "
              "Week52High > 0, Week52Low > 0, "
              "(ClosePrice - Week52Low) / (Week52High - Week52Low) < 0.35, "
              "NegotiableMV > 5000000000, TotalMV > 10000000000, "
              "ROETTM > 0, " + _SHOW + "])"),
    ),
    "value": dict(
        name="低估值", kind="core", money="估值均值回归",
        desc="PE绝对值低＋PE/PB分位双低＋盈利为正",
        logic="经典低估值：PE<15 ＋ PE/PB十年分位双低 ＋ 归母正增长 ＋ ROE>10%。"
              "与 value_trap 的区别是本池额外要求盈利为正且在增长。",
        order="PE_TTM",
        ind_cap=4,
        cond=("intersect([PE_TTM > 0, PE_TTM < 15, "
              "PE_TTMPct10Y > 0, PE_TTMPct10Y < 35, "
              "PB > 0, PB_LFPct10Y > 0, PB_LFPct10Y < 40, "
              "ROETTM > 10, NPParentCompanyYOY > 0, "
              "TotalMV > 10000000000, " + _SHOW + "])"),
    ),
    "turnaround": dict(
        name="困境反转", kind="core", money="均值回归",
        desc="低PB＋ROE处低位＋年内下跌＋已分红",
        logic="PB<2 ＋ ROE 3~12%（低位待回升）＋ 年内跌 ＋ 仍分红（证明现金未断）。"
              "⚠️ 候选最多（160+），是全池最宽的 —— "
              "因为「困境」本身定义模糊，必须人工逐只看反转证据。",
        order="PB",
        ind_cap=4,
        cond=("intersect([PB > 0, PB < 2, ROETTM > 3, ROETTM < 12, "
              "PE_TTM > 0, DividendRatioTTM > 0, "
              "DebtAssetsRatio > 40, DebtAssetsRatio < 75, "
              "ChgYtd < 0, TotalMV > 8000000000, " + _SHOW + "])"),
    ),

    # ---------------- 赚现金流的钱 ----------------
    "dividend": dict(
        name="高股息", kind="core", money="现金分红",
        desc="股息率高＋估值分位低＋ROE达标",
        logic="股息率TTM>3% ＋ PE/PB分位双<40% ＋ ROE>12%。"
              "⚠️ 高股息是 skill 的『禁用尺子』区：只适用于分红能持续的成熟标的，"
              "须用「派息总额 vs 经营现金流 vs 货币资金」验证分红的钱从哪来。",
        order="DividendRatioTTM",
        cond=("intersect([PE_TTM > 0, PE_TTMPct10Y > 0, PE_TTMPct10Y < 40, "
              "PB_LFPct10Y > 0, PB_LFPct10Y < 40, DividendRatioTTM > 3, "
              "NegotiableMV > 5000000000, TotalMV > 10000000000, "
              "ROETTM > 12, " + _SHOW + "])"),
    ),
    "bluechip": dict(
        name="白马", kind="core", money="稳健复利",
        desc="高ROE＋低波动＋有分红＋大盘",
        logic="ROE 15~30% ＋ PE<25 ＋ 日振幅<4%（波动低）＋ 股息>2% ＋ 市值>300亿。"
              "对应 skill 的「成熟制造+高分红」形态，主锚 DDM＋正常化PE。",
        order="DividendRatioTTM",
        cond=("intersect([ROETTM > 15, ROETTM < 30, "
              "PE_TTM > 0, PE_TTM < 25, "
              "PE_TTMPct10Y > 0, PE_TTMPct10Y < 50, "
              "PB_LFPct10Y > 0, PB_LFPct10Y < 60, DividendRatioTTM > 2, "
              "RangePCT < 4, GrossIncomeRatio > 30, "
              "TotalMV > 30000000000, " + _SHOW + "])"),
    ),
    "cyclebottom": dict(
        name="周期底部", kind="core", money="周期反转",
        desc="PB分位低＋负债率高（重资产）＋年内跌",
        logic="PB十年分位<25% ＋ 资产负债率>55%（重资产特征）＋ 年内跌>10%。"
              "⚠️ 本池只做「位置初筛」。周期股必须走 skill 的周期专章："
              "定位五要素（商品价分位/供给/需求/库存/成本）缺一不可，"
              "且底部阶段禁用 PE。",
        order="PB_LFPct10Y",
        ind_cap=3,
        cond=("intersect([PB > 0, PB_LFPct10Y > 0, PB_LFPct10Y < 25, "
              "PE_TTM > 0, DebtAssetsRatio > 55, ChgYtd < -10, "
              "TotalMV > 15000000000, NPParentCompanyYOY > 0, " + _SHOW + "])"),
    ),

    # ---------------- 交易型（非常规持仓逻辑） ----------------
    "grid": dict(
        name="网格交易", kind="trade", money="波动",
        desc="日振幅够大＋流动性够好＋估值不离谱",
        logic="日振幅>2% ＋ 成交额>5亿 ＋ 换手 1~12% ＋ PE<30 且 PB分位<50%。"
              "⚠️ 重要局限：RangePCT 只是【当日】振幅，不是历史波动率。"
              "真正的网格间距须用 ATR / 历史波动率自算（本工具不提供），"
              "故本池只能筛出「今天活跃」的候选，不能保证未来的波动率。",
        order="RangePCT",
        cond=("intersect([RangePCT > 2, TurnoverValue > 500000000, "
              "TurnoverRate > 1, TurnoverRate < 12, "
              "PE_TTM > 0, PE_TTM < 30, PB > 0, PB_LFPct10Y < 50, "
              "TotalMV > 20000000000, NegotiableMV > 10000000000, "
              "DebtAssetsRatio < 70, " + _SHOW + "])"),
    ),

    # ---------------- 排雷池（命中=风险，不是候选） ----------------
    "value_trap": dict(
        name="周期陷阱（排雷）", kind="danger", money="假便宜",
        desc="PE分位低但PB分位高 —— 盈利在顶，不是便宜",
        logic="PE_TTMPct10Y < 20% 【且】 PB_LFPct10Y > 60%。"
              "这是 skill 反复警告的教科书陷阱：PE 低是因为分母在峰值，"
              "不是股价便宜。命中即提示风险，**不可作候选**。",
        order="PB_LFPct10Y",
        cond=("intersect([PE_TTM > 0, PE_TTMPct10Y > 0, PE_TTMPct10Y < 20, "
              "PB_LFPct10Y > 60, DebtAssetsRatio > 50, "
              "ChgYtd < 5, TotalMV > 10000000000, " + _SHOW + "])"),
    ),
}


# 各类型在看板上展示的列（按类型裁剪，避免 15 列挤爆）
COLS = {
    "_base":  [("ClosePrice", "现价"), ("TotalMV", "总市值"),
               ("NegotiableMV", "自由流通"), ("ChangePCT", "当日")],
    "val":    [("PE_TTM", "PE_TTM"), ("PE_TTMPct10Y", "PE分位10Y"),
               ("PB_LFPct10Y", "PB分位10Y")],
    "qual":   [("ROETTM", "ROE_TTM"), ("GrossIncomeRatio", "毛利率"),
               ("DebtAssetsRatio", "负债率")],
    "grow":   [("TORGrowRate", "营收同比"), ("NPParentCompanyYOY", "归母同比"),
               ("ORComGrowRate3Y", "营收3Y"), ("NPPCCGrowRate3Y", "利润3Y")],
    "price":  [("Chg52W", "52周涨跌"), ("ChgYtd", "年内涨跌")],
    "trade":  [("RangePCT", "日振幅"), ("TurnoverRate", "换手率"),
               ("DividendRatioTTM", "股息率")],
}
PROFILE_COLS = {
    "prelude": "val qual grow", "quality": "val qual grow",
    "growth": "val qual grow", "smallgrowth": "val qual grow price",
    "oversold": "val qual price", "value": "val qual grow",
    "turnaround": "val qual price", "dividend": "val qual trade",
    "bluechip": "val qual trade", "cyclebottom": "val qual price",
    "grid": "trade val qual", "value_trap": "val qual price",
}


# ================================================================= 数据获取
def _cli(args, retries=3):
    """调用筛选工具。失败时退避重试 —— 实测偶发空返回。"""
    # 依赖前置检查：cwd 指向不存在的目录时 subprocess 只会抛 FileNotFound
    # 或返回非 0，混在重试里表现为「跑出 12 个空池」，很难排查。
    if not os.path.isfile(os.path.join(CLI_DIR, "scripts", "index.js")):
        raise SystemExit(
            f"!! 找不到横截面筛选工具：{CLI_DIR}\\scripts\\index.js\n"
            f"   它是 WorkBuddy 插件缓存里的 westock-tool，不在本仓库内。\n"
            f"   请设置环境变量指向它：\n"
            f"     set WESTOCK_TOOL_DIR=<westock-tool 目录>\n"
            f"   目录内应包含 scripts/index.js 与 package.json。")
    for i in range(retries):
        out = subprocess.run(f"{CLI} {args}", shell=True, cwd=CLI_DIR,
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0 and out.stdout.strip():
            try:
                return json.loads(out.stdout)
            except json.JSONDecodeError:
                pass
        time.sleep(1.5 * (i + 1))
    return []


def load_industry(codes, allow_net):
    """补行业分类。返回 (映射, 数据来源说明)。

    行业字段无法由筛选表达式直接取（实测 `SW1Name > 0` / `IndustryName > 0`
    均返回「数据为空」——BI 类字段只支持展示不支持表达式），必须外部拉取。

    ⚠️ **数据源用新浪而非东财**：东财 push2 / 82.push2 / 7.push2 三个域名在
    本机已连续实测 RemoteDisconnected（限流），冷却 90 秒不恢复。新浪分两步、
    每步轻量，实测可用。合并两套分类源以提升覆盖：
      1) newSinaHy.php  → 49 个新浪二级行业（玻璃行业、船舶制造…），粒度细
      2) newFLJK.php    → 84 个证监会门类（农业、林业…），粒度粗但覆盖广
    单用第1 套实测只覆盖候选池 61%，两套并用可提升到八成以上。
    ⚠️ 行业数据本身**不参与限流**（见 apply_industry_cap），未覆盖的股票照常
    入选，只在看板标 `-`，避免把互不相关的股票当成同一行业误剔。

    策略：本地缓存 → 否则批量拉取 → 失败降级为空（不阻塞主流程）。
    """
    if os.path.exists(IND_CACHE):
        with open(IND_CACHE, encoding="utf-8") as f:
            return json.load(f), "本地缓存"
    if not allow_net:
        return {}, "已跳过"

    def _get(url):
        r = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
        return urllib.request.urlopen(r, timeout=25).read().decode("gbk", "ignore")

    def _get_json(url):
        t = _get(url).strip()
        return json.loads(t) if t and t != "null" else []

    def _parse_board(url):
        """从新浪板块清单脚本里解出 {node: 行业名}。"""
        body = re.search(r"=\s*(\{.*\})\s*;?\s*$", _get(url), re.S)
        if not body:
            return {}
        out = {}
        for key, val in json.loads(body.group(1)).items():
            parts = str(val).split(",")
            if len(parts) > 1 and parts[1]:
                out[key] = parts[1]
        return out

    #两套分类源合并：newSinaHy（49 个新浪二级行业，粒度细）+
    #   newFLJK（84 个证监会门类，粒度粗但覆盖广）。
    #   单用前者实测只覆盖候选池 61%，两套并用可显著提升。
    m, nodes = {}, {}
    try:
        for src in ("https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
                    "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php"):
            try:
                for k, v in _parse_board(src).items():
                    nodes.setdefault(k, v)
            except Exception:
                continue

        for key, name in nodes.items():
            try:
                u = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/"
                     f"json_v2.php/Market_Center.getHQNodeData?page=1&num=200"
                     f"&sort=symbol&asc=1&node={key}&symbol=&_s_r_a=page")
                for it in _get_json(u):
                    m[re.sub(r"^(sh|sz|bj)", "", it.get("code", ""))] = name
            except Exception:
                continue          # 单板块失败不整体降级
            time.sleep(0.2)         # 轻节流，133 个板块约 27 秒
    except Exception as e:
        return {}, f"取数失败（{type(e).__name__}）已降级"

    if m:
        with open(IND_CACHE, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        return m, f"新浪行业分类（{len(nodes)} 个板块 / {len(m)} 只）"
    return {}, "取数失败已降级"


def apply_industry_cap(rows, ind_map, cap):
    """同行业限 cap 只。返回 (保留行, 被限掉的行业清单)。

    ⚠️ **行业缺失的股票不参与限流**。它们各自行业未知，若归到同一个
    「未分类」桶里限流，会把大量互不相关的股票当成同一行业误剔
    （实测「成长股」池因此被砍掉 46 只，实际全是不同公司）。
    正确做法：未知行业一律放行，只在返回值里标注未覆盖。
    """
    if not cap or not ind_map:
        return rows, []
    seen, out, dropped = {}, [], []
    for r in rows:
        code = re.sub(r"^(sh|sz|bj)", "", r.get("code", ""))
        ind = ind_map.get(code)
        if not ind:                      # 行业未知 → 不限流，仅标注
            r["_industry"] = "-"
            out.append(r)
            continue
        if seen.get(ind, 0) >= cap:
            dropped.append(ind)
            continue
        seen[ind] = seen.get(ind, 0) + 1
        r["_industry"] = ind
        out.append(r)
    return out, sorted(set(dropped))


# ================================================================= 看板生成
def build_html(data, ind_src, types, ind_degraded=False):
    e = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def yi(v):
        n = num(v)
        return "-" if n is None else f"{n / 1e8:,.1f}"

    def nfmt(v, d=1):
        n = num(v)
        return "-" if n is None else f"{n:,.{d}f}"

    tabs, bodies, radios = [], [], []
    for i, k in enumerate(types):
        p = PROFILES[k]
        rows = data.get(k, [])
        radios.append(f'<input type="radio" class="r" name="g" id="g{k}" '
                      f'{"checked" if i == 0 else ""}>')
        badge = ('<span class="tag danger">排雷</span>' if p["kind"] == "danger"
                 else '<span class="tag trade">交易型</span>' if p["kind"] == "trade"
                 else '<span class="tag core">找机会</span>')
        tabs.append(f'<label class="nav" for="g{k}">{p["name"]} <b>{len(rows)}</b></label>')

        # 按类型挑列
        groups = PROFILE_COLS.get(k, "val qual").split()
        cols = []
        for g in groups:
            cols += COLS["_base"] + COLS[g]
        seen_c, cols = set(), []
        for c in cols:
            if c[0] not in seen_c:
                seen_c.add(c[0])
                cols.append(c)
        thead = (f"<tr><th>名称</th><th>现价</th>"
                 f"<th class='up'>当日%</th><th>总市值</th><th>自由流通</th>"
                 + "".join(f"<th>{c[1]}</th>" for c in cols[5:]) + "</tr>")

        trs = []
        for r in rows:
            chg = num(r.get("ChangePCT")) or 0
            ind = r.get("_industry", "")
            tds = [f'<td class="nm"><b>{e(r.get("name"))}</b>'
                   f'<span class="code">{e(r.get("code"))}</span>'
                   + (f'<span class="ind">{e(ind)}</span>' if ind else "")
                   + "</td>",
                   f'<td class="mono">{nfmt(r.get("ClosePrice"), 2)}</td>',
                   f'<td class="mono {"up" if chg >= 0 else "down"}">'
                   f'{chg:+.2f}</td>',
                   f'<td class="mono">{yi(r.get("TotalMV"))}</td>',
                   f'<td class="mono">{yi(r.get("NegotiableMV"))}</td>']
            for c in cols[5:]:
                v = num(r.get(c[0]))
                tds.append(f'<td class="mono">{nfmt(v, 2)}</td>')
            trs.append(f'<tr>{"".join(tds)}</tr>')
        if not trs:
            trs.append(f'<tr><td colspan="{len(cols) + 5}" class="empty">'
                       f'本次无命中</td></tr>')

        bodies.append(f"""<div class="sec" id="g{k}">
<div class="ph">{badge}<b>{p['name']}</b>
<span class="ds">{e(p['desc'])}</span><span class="ds">{e(p['logic'])}</span></div>
<div class="tblwrap"><table><thead>{thead}</thead><tbody>{''.join(trs)}</tbody></table></div>
</div>""")

    rules = "".join(
        f'body:has(#g{k}:checked) #g{k}{{display:block}}'
        f'body:has(#g{k}:checked) label[for="g{k}"]'
        f'{{color:#e94560;border-bottom-color:#e94560;font-weight:500}}'
        for k in types)

    counts = " · ".join(f"{PROFILES[k]['name']} {len(data.get(k, []))}" for k in types)
    degraded_box = ""
    if ind_degraded:
        names = "、".join(PROFILES[k]["name"] for k in types
                          if PROFILES[k].get("ind_cap"))
        degraded_box = f"""<div class="warn2">
<b>行业去重未生效</b>（行业数据源限流，本次已降级）。受影响：{e(names)}。
这些池可能出现「候选被单一行业占满」的情况 —— 请人工检查行业集中度后再选型。
恢复后重跑 <code>--refresh</code> 即可自动生效。
</div>"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股粗筛候选池</title><style>
*{{box-sizing:border-box;box-shadow:none}}
body{{margin:0;background:#141821;color:#dfe4ee;
 font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1860px;margin:0 auto;padding:20px}}
h1{{font-size:19px;margin:0 0 4px;font-weight:500}}
.sub{{color:#8b93a7;font-size:12.5px;margin-bottom:6px}}
.note2{{color:#6b7386;font-size:12px;margin-bottom:16px}}
.navwrap{{display:flex;flex-wrap:wrap;gap:6px 8px;margin-bottom:16px}}
.nav{{display:inline-block;padding:7px 13px;white-space:nowrap;
 background:#1e2430;border:1px solid #2c3444;border-bottom:2px solid transparent;
 border-radius:6px;cursor:pointer;font-size:12.5px}}
.nav b{{color:#e94560;margin-left:3px;font-family:Consolas,monospace}}
.r{{display:none}}.sec{{display:none}}
.tblwrap{{overflow-x:auto;border-radius:6px;border:1px solid #2c3444}}
table{{width:100%;border-collapse:collapse;background:#1a1f2b;min-width:1080px}}
.ph{{background:#1a2030;border-left:3px solid #e94560;
 padding:11px 15px;margin-bottom:12px;border-radius:0 6px 6px 0}}
.ph b{{font-size:14px;margin:0 7px 0 0;font-weight:500}}
.ds{{display:block;color:#8b93a7;font-size:12px;margin-top:3px}}
.tag{{font-size:10.5px;padding:2px 7px;border-radius:9px;
 vertical-align:1.5px;margin-right:2px}}
.tag.core{{background:#1d3a2f;color:#5DCAA5}}
.tag.trade{{background:#3a3320;color:#EF9F27}}
.tag.danger{{background:#4a2020;color:#F09595}}
.ph:has(.tag.danger){{border-left-color:#E24B4A}}
.ph:has(.tag.trade){{border-left-color:#EF9F27}}
th{{background:#202634;color:#8b93a7;font-size:10.5px;font-weight:500;
 text-align:right;padding:7px 9px;border-bottom:1px solid #2c3444;white-space:nowrap}}
th:first-child{{text-align:left}}
td{{padding:7px 9px;border-bottom:1px solid #212836;text-align:right;
 white-space:nowrap}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1e2430}}
.nm{{text-align:left}}
.nm b{{font-size:13px;font-weight:500;margin-right:6px}}
.code{{color:#5a6274;font-size:10.5px;font-family:Consolas,monospace}}
.ind{{color:#c9a227;font-size:10.5px;margin-left:5px}}
.mono{{font-family:Consolas,monospace;font-size:12.5px}}
.up{{color:#e94560}}.down{{color:#00c853}}
.empty{{text-align:center;color:#6b7386;padding:26px}}
.warn{{margin-top:18px;padding:13px 16px;background:#2a2410;
 border-left:3px solid #EF9F27;border-radius:0 6px 6px 0;
 color:#d6c9a8;font-size:12.5px}}
.warn b{{color:#FAC775}}
.warn2{{margin-bottom:16px;padding:12px 15px;background:#2a1818;
 border-left:3px solid #E24B4A;border-radius:0 6px 6px 0;
 color:#e0c0c0;font-size:12.5px}}
.warn2 b{{color:#F09595}}
.warn2 code{{background:#1a1f2b;padding:1px 5px;border-radius:3px;
 font-family:Consolas,monospace;font-size:11.5px}}
</style></head><body><div class="wrap">
<h1>A股粗筛候选池</h1>
<div class="sub">{len(types)} 类 · {e(counts)}</div>
<div class="note2">生成时间 {time.strftime('%Y-%m-%d %H:%M')} ·
 行业数据：{e(ind_src)} · 全市场约 5,100 只，
 每池均为横截面初筛，深度不足</div>
{degraded_box}
{''.join(radios)}
<div class="navwrap">{''.join(tabs)}</div>
{''.join(bodies)}
<div class="warn">
<b>这是初筛结论，深度不足</b>，不得作为加仓依据，也不得与完整覆盖结论并列。<br>
横截面筛选只覆盖可量化判据（利润增速、估值分位、盈利质量、流动性、价格位置）。
<b>未做且必须做的</b>：估值锚归类、单季环比拆解、经营现金流质量、
分部收入结构、景气档位定位、筹码结构、催化传导时间窗 —— 选型后再走完整评估。<br>
<b>「周期陷阱」是排雷池</b>，命中表示 PE 低是因为盈利在顶，不作候选。
</div>
</div><style>{rules}</style></body></html>"""


# ================================================================= 主流程
def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refresh = "--refresh" in sys.argv
    no_ind = "--no-industry" in sys.argv

    if "--list" in sys.argv:
        print(f"{'类型':<12}{'名称':<16}{'类别':<6}{'候选数':<8}判据")
        for k, p in PROFILES.items():
            kind = {"core": "找机会", "danger": "排雷", "trade": "交易"}[p["kind"]]
            print(f"{k:<12}{p['name']:<16}{kind:<6}{'-':<8}{p['desc']}")
        return

    types = [a for a in args if a in PROFILES]
    bad = [a for a in args if a not in PROFILES and a != "screen.py"]
    if bad:
        print(f"!! 未知类型: {', '.join(bad)}（用 --list 查看全部）")
        return
    types = types or list(PROFILES)

    # 缓存只认「全量 + 全类型」。指定子集时若复用全量缓存，
    # 看板会显示未跑的类型的数据（--type grid 却列出成长股）。
    full = (set(types) == set(PROFILES) and os.path.exists(OUT_JSON))
    if full and not refresh:
        print(f"输出已存在，跳过（--refresh 强制刷新）: {OUT_JSON}")
        with open(OUT_JSON, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
        for k in types:
            p = PROFILES[k]
            print(f"[{k:<12}] {p['name']} ...", end=" ", flush=True)
            rows = _cli(f'filter "{p["cond"]}" --limit 120 '
                        f'--orderby {p["order"]} --raw')
            data[k] = rows
            print(f"{len(rows)} 只")
            time.sleep(1.2)

    # 行业补全 + 同行业限流
    need_ind = any(PROFILES[k].get("ind_cap") for k in types)
    ind_map, ind_src = ({}, "未启用")
    ind_degraded = False
    if need_ind and not no_ind:
        allcodes = set()
        for k in types:
            if PROFILES[k].get("ind_cap"):
                allcodes |= {re.sub(r"^(sh|sz|bj)", "", r.get("code", ""))
                             for r in data.get(k, [])}
        ind_map, ind_src = load_industry(allcodes, allow_net=True)
        if ind_map:
            cover = sum(1 for c in allcodes if ind_map.get(c))
            pct = 100.0 * cover / max(1, len(allcodes))
            print(f"  行业覆盖率 {cover}/{len(allcodes)} ({pct:.0f}%)"
                  f" · 未覆盖的股票不做同行业限流，仅标注")
            for k in types:
                cap = PROFILES[k].get("ind_cap")
                if not cap:
                    continue
                kept, dropped = apply_industry_cap(data[k], ind_map, cap)
                if dropped:
                    print(f"  {PROFILES[k]['name']}: 行业去重限 {cap} 只/行业，"
                          f"剔除 {len(data[k]) - len(kept)} 只（{', '.join(dropped)}）")
                data[k] = kept
        else:
            skipped = [PROFILES[k]["name"] for k in types
                       if PROFILES[k].get("ind_cap")]
            print(f"  !! 行业数据不可用，以下池未做同行业去重：{', '.join(skipped)}")
            print("     新浪行业接口取数失败。恢复后重跑 --refresh 即可；"
                  "在此之前请人工检查候选是否被单一行业占满。")
            ind_degraded = True
            ind_src += "（行业去重未生效，见下方提示）"
    elif no_ind:
        ind_src = "已跳过（--no-industry）"

    # 子集跑时合并进全量缓存，不覆盖其它类型的结果
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, encoding="utf-8") as f:
                merged = json.load(f)
            if set(merged) >= set(types):
                merged.update(data)
                data = merged
        except (json.JSONDecodeError, OSError):
            pass

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    html = build_html(data, ind_src, types, ind_degraded)

    # 自检：radio 与 has 规则必须成对，且 rules 必须落在 <style> 里。
    # 这三项缺一，页面就是「导航在、内容全空」——结构检查看不出来，只有截图能发现。
    n_radio = html.count('class="r"')
    n_rule = html.count("body:has(")
    assert n_radio == len(types), f"radio 数 {n_radio} != 类型数 {len(types)}"
    assert n_rule == len(types) * 2, f"has 规则数 {n_rule} != 应为 {len(types) * 2}"
    assert html.rstrip().endswith("</html>"), "HTML 未正常闭合"
    style_end = html.rfind("</style>")
    assert style_end > html.rfind('<div class="sec"'), \
        "rules 被写到了 section 之后（很可能落在 <script> 里导致失效）"
    assert html.count("<div") == html.count("</div>"), "div 不配平"

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n完成 -> {OUT_HTML}")


if __name__ == "__main__":
    main()
