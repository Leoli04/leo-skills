"""台账骨架体检：改完 / 重建完台账，确认「固定内容」没有被吃掉。

**为什么需要这个脚本**（2026-11-07 事故，同一类已发生两次）：
`render_watchlist.py` 只渲染「观察池」这一层 —— masthead、KPI、总览、四分区、
复核时间轴、口径说明。台账上另外四样东西**都不在它的产出里**，全靠事后补：

  1. 智能页面运行时      `<script src="/page/page_comm/inject.js">`（平台注入）
  2. 数据表绑定          `#posSrc` + `data-sp-bindable` + `data-sp-database-id`
  3. ＋加行增强层        CSS `.padd-mini` + JS（posMask / addRecord / fetchAll）
  4. 持仓与计划 Tab      `#view-pos` + `data-v="pos"`

于是每次「本地重建 → 覆盖上传」都会静默丢一批：2026-11-05 那次丢的正是 2/3/4，
页面看着完全正常，只有点「＋」没反应、点位表不联动 —— 用户先发现，比脚本晚一步。
11-07 补施洛斯 tab 时又继承了同一个漏洞（没新增，但也没修）。

**和 `check_ledger_gap.py` 的分工**（两个脚本都要跑，管的是不同层）：

  check_ledger_gap.py      行级内容  —— 该有的标的有没行、行里的胜率是不是旧值
  check_ledger_skeleton.py 页面骨架  —— 行之外的一切：智能页面 / 数据表 / 增强层 / Tab

**判据为什么分三组**：
`render` 阶段的产物本来就不含 smart 组（渲染器不产出），拿它判 FAIL 会天天误报，
最后没人看。所以按阶段分级：`--stage render` 时 smart 组只 WARN，`--stage upload`
（准备传库端）时必须全绿。这样「重建后随手一跑」不会吵，「传之前一跑」拦得住。

**判据为什么用「CSS 里有没有 / JS 里有没有」而不是出现次数**：
`padd-mini` 在合格件里只出现 6 次（CSS 5 + JS 1），因为它是一个类名和一个
`b.className='padd-mini'` 赋值，不是每行一个按钮。数个数会得出「6 ≠ 104 所以坏了」
这种假结论。真正会半残的形态是**样式在、注入逻辑没了**（按钮永远不生成），
所以拆成 padd_css / padd_js 两条分开判。

用法：
    python assets/watchlist/check_ledger_skeleton.py --html 投资观察池台账-20261107.html
    python assets/watchlist/check_ledger_skeleton.py --html xxx.html --stage upload
    python assets/watchlist/check_ledger_skeleton.py --html 新版.html --diff 上一版.html
    python assets/watchlist/check_ledger_skeleton.py --html xxx.html --quiet   # 只出结论行

退出码：0 = OK（无 FAIL），1 = BROKEN（有 FAIL），2 = 文件读不到
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

# ---------------------------------------------------------------- 解析

RE_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
RE_SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.S)
RE_HEADING = re.compile(r"<h([1-4])[^>]*>(.*?)</h\1>", re.S)
RE_TAG = re.compile(r"<[^>]+>")
# 平台注入物：逐字节比对时制造假差异，判据里一律剥掉
RE_PNID_NOTE = re.compile(r"<!--pnid:[^>]*-->")
PNID_ATTRS = ("data-page-node-id", "data-pnid-children")


def split_doc(s: str) -> tuple[list[str], list[str], str]:
    """拆成 (style 块列表, script 块列表含其属性, 可见 body)。

    body 保留注释与标签文本 —— 判据里有需要看 `id="pxbar"` 这种属性的项。
    `<script src=...>` 的外链脚本也算进 script 块（inject.js 就是这种），
    所以 script 块取「属性 + 内容」两段拼接。
    """
    styles = RE_STYLE.findall(s)
    scripts = [a + b for a, b in RE_SCRIPT.findall(s)]
    body = RE_SCRIPT.sub(" ", s)
    body = RE_STYLE.sub(" ", body)
    return styles, scripts, body


def headings(body: str) -> list[tuple[int, str]]:
    """可见标题序列。只取 script/style 之外的 —— JS 模板串里也有 `<h3>`。"""
    out = []
    for lv, inner in RE_HEADING.findall(body):
        txt = " ".join(RE_TAG.sub(" ", inner).split())
        if txt:
            out.append((int(lv), txt))
    return out


def has_heading(hs: list[tuple[int, str]], level: int, needle: str) -> bool:
    return any(lv == level and needle in txt for lv, txt in hs)


def count_rows(body: str) -> tuple[int, int, int]:
    """(观察池只数, A 区卡片数, 分区容器数)，仅作 INFO 展示，不参与判定。"""
    rows = len(re.findall(r'data-k="', body))
    cards = len(re.findall(r'class="[^"]*\bzcard\b', body))
    zones = len(re.findall(r'class="[^"]*\bzone zone--', body))
    return rows, cards, zones


# ---------------------------------------------------------------- 判据表
#
# group:  core    = 任何一份台账都该有（渲染器就产出这些）
#         smart   = 智能页面 / 数据表 / 增强层 / 持仓 Tab，render 阶段豁免
#         optional= 后加的模块（施洛斯 Tab 这类），缺了只提示
# where:  body / style / script / any   —— 到哪个块里找
# hint:   缺了怎么办（直接给动作，不给解释）

CHECKS = [
    # ---- core：渲染器产出，缺了说明渲染链路本身坏了 ----
    dict(k="h1_title", group="core", where="body", kind="heading", level=1,
         arg="投资观察池", label="页头标题 h1",
         hint="渲染器没跑到 masthead，检查 render_watchlist.py 是否中途异常退出"),
    dict(k="h2_overview", group="core", where="body", kind="heading", level=2,
         arg="全池总览", label="全池总览模块",
         hint="总览整块丢失（分布柱 / 赔率矩阵 / 三桶条都在这一节）"),
    dict(k="h2_zones", group="core", where="body", kind="heading", level=2,
         arg="分区台账", label="分区台账模块",
         hint="四分区整块丢失，检查 manifest 的 zone 字段是否为空"),
    dict(k="h2_timeline", group="core", where="body", kind="heading", level=2,
         arg="复核时间轴", label="复核时间轴模块",
         hint="时间轴丢失，检查各报告 asof 是否全为空"),
    dict(k="h2_scope", group="core", where="body", kind="heading", level=2,
         arg="口径与设计说明", label="口径与设计说明",
         hint="页脚口径块丢失 —— 读者会不知道现价时点与判定口径，属合规项"),
    dict(k="zone_box", group="core", where="body", kind="token",
         arg="zone zone--", label="分区容器 class",
         hint="分区容器没了，chips 过滤与折叠会整块失效"),
    dict(k="model", group="core", where="script", kind="token",
         arg="WL_MODEL", label="JS 数据模型 WL_MODEL",
         hint="页面退化成静态死页：刷新现价 / 排序 / 筛选全部失效"),
    dict(k="pxbar", group="core", where="body", kind="token",
         arg='id="pxbar"', label="现价刷新条 #pxbar",
         hint="现价刷新入口丢失；若同时丢了 #px-refresh 按钮则整条 bar 没了"),
    dict(k="px_quote", group="core", where="script", kind="token",
         arg="qt.gtimg.cn", label="行情通道 qt.gtimg.cn",
         hint="取价通道丢了，刷新会静默失败（代码在但请求不到）"),
    dict(k="theme", group="core", where="script", kind="token",
         arg="wl-theme", label="三档主题 localStorage 键",
         hint="主题切换器失效，深色档用户会看到闪白"),

    # ---- smart：库端才有的四样，render 阶段豁免 ----
    dict(k="inject", group="smart", where="any", kind="token",
         arg="/page_comm/inject.js", label="智能页面运行时 inject.js",
         hint="没有它平台不认这是智能页面：块编辑与数据表联动都不工作"),
    dict(k="bind", group="smart", where="body", kind="token",
         arg='data-sp-bindable', label="数据表绑定标记 data-sp-bindable",
         hint="平台靠它认数据集，缺了 #posSrc 就只是个普通 span"),
    dict(k="pos_src", group="smart", where="body", kind="token",
         arg='id="posSrc"', label="数据表源标记 #posSrc",
         hint="增强脚本读它拿 databaseId，缺了一启动就 return"),
    dict(k="dbid", group="smart", where="body", kind="regex",
         arg=r'data-sp-database-id="([0-9A-Za-z]{20,40})"', label="数据库 ID",
         hint="绑定到了空库；应指向台账数据表（本项目 LmhN0eFhk6hgXCjbOcSlaz）"),
    dict(k="padd_css", group="smart", where="style", kind="token",
         arg="padd-mini", label="＋按钮样式 .padd-mini（CSS）",
         hint="CSS 丢了：按钮会生成但没样式，撑破卡片布局"),
    dict(k="padd_js", group="smart", where="script", kind="token",
         arg="padd-mini", label="＋按钮注入逻辑（JS）",
         hint="这是「＋丢失」的真正病灶：样式在、逻辑没了，按钮永不生成"),
    dict(k="pos_mask", group="smart", where="script", kind="token",
         arg="posMask", label="持仓表单遮罩 posMask",
         hint="点＋没表单可填，等于加行功能不可用"),
    dict(k="add_rec", group="smart", where="script", kind="token",
         arg="addRecord", label="写库调用 addRecord",
         hint="表单能填但存不进去 —— 数据表里不会多行"),
    dict(k="fetch_all", group="smart", where="script", kind="token",
         arg="fetchAll", label="分页拉全量 fetchAll",
         hint="只读到第一页，超过 pageSize 的持仓行在页面上不见"),
    dict(k="view_pool", group="smart", where="body", kind="token",
         arg='id="view-pool"', label="观察池视图容器",
         hint="视图切换的容器没了，切 tab 会白屏"),
    dict(k="view_pos", group="smart", where="body", kind="token",
         arg='id="view-pos"', label="持仓与计划视图容器",
         hint="本地渲染器不产出这一 Tab。要保留持仓就**别整页覆盖上传**，走行级补丁"),
    dict(k="tab_pos", group="smart", where="body", kind="token",
         arg='data-v="pos"', label="持仓 Tab 按钮",
         hint="有容器没按钮 = 这页永远切不过去"),

    # ---- optional：后加模块，缺了不算坏 ----
    dict(k="view_schl", group="optional", where="body", kind="token",
         arg='id="view-schl"', label="施洛斯策略观察视图",
         hint="11-07 新增；缺失说明这次重建把它吃了，重跑 _schl_tab_patch.py"),
    dict(k="tab_schl", group="optional", where="body", kind="token",
         arg='data-v="schl"', label="施洛斯 Tab 按钮",
         hint="同上"),
]


# ---------------------------------------------------------------- 执行

def evaluate(html: str) -> list[dict]:
    styles, scripts, body = split_doc(html)
    hs = headings(body)
    pool = {
        "body": body,
        "style": "\n".join(styles),
        "script": "\n".join(scripts),
        "any": html,
    }
    results = []
    for c in CHECKS:
        hay = pool[c["where"]]
        n = 0
        if c["kind"] == "heading":
            ok = has_heading(hs, c["level"], c["arg"])
        elif c["kind"] == "regex":
            m = re.search(c["arg"], hay)
            ok = bool(m)
            n = 1 if m else 0
            if m:
                c = dict(c, found=m.group(1))
        else:
            n = hay.count(c["arg"])
            ok = n > 0
        results.append(dict(c, ok=ok, n=n))
    return results


def level_of(r: dict, stage: str) -> str:
    """PASS / FAIL / WARN。smart 组在 render 阶段降为 WARN。"""
    if r["ok"]:
        return "PASS"
    if r["group"] == "core" or r["group"] == "optional":
        return "FAIL" if r["group"] == "core" else "WARN"
    return "FAIL" if stage == "upload" else "WARN"


def report(html: str, path: str, stage: str, quiet: bool) -> int:
    res = evaluate(html)
    _, _, body = split_doc(html)
    rows, cards, zones = count_rows(body)
    styles, scripts, _ = split_doc(html)
    pnid = len(RE_PNID_NOTE.findall(html))
    dbid = next((r.get("found") for r in res if r["k"] == "dbid"), "")

    if not quiet:
        print("台账骨架体检：%s  (%.0f KB)" % (os.path.basename(path), len(html) / 1024))
        print("观察池 %d 只 / A 区卡片 %d 张 / 分区 %d 个 ｜ script %d 段 · style %d 段 · pnid %d"
              % (rows, cards, zones, len(scripts), len(styles), pnid))
        if dbid:
            print("数据表 database-id：%s" % dbid)
        print()

    fails = warns = 0
    # 拿报告页误跑时，core 会整组挂掉；先给一句人话，别让人去猜 10 条 FAIL
    if not any(r["k"] == "h1_title" and r["ok"] for r in res) and \
       not any(r["k"] == "h2_overview" and r["ok"] for r in res):
        print("⚠ 这份文件不像观察池台账（既无「投资观察池」h1，也无「全池总览」h2）。")
        print("  本脚本只体检台账；个股报告请用 verify_report.py。下面结果仅供参考。\n")

    groups = [("core", "① 骨架（渲染器产物，任何一份台账都该有）"),
              ("smart", "② 智能页面 / 数据表 / 增强层 / 持仓 Tab（库端才有）"),
              ("optional", "③ 后加模块（缺了只提示）")]
    for gk, title in groups:
        items = [r for r in res if r["group"] == gk]
        shown = [(r, level_of(r, stage)) for r in items]
        bad = [x for x in shown if x[1] != "PASS"]
        if not quiet:
            print("=== %s ===" % title)
        if not bad:
            if not quiet:
                print("  PASS  全部 %d 项在位" % len(items))
        for r, lv in shown:
            if lv == "PASS":
                continue
            fails += lv == "FAIL"
            warns += lv == "WARN"
            print("  %-4s %s" % (lv, r["label"]))
            print("         └ %s" % r["hint"])
        if not quiet:
            print()

    ok = fails == 0
    tail = ""
    if not ok:
        tail = "  → 先按上面的 └ 修复，再从库端拉回比对"
    elif warns and stage != "upload":
        # render 阶段有告警时**不能**说「可上传」：smart 组正是渲染器不产出、
        # 必须事后补的那几样，此时传上去就是丢「＋」的那一版。
        tail = "  → 上面 WARN 的项渲染器不产出，补齐后加 --stage upload 再确认可否上传"
    elif warns:
        tail = "  → 仅提示项缺失，可上传"
    print("LEDGER_SKELETON_RESULT: %s (fail %d / warn %d%s)"
          % ("OK" if ok else "BROKEN", fails, warns,
             "" if stage == "upload" else " / stage=render，smart 组缺失只告警"))
    if tail:
        print(tail)
    return 0 if ok else 1


def diff(base_html: str, new_html: str) -> int:
    """两份台账对差，只比「结构性标记的有无」，不比数字（行数/价格本来就该变）。"""
    b = {r["k"]: r for r in evaluate(base_html)}
    n = {r["k"]: r for r in evaluate(new_html)}
    gone = [k for k in b if b[k]["ok"] and not n[k]["ok"]]
    back = [k for k in n if n[k]["ok"] and not b[k]["ok"]]
    print("\n=== 相对基准消失了的结构标记 %d 项 ===" % len(gone))
    for k in gone:
        print("  - %-12s %s" % (k, b[k]["label"]))
        print("      └ %s" % b[k]["hint"])
    print("\n=== 相对基准新增的结构标记 %d 项 ===" % len(back))
    for k in back:
        print("  + %-12s %s" % (k, n[k]["label"]))
    return 0 if not gone else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="要体检的台账 HTML")
    ap.add_argument("--stage", choices=("render", "upload"), default="render",
                    help="render=刚渲染完（smart 组只告警）；upload=准备上传（必须全绿）")
    ap.add_argument("--diff", default="", help="基准 HTML，额外输出「相对基准丢了什么」")
    ap.add_argument("--quiet", action="store_true", help="只输出问题项与结论行")
    a = ap.parse_args()

    if not os.path.exists(a.html):
        print("ERR 文件不存在：%s" % a.html)
        return 2
    html = io.open(a.html, encoding="utf-8", errors="replace").read()
    rc = report(html, a.html, a.stage, a.quiet)
    if a.diff:
        if not os.path.exists(a.diff):
            print("ERR 基准文件不存在：%s" % a.diff)
            return 2
        rc = max(rc, diff(io.open(a.diff, encoding="utf-8", errors="replace").read(), html))
    return rc


if __name__ == "__main__":
    sys.exit(main())
