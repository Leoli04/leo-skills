# -*- coding: utf-8 -*-
"""给台账加一个「沃尔特施洛斯策略观察」视图 Tab，内容是施洛斯改良标准筛出的 A 级。

**为什么是独立步骤、不塞进 render_watchlist.py**：
Tab 的内容（A 级名单、漏斗各层数量、口径日期）来自一次外部筛选的结果 CSV，
不是渲染器从 manifest 推得出来的。渲染器负责「确定的骨架」，本脚本负责
「外挂一块数据视图」，职责分开。标准流程是：

    render_watchlist.py  →  patch_schl_tab.py（可选）  →  check_ledger_skeleton.py

**设计约束**（来自 WATCHLIST.md §13/§14，别改）：
- 页面 JS 会扫 `table.wl tbody` / `[data-row]` / `.zone` / `.zcard` 做重排与统计，
  所以新视图一律用 `schl-` 前缀类名，绝不复用 wl / zone / zcard / data-row，
  否则 A 级那几只被算进观察池的 KPI、chips、分区计数。
  脚本末尾有断言在守这条。
- 颜色全部走 CSS 变量（--surface/--line/--ink-*/--brand），三套主题自动适配。
- 正文不出现裸 `<`（避免二次转义），阈值一律用 ≤ / ≥ 表述。

用法：
    python assets/watchlist/patch_schl_tab.py \
        --html "投资观察池台账-20261107.html" \
        --csv _schl_result.csv \
        --funnel "5927:全 A,167:估值初筛,69:财务六关,38:九关全过" \
        --metrics-date 2026-11-07

    # 只看会改成什么，不落盘
    python assets/watchlist/patch_schl_tab.py --html x.html --csv y.csv --dry-run

    # 备注（每只一句问题）默认按代码内置；换一批标的时用 --notes 传 JSON
    python assets/watchlist/patch_schl_tab.py --html x.html --csv y.csv --notes notes.json

幂等：已经含 `id="view-schl"` 的文件会直接跳过（退出码 0）。
退出码：0 = 已应用或已存在；2 = 文件读不到；3 = 锚点命中数不符
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys

TAB_LABEL = "沃尔特施洛斯策略观察"

# 每只标的的一句风险提示。默认按 2026-11-07 那批 A 级写的；
# 换一批标的时用 --notes 传 {"代码": "说明"} 覆盖。
DEFAULT_NOTES = {
    "600894": "利润主要来自参股日立电梯的投资收益，本质是持股平台型公司",
    "603018": "ROE 由 14.9 降至 5.3，股价贴 52 周低点，仍在下跌通道",
    "600780": "小市值电力股，电价政策敏感",
    "002091": "近 12 个月派息不止一次，5.93% 不能当成常态股息率",
    "002120": "贴 52 周低点，快递价格战尚未出清",
    "601518": "负债率 12%、有息负债 0.2%，最接近原版画像",
    "600987": "ROE 三年几乎不动（11.2/11.4/11.5），行业无人问津",
    "000828": "负债 31.7%、股息 4.73%，现金流稳定",
}

CSS = """<style>
/* ── 视图 Tab：沃尔特施洛斯策略观察（类名 schl- 前缀，避开页面 JS 的 wl/zone 扫描） ── */
.schl-hero{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  padding:var(--s5) var(--s5) var(--s4);margin-bottom:var(--s5)}
.schl-hero__t{margin:0 0 var(--s2);font-size:var(--fs-xl);color:var(--ink-900);
  font-weight:700;letter-spacing:-.01em}
.schl-hero__d{margin:0;font-size:var(--fs-sm);color:var(--ink-500);line-height:1.75}
.schl-funnel{display:flex;flex-wrap:wrap;align-items:center;gap:var(--s2);
  margin:var(--s4) 0 0;padding:0;list-style:none}
.schl-funnel li{display:flex;align-items:baseline;gap:5px;font-size:var(--fs-xs);
  color:var(--ink-500);background:var(--surface-2);border:1px solid var(--line);
  border-radius:999px;padding:5px 12px}
.schl-funnel li b{font-size:var(--fs-sm);color:var(--ink-900);font-weight:700;
  font-variant-numeric:tabular-nums}
.schl-funnel li.is-end{background:var(--brand-soft);border-color:var(--brand);
  color:var(--brand)}
.schl-funnel li.is-end b{color:var(--brand)}
.schl-arw{color:var(--ink-300);font-size:var(--fs-xs);margin:0 1px}

.schl-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  overflow:hidden;margin-bottom:var(--s4)}
.schl-panel__h{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;
  padding:var(--s4) var(--s5);border-bottom:1px solid var(--line)}
.schl-panel__bar{width:4px;height:16px;border-radius:2px;background:var(--brand)}
.schl-panel__t{font-size:var(--fs-md);font-weight:700;color:var(--ink-900)}
.schl-panel__d{font-size:var(--fs-xs);color:var(--ink-400)}
.schl-panel__n{margin-left:auto;font-size:var(--fs-xs);font-weight:700;color:var(--brand);
  background:var(--brand-soft);border-radius:999px;padding:3px 10px;
  font-variant-numeric:tabular-nums}
.schl-tw{overflow-x:auto}
table.schl-t{width:100%;border-collapse:collapse;font-size:var(--fs-xs)}
table.schl-t th{text-align:left;font-weight:600;color:var(--ink-500);white-space:nowrap;
  padding:10px var(--s4);border-bottom:1px solid var(--line);background:var(--surface-2)}
table.schl-t td{padding:11px var(--s4);border-bottom:1px solid var(--line-2);
  color:var(--ink-700);vertical-align:middle}
table.schl-t tbody tr:last-child td{border-bottom:none}
table.schl-t tbody tr:hover td{background:var(--surface-2)}
.schl-t__i{color:var(--ink-300);width:34px;font-variant-numeric:tabular-nums}
.schl-t__nm{white-space:nowrap}
.schl-t__nm b{color:var(--ink-900);font-weight:650}
.schl-t__nm span{display:block;color:var(--ink-400);font-size:10.5px;
  font-family:var(--mono);letter-spacing:.02em}
.schl-t__r{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
table.schl-t th.schl-t__r{text-align:right}
.schl-t__nt{color:var(--ink-500);font-size:var(--fs-xs);line-height:1.6;min-width:220px}

.schl-note{background:var(--surface-2);border:1px solid var(--line);border-radius:var(--r2);
  padding:var(--s4) var(--s5);font-size:var(--fs-xs);color:var(--ink-500);line-height:1.85}
.schl-note b{color:var(--ink-700);font-weight:650}
.schl-note ul{margin:var(--s2) 0 0;padding-left:18px}
.schl-note li{margin:2px 0}
@media (max-width:760px){.schl-t__nt{min-width:150px}}
</style>"""

VIEW_TPL = """<div hidden id="view-schl">
<section class="schl-hero">
  <h2 class="schl-hero__t">__TAB_LABEL__</h2>
  <p class="schl-hero__d">按改良版施洛斯标准（九关）筛全 A，只留 __NA__ 只。原版七条是折价于账面价值、低 PE、存续十年、无长期负债、贴近 52 周低点、内部人持股高、股息尚可；改良版把「内部人持股」换成财报排雷，把「翻倍就走」换成按折价修复分批卖，并对周期股加行业 PB 分位过滤。</p>
  <ol class="schl-funnel">__FUNNEL__</ol>
</section>

<section class="schl-panel">
  <div class="schl-panel__h">
    <span class="schl-panel__bar"></span>
    <span class="schl-panel__t">A 级 · __NA_CN__</span>
    <span class="schl-panel__d">九关全过，且 PB≤1.0、三年均 ROE≥8%、股息≥3%、非周期</span>
    <span class="schl-panel__n">__NA__ 只</span>
  </div>
  <div class="schl-tw">
    <table class="schl-t">
      <thead>
        <tr>
          <th>#</th><th>标的</th><th>行业</th><th class="schl-t__r">PB</th>
          <th class="schl-t__r">PE(TTM)</th><th class="schl-t__r">ROE 近三年</th>
          <th class="schl-t__r">距 52 周低点</th><th class="schl-t__r">股息率</th>
          <th class="schl-t__r">负债率</th><th>备注</th>
        </tr>
      </thead>
      <tbody>
__TBODY__
      </tbody>
    </table>
  </div>
</section>

<div class="schl-note">
  <b>口径</b>
  <ul>
    <li>估值、市值、距低点取 __DATE__ 实时快照；ROE 取最近年报，负债率取最近季报。</li>
    <li>股息率＝最近 12 个月已实施分红合计 ÷ 现价，滚动口径，会高于按年度方案算的股息率。</li>
    <li>未核三项：大股东持股比例、股权质押、审计意见。这三项要逐份翻公告，买前必须人工补。</li>
    <li><b>这是观察池，不是买入清单。</b>按施洛斯的做法：单只先建计划仓位的 50%，跌了再加；单只不超过 5%，总数 25–30 只。</li>
  </ul>
</div>
</div>

"""

CN_NUM = {2: "两只", 3: "三只", 4: "四只", 5: "五只", 6: "六只", 7: "七只",
          8: "八只", 9: "九只", 10: "十只", 11: "十一只", 12: "十二只"}


def fnum(v, nd=2):
    return ("%." + str(nd) + "f") % float(v)


def read_a_rows(path):
    with io.open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise SystemExit("CSV 为空：%s" % path)
    head, body = rows[0], rows[1:]
    need = ("层级", "代码", "名称", "行业", "PB", "PE_TTM", "ROE近三年",
            "距52周低点%", "近12月股息率%", "资产负债率%")
    lack = [c for c in need if c not in head]
    if lack:
        raise SystemExit("CSV 缺列：%s" % ", ".join(lack))
    data = [dict(zip(head, r)) for r in body if len(r) == len(head)]
    return sorted([x for x in data if x["层级"] == "A"], key=lambda x: float(x["PB"]))


def build_view(a_rows, funnel, date, notes):
    trs = []
    for i, x in enumerate(a_rows, 1):
        code = x["代码"]
        trs.append(
            '      <tr>'
            '<td class="schl-t__i">%d</td>'
            '<td class="schl-t__nm"><b>%s</b><span>%s</span></td>'
            '<td>%s</td>'
            '<td class="schl-t__r">%s</td>'
            '<td class="schl-t__r">%s</td>'
            '<td class="schl-t__r">%s</td>'
            '<td class="schl-t__r">%s%%</td>'
            '<td class="schl-t__r">%s%%</td>'
            '<td class="schl-t__r">%s%%</td>'
            '<td class="schl-t__nt">%s</td>'
            '</tr>' % (
                i, x["名称"], code, x["行业"],
                fnum(x["PB"]), fnum(x["PE_TTM"], 1), x["ROE近三年"],
                fnum(x["距52周低点%"], 1), fnum(x["近12月股息率%"]),
                fnum(x["资产负债率%"], 0),
                notes.get(code, ""),
            ))
    n = len(a_rows)
    pills = []
    for i, (num, label) in enumerate(funnel):
        pills.append('<li><b>%s</b> %s</li>' % (num, label))
        pills.append('<li class="schl-arw">→</li>')
    pills.append('<li class="is-end"><b>%d</b> A 级</li>' % n)
    return (VIEW_TPL
            .replace("__TAB_LABEL__", TAB_LABEL)
            .replace("__NA_CN__", CN_NUM.get(n, "%d 只" % n))
            .replace("__NA__", str(n))
            .replace("__FUNNEL__", "".join(pills))
            .replace("__TBODY__", "\n".join(trs))
            .replace("__DATE__", date))


def anchor_by_regex(html, pattern, what, flags=re.S):
    """按正则找唯一锚点，返回 (start, end, text)。"""
    ms = list(re.finditer(pattern, html, flags))
    if len(ms) != 1:
        raise SystemExit("ANCHOR_FAIL %s：命中 %d 次（应为 1）—— 页面结构变了，先核对再改。"
                         % (what, len(ms)))
    m = ms[0]
    return m.start(), m.end(), m.group(0)


def apply(html, view):
    """四处插入 + 一处加 id。每处都断言唯一，失败即中止（不产出半成品）。"""
    # 1. 样式
    if html.count("</head>") != 1:
        raise SystemExit("ANCHOR_FAIL </head>：命中 %d 次" % html.count("</head>"))
    html = html.replace("</head>", CSS + "\n</head>", 1)

    # 2. Tab 按钮：插在 data-v="pool" 那个按钮之后
    s, e, pool_btn = anchor_by_regex(
        html, r'<button[^>]*data-v="pool"[^>]*>.*?</button>', "观察池 Tab 按钮")
    new_btn = ('\n  <button class="vtab" data-v="schl" type="button" '
               'aria-pressed="false">%s</button>' % TAB_LABEL)
    html = html[:e] + new_btn + html[e:]

    # 3. 视图容器：插在 #view-pos 之前（DOM 顺序不影响，靠 hidden 控制）
    s, e, vp = anchor_by_regex(html, r'<div[^>]*\bid="view-pos"[^>]*>', "持仓视图容器")
    html = html[:s] + view + html[s:]

    # 4. 切换函数：补一行施洛斯视图
    SHOW = "document.getElementById('view-pos').hidden = (v !== 'pos');"
    if html.count(SHOW) != 1:
        raise SystemExit("ANCHOR_FAIL 视图切换函数：命中 %d 次（页面 JS 写法变了）"
                         % html.count(SHOW))
    html = html.replace(
        SHOW,
        SHOW +
        "\n    var sx = document.getElementById('view-schl');"
        " if (sx) sx.hidden = (v !== 'schl');"
        "\n    var ft = document.getElementById('ledger-foot');"
        " if (ft) ft.hidden = (v === 'schl');", 1)

    # 5. 页脚「口径与设计说明」加 id：施洛斯视图下要隐藏它
    #    它讲的是观察池的价格带 / 判定 / 期望价口径，挂在这张表下面会自相矛盾。
    i = html.find("口径与设计说明")
    if i < 0:
        raise SystemExit("ANCHOR_FAIL 页脚「口径与设计说明」：页面里找不到")
    sec_start = html.rfind("<section", 0, i)
    if sec_start < 0:
        raise SystemExit("ANCHOR_FAIL 页脚 section 开始标签")
    head_end = html.find(">", sec_start)
    if head_end < 0 or head_end > i:
        raise SystemExit("ANCHOR_FAIL 页脚 section 开始标签范围异常")
    tag = html[sec_start:head_end + 1]
    if 'id="' in tag:
        raise SystemExit("页脚 section 已有 id，不覆盖：%s" % tag[:120])
    html = html[:sec_start] + tag[:-1] + ' id="ledger-foot">' + html[head_end + 1:]

    return html


def verify(html, view):
    """自检：三样各一份；新视图里绝不能带旧钩子。"""
    for k, want in (('id="view-schl"', 1), ('data-v="schl"', 1),
                    ('class="schl-t"', 1), ('id="ledger-foot"', 1)):
        got = html.count(k)
        if got != want:
            raise SystemExit("VERIFY_FAIL %s：%d（应为 %d）" % (k, got, want))
    seg = html[html.find('id="view-schl"'):html.find('id="view-pos"')]
    for bad in ('data-row', 'data-b=', 'data-up=', 'data-win=', 'class="zone',
                'zcard', 'table class="wl"', 'class="wl"'):
        if bad in seg:
            raise SystemExit("VERIFY_FAIL 新视图污染了观察池钩子：%s" % bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="要加 Tab 的台账 HTML")
    ap.add_argument("--csv", required=True, help="施洛斯筛选结果 CSV（需含 层级 列）")
    ap.add_argument("--out", default="", help="输出路径，默认原地覆盖 --html")
    ap.add_argument("--funnel", default="",
                    help='漏斗前几层，形如 "5927:全 A,167:估值初筛"；A 级数量自动取')
    ap.add_argument("--metrics-date", default="", help="口径日期，如 2026-11-07")
    ap.add_argument("--notes", default="", help="JSON 文件：{代码: 一句风险提示}")
    ap.add_argument("--dry-run", action="store_true", help="只报告会改什么，不落盘")
    a = ap.parse_args()

    if not os.path.exists(a.html):
        print("ERR 文件不存在：%s" % a.html)
        return 2
    html = io.open(a.html, encoding="utf-8").read()

    if 'id="view-schl"' in html:
        print("SKIP 已含施洛斯视图（%d 处），不重复插入" % html.count('id="view-schl"'))
        return 0

    a_rows = read_a_rows(a.csv)
    if not a_rows:
        raise SystemExit("CSV 里没有 层级=A 的行，无可展示内容")

    notes = dict(DEFAULT_NOTES)
    if a.notes:
        notes.update(json.load(io.open(a.notes, encoding="utf-8")))

    funnel = []
    if a.funnel:
        for part in a.funnel.split(","):
            part = part.strip()
            if not part:
                continue
            num, _, label = part.partition(":")
            funnel.append((num.strip(), label.strip() or num.strip()))
    else:
        print("! 未传 --funnel，漏斗只显示 A 级一层；重跑筛选后建议补上各层数量")

    view = build_view(a_rows, funnel, a.metrics_date or "—", notes)
    out_html = apply(html, view)
    verify(out_html, view)

    print("A 级 %d 只：%s" % (len(a_rows), "、".join(x["名称"] for x in a_rows)))
    print("bytes %d -> %d (+%d)" % (len(html), len(out_html), len(out_html) - len(html)))
    n_btn = len(re.findall(r'<button[^>]*\bdata-v="', out_html))
    print("tab 按钮 %d 个 ｜ 视图容器 %d 个 ｜ 页脚 id %d 处"
          % (n_btn, out_html.count('id="view-'),
             out_html.count('id="ledger-foot"')))

    if a.dry_run:
        print("--dry-run：未落盘")
        return 0
    dst = a.out or a.html
    io.open(dst, "w", encoding="utf-8", newline="\n").write(out_html)
    print("written %s" % dst)
    print("下一步：check_ledger_skeleton.py --html %s" % os.path.basename(dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
