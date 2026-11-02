#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — 把 data.json 的内容片段渲染进 assets/template.html，产出单文件学习 HTML。

为什么要有它：模板里约 60 个 {{占位符}}，纯靠模型手工替换必然漏填，
而漏填的表现是页面某块**静默空白**，不报错、很难发现。本脚本做四件事：

  1. 校验：模板占位符集合 vs data 键集合，缺的、多的一律报错（typo 直接拦住）
  2. 单遍替换：内容里若含 {{...}} 不会被二次解释，而是事后作为残留报出来
  3. 结构自检：12 个视图 / 12 个侧栏项 / id 与 data-view 一一对应 / 深色主题壳完好
  4. 配色自检：可视化片段里不许写死 #hex（深色主题下会隐形）
  5. 幂等：输出已存在就跳过，--force 才覆盖

用法：
    python scripts/render.py --data data.json                    # 渲染到 ./<主题>-十步学习.html
    python scripts/render.py --data data.json --fonts             # 顺带内联 Fraunces/Inter
    python scripts/render.py --data data.json --check             # 只校验，不写文件
    python scripts/render.py --data data.json -o out.html --force # 指定输出并覆盖

data.json 形如 {"TOPIC": "...", "STEP_1_OUTPUT": "<div class=\\"prose\\">...</div>", ...}
值是 HTML 片段，原样插入（不转义），所以片段必须自己闭合好标签。
STEP_N_VIZ 可省略，缺省按空串处理。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
TEMPLATE = SKILL_ROOT / "assets" / "template.html"
FONTS_CSS = SKILL_ROOT / "assets" / "fonts-inline.css"

PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
# 允许缺失、缺省当空串的占位符（可视化槽位，只有 1/2/6 步与收尾要填）
OPTIONAL_SUFFIX = ("_VIZ",)
# SVG 里写死颜色的写法（fill="#xxx" / stroke="#xxx"）——深色主题下必然出问题
HEX_COLOR_RE = re.compile(r'(?:fill|stroke|stop-color)\s*=\s*"#[0-9a-fA-F]{3,8}"')
# 显式豁免标记：确实需要固定颜色时，在片段里写这条注释
THEME_EXEMPT = "theme-fixed"
ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"! {msg}", file=sys.stderr)


def load_template() -> str:
    if not TEMPLATE.is_file():
        die(f"找不到模板：{TEMPLATE}")
    return TEMPLATE.read_text(encoding="utf-8")


def safe_name(topic: str) -> str:
    """把主题压成安全文件名：去非法字符、折叠空白、限长。"""
    s = ILLEGAL_FILENAME.sub("", topic or "").strip().strip(".")
    s = re.sub(r"\s+", "-", s)
    return (s[:80] or "未命名主题") + "-十步学习.html"


def validate(tpl: str, data: dict) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。errors 非空即中止。"""
    errors: list[str] = []
    warnings: list[str] = []

    expected = set(PLACEHOLDER_RE.findall(tpl))
    provided = set(data)

    # 1) data 里有、模板里没有 → 一定是键名写错，会静默丢内容
    unknown = sorted(provided - expected)
    if unknown:
        errors.append(
            "data 中存在模板没有的键（多半是拼写错误，内容会静默丢失）：\n    "
            + "\n    ".join(unknown)
        )

    # 2) 模板要、data 没给 → 页面空白。_VIZ 可省，其余必填
    missing_all = sorted(expected - provided)
    missing_required = [k for k in missing_all if not k.endswith(OPTIONAL_SUFFIX)]
    missing_optional = [k for k in missing_all if k.endswith(OPTIONAL_SUFFIX)]
    if missing_required:
        errors.append("缺少必填占位符（渲染后该处会空白）：\n    " + "\n    ".join(missing_required))
    if missing_optional:
        warnings.append(f"{len(missing_optional)} 个可视化槽位未填，按空处理：{', '.join(missing_optional)}")

    # 3) 值必须是字符串
    for key, val in data.items():
        if not isinstance(val, str):
            errors.append(f"{key} 的值是 {type(val).__name__}，必须是字符串（HTML 片段）")

    # 4) 值里出现 {{...}} → 几乎都是把提示词原文（含 {{主题}}）直接粘进来了，
    #    渲染后会残留在页面上，且会污染「无残留」自检
    for key, val in data.items():
        if isinstance(val, str) and PLACEHOLDER_RE.search(val):
            bad = PLACEHOLDER_RE.findall(val)
            warnings.append(
                f"{key} 的值里含有字面量占位符 {{{{ {', '.join(bad)} }}}}，"
                "渲染后会原样显示在页面上（提示词面板里应换成真实主题/角色）"
            )

    return errors, warnings


def lint_viz_colors(data: dict) -> list[str]:
    """可视化片段里出现写死的 #hex → 深色主题下会隐形（深绿节点压在近黑画布上）。"""
    errors: list[str] = []
    hint = (
        "    SVG 颜色一律用语义类，不要写死 hex：\n"
        '      节点 shape → class="viz-node"；强调 shape → class="viz-accent"\n'
        '      普通文字 → class="viz-ink"；节点内文字 → class="viz-node-ink"；强调块内文字 → class="viz-accent-ink"\n'
        '      连线 → class="viz-edge"，冲突线加 viz-edge--conflict，共识线加 viz-edge--consensus\n'
        "    确实必须固定颜色（很少见）：在该片段里写 <!-- theme-fixed --> 显式豁免。"
    )
    for key, val in data.items():
        if not isinstance(val, str):
            continue
        if not (key.endswith(OPTIONAL_SUFFIX) or key == "LOOP_DIAGRAM"):
            continue
        if THEME_EXEMPT in val:
            continue
        hits = sorted(set(HEX_COLOR_RE.findall(val)))
        if hits:
            errors.append(f"{key} 里写死了颜色：{', '.join(hits)}（深色主题下会看不见）\n{hint}")
    return errors


def check_structure(html: str) -> list[str]:
    """渲染后的结构自检，防住模板被误改。"""
    errors: list[str] = []
    views = re.findall(r'<section class="view[^"]*" id="([^"]+)"', html)
    nav_targets = set(re.findall(r'data-view="([^"]+)"', html))
    # 侧栏 12 项 + 总览地图 10 项 + 收尾 2 个 cta，data-view 会重复出现
    if len(views) != 12:
        errors.append(f"视图数量应为 12（总览+十步+收尾），实际 {len(views)}")
    for v in views:
        if v not in nav_targets:
            errors.append(f"视图 {v} 在侧栏没有对应导航项")
    for n in sorted(nav_targets - set(views)):
        errors.append(f"侧栏导航指向不存在的视图 {n}")
    # 主题壳：默认深色 + 切换按钮，任一缺失说明模板被改回浅色专用
    if 'data-theme="dark"' not in html:
        errors.append('模板根元素缺少 data-theme="dark"（默认深色失效）')
    if 'id="themeBtn"' not in html:
        errors.append('主题切换按钮 #themeBtn 缺失')
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="把 data.json 渲染进十步学习 HTML 模板")
    ap.add_argument("--data", required=True, help="内容数据 JSON 路径")
    ap.add_argument("-o", "--out", help="输出文件路径（默认 <主题>-十步学习.html，落在当前目录）")
    ap.add_argument("--fonts", action="store_true", help="内联 assets/fonts-inline.css（保住 Fraunces/Inter 拉丁字形）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--force", action="store_true", help="输出已存在时覆盖（默认跳过）")
    args = ap.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        die(f"找不到数据文件：{data_path}")
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"data.json 不是合法 JSON：第 {e.lineno} 行第 {e.colno} 列 — {e.msg}")
    if not isinstance(data, dict):
        die("data.json 顶层必须是对象（键 = 占位符名）")

    tpl = load_template()
    errors, warnings = validate(tpl, data)
    errors += lint_viz_colors(data)
    for w in warnings:
        warn(w)
    if errors:
        for e in errors:
            print(f"✗ {e}", file=sys.stderr)
        print(f"\n共 {len(errors)} 处错误，未写入任何文件。", file=sys.stderr)
        sys.exit(1)

    expected = set(PLACEHOLDER_RE.findall(tpl))
    print(f"· 模板占位符 {len(expected)} 个，data 提供 {len(data)} 个，校验通过")

    if args.check:
        print("✓ --check 模式：仅校验，未写文件")
        return

    # 单遍替换：值里的 {{...}} 不会被二次解释
    out_html = PLACEHOLDER_RE.sub(lambda m: data.get(m.group(1), ""), tpl)

    if args.fonts:
        if not FONTS_CSS.is_file():
            die(f"--fonts 需要 {FONTS_CSS.name}，先跑：node scripts/fetch-fonts.mjs")
        font_css = FONTS_CSS.read_text(encoding="utf-8")
        idx = out_html.rfind("</style>")
        if idx < 0:
            die("模板里找不到 </style>，无法注入字体")
        out_html = out_html[:idx] + "\n/* --- 内联字体（Fraunces + Inter latin 子集，base64）--- */\n" + font_css + out_html[idx:]
        print(f"· 已内联字体 CSS（{len(font_css) / 1024:.1f} KB）")

    # 残留检查：理论上不应出现，出现即说明有值漏填或含字面量
    leftovers = PLACEHOLDER_RE.findall(out_html)
    if leftovers:
        die("渲染后仍有占位符残留：" + ", ".join(sorted(set(leftovers))))

    struct_errors = check_structure(out_html)
    if struct_errors:
        for e in struct_errors:
            print(f"✗ {e}", file=sys.stderr)
        die("结构自检未通过，未写文件")

    topic = data.get("TOPIC", "")
    out_path = Path(args.out) if args.out else Path.cwd() / safe_name(topic)
    if out_path.exists() and not args.force:
        print(f"[skip] {out_path} 已存在（--force 可覆盖）")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline='\n' 统一行尾，避免按字节校验时跨平台不一致
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out_html)

    size_kb = len(out_html.encode("utf-8")) / 1024
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', out_html)
    print(f"✓ 写出 {out_path}")
    print(f"  {size_kb:.1f} KB · 12 视图 · 外链 {len(external)} 个" + ("（非离线！）" if external else "（完全离线）"))


if __name__ == "__main__":
    main()
