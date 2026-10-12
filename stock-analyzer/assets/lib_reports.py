#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stock-analyzer · 资料库「个股报告」历史版本检索 / 全量盘查 / 旧版归档

三个子命令（对应 SKILL.md 的 Phase 0a 与 Phase 11）：

  scan     列出资料库「个股报告」文件夹的全部子节点，按 --code / --name 过滤出
           同一标的的历史版本，按日期倒序打印，并给出结论行与待归档清单。
             - NO_HISTORY    零命中  → 本次为首次覆盖，按全流水线正常做
             - HISTORY_FOUND 命中 1 版 → 必须向用户确认评估模式（全面重估 / 基于旧版更新）
             - MULTI_VERSION 命中 ≥2 版 → 除确认模式外，收尾必须归档旧版至只剩 1 版
           只读，不修改任何节点。幂等，可反复跑。

  audit    全量盘查（不分标的）：把「个股报告」内全部节点按标的归组，一次列出所有
           「同标的多版本并存」的组、以及完全同名的疑似重复上传，并给出待归档 node-id
           清单与现成可跑的命令。结论行 CLEAN / NEEDS_ACTION。只读。

  archive  把指定 node-id 移到「旧版归档」文件夹（space.workspace.move-node）。
           `parentId` 已在归档夹内的节点自动跳过，因此可重复执行（幂等）。
           支持 --dry-run。

用法：
  python lib_reports.py scan  --code 689009 --name 九号公司
  python lib_reports.py scan  --space-id <sid> --folder-id <fid> --code 09992 --name 泡泡玛特 --json
  python lib_reports.py audit                                  # 全量盘查，列多版本组
  python lib_reports.py audit  --json
  python lib_reports.py archive --archive-id <aid> --node-id <旧版 node-id> [--node-id ...] [--dry-run]

默认 space_id / folder_id / archive_id 为本项目实测值（见 watchlist_manifest.json 的 space 段），
可用参数覆盖；也可用 --manifest <path> 直接读取 manifest 的 space 段。
资料库接口目录默认取 WorkBuddy 内置 library skill，可用 --lib-dir 或
环境变量 WORKBUDDY_LIBRARY_DIR 覆盖。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------- 常量

DEFAULT_LIB_DIR = (
    r"C:\Users\86130\AppData\Local\Programs\WorkBuddy\resources\app.asar.unpacked"
    r"\resources\plugins\workbuddy-builtin\skills\library"
)
DEFAULT_SPACE_ID = "lWmChDNEl28HPp3VjuY5W7"
DEFAULT_FOLDER_ID = "ls82HtPIkKcX6Cv3AUGeVP"   # 个股报告
DEFAULT_ARCHIVE_ID = "1PBO6txAv1MOq2nljCBvQM"  # 旧版归档

# 标题里出现的报告类型关键词，按优先级取第一个命中
TYPE_KEYS = [
    "投资分析报告", "首次覆盖报告", "基本面分析报告",
    "投资分析", "首次覆盖", "基本面分析", "测算",
]

DATE_FULL = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
DATE_COMPACT = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
# 括号内代码：A 股 6 位；港股 5 位（须带 .HK 后缀，否则不认，避免与 A 股混淆）
CODE_PAREN = re.compile(r"[（(]\s*(\d{5,6})(\.HK)?\s*[)）]", re.I)
CODE_HK = re.compile(r"(?<!\d)(\d{5})\s*\.?\s*HK\b", re.I)
CODE_BARE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
NAME_SPLIT = re.compile(r"[（(|\-_/·]")
NAME_JUNK = re.compile(r"\s+")


# ---------------------------------------------------------------- 工具

def out(msg: str = "") -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(msg)


def load_lib_dir(cli_value: str | None) -> str:
    for cand in (cli_value, os.environ.get("WORKBUDDY_LIBRARY_DIR"), DEFAULT_LIB_DIR):
        if cand and os.path.isfile(os.path.join(cand, "space_api.py")):
            return cand
    raise SystemExit(
        "[ERROR] 找不到资料库接口目录（space_api.py）。\n"
        "        用 --lib-dir <library skill 目录> 或设置环境变量 WORKBUDDY_LIBRARY_DIR。\n"
        "        默认路径：%s" % DEFAULT_LIB_DIR
    )


def call_api(lib_dir: str, api: str, flags: dict) -> dict:
    """调用 space_api.py，返回 data 字段。"""
    cmd = [sys.executable, os.path.join(lib_dir, "space_api.py"), api]
    for key, value in flags.items():
        if value is None or value is False:
            continue
        cmd += ["--" + key.replace("_", "-"), str(value)]
    cp = subprocess.run(cmd, capture_output=True)
    raw = cp.stdout.decode("utf-8", "replace")
    idx = raw.find("{")
    if idx < 0:
        err = cp.stderr.decode("utf-8", "replace") or raw
        raise SystemExit("[ERROR] %s 调用失败：%s" % (api, err.strip()[:400]))
    try:
        env = json.loads(raw[idx:])
    except Exception:
        raise SystemExit("[ERROR] %s 返回无法解析：%s" % (api, raw[idx:idx + 400]))
    return env.get("data") or {}


def list_all_nodes(lib_dir: str, space_id: str, parent_id: str) -> list:
    nodes, offset = [], 0
    while True:
        data = call_api(lib_dir, "space.workspace.list-nodes", {
            "space_id": space_id,
            "parent_node_id": parent_id,
            "limit": 100,
            "offset": offset,
        })
        batch = data.get("nodes") or []
        nodes.extend(batch)
        if not data.get("hasMore") or not batch:
            break
        offset += int(data.get("limit") or 100)
    return nodes


# ---------------------------------------------------------------- 解析

def parse_title(title: str) -> dict:
    title = (title or "").strip()
    stripped = DATE_FULL.sub(" ", title)
    stripped = DATE_COMPACT.sub(" ", stripped)

    code = None
    m = CODE_PAREN.search(title)
    if m:
        digits, suffix = m.group(1), m.group(2)
        if len(digits) == 6 or suffix:      # 6 位 A 股；5 位仅在带 .HK 时认
            code = digits + (".HK" if suffix else "")
    if not code:
        m = CODE_HK.search(stripped)
        if m:
            code = m.group(1) + ".HK"
    if not code:
        m = CODE_BARE.search(stripped)
        if m:
            code = m.group(1)
    # 港股 5 位裸码（无 HK 后缀）不单独识别，避免与 A 股混淆

    rtype = "报告"
    for key in TYPE_KEYS:
        if key in title:
            rtype = key
            break

    m = DATE_FULL.search(title)
    if m:
        date = "%s-%s-%s" % m.groups()
    else:
        m = DATE_COMPACT.search(title)
        date = "%s-%s-%s" % m.groups() if m else ""

    head = NAME_SPLIT.split(title)[0] if title else ""
    name = NAME_JUNK.sub("", head).strip()
    name = re.sub(r"[（(].*$", "", name).strip()

    return {"name": name, "code": code, "rtype": rtype, "date": date}


def code_key(code: str | None) -> str:
    return (code or "").split(".")[0] or ""


def matches(node: dict, code: str | None, name: str | None) -> bool:
    if code:
        if code_key(node.get("code")) and code_key(node.get("code")) == code_key(code):
            return True
    if name and len(name) >= 2:
        node_name = node.get("name") or ""
        if node_name and (name in node_name or node_name in name):
            return True
    return False


def sort_key(node: dict):
    priority = TYPE_KEYS.index(node["rtype"]) if node["rtype"] in TYPE_KEYS else len(TYPE_KEYS)
    return (node["date"] or "0000-00-00", -priority, len(node["title"] or ""))


# ---------------------------------------------------------------- scan

def cmd_scan(args) -> int:
    lib_dir = load_lib_dir(args.lib_dir)
    space_id, folder_id, _ = resolve_ids(args)

    nodes = list_all_nodes(lib_dir, space_id, folder_id)
    folders = [n for n in nodes if (n.get("kind") or "") == "folder"]
    nodes = [n for n in nodes if (n.get("kind") or "") != "folder"]
    parsed = []
    for n in nodes:
        item = parse_title(n.get("title"))
        item.update({"id": n.get("id"), "title": n.get("title") or "",
                     "url": n.get("url") or "",
                     "updated_at": n.get("updatedAt") or 0,
                     "parent_id": n.get("parentId") or ""})
        parsed.append(item)

    hit = [p for p in parsed if matches(p, args.code, args.name)]
    hit.sort(key=sort_key, reverse=True)

    if args.json:
        out(json.dumps({
            "scan_result": "NO_HISTORY" if not hit else ("HISTORY_FOUND" if len(hit) == 1 else "MULTI_VERSION"),
            "folder_id": folder_id,
            "total_nodes": len(parsed),
            "matched": hit,
            "latest": hit[0] if hit else None,
            "to_archive": hit[1:] if hit else [],
            "same_date_need_confirm": [p for p in hit[1:] if p["date"] and p["date"] == hit[0]["date"]] if hit else [],
        }, ensure_ascii=False, indent=1))
        return 0

    out("=== 资料库「个股报告」历史版本检索 ===")
    out("space : %s" % space_id)
    out("folder: %s   （个股报告）" % folder_id)
    out("总节点: %d（报告 %d / 子文件夹 %d）    匹配: %d    条件: code=%s name=%s"
        % (len(parsed) + len(folders), len(parsed), len(folders), len(hit), args.code or "-", args.name or "-"))
    out("")

    if not hit:
        out("SCAN_RESULT: NO_HISTORY")
        out("  未检索到同标的历史报告 → 本次为首次覆盖，按全流水线正常做；收尾无需归档。")
        out("  若确有历史报告却报 NO_HISTORY，请核对 --code / --name，或该节点不在「个股报告」文件夹内。")
        return 0

    out("  #  日期        状态     类型            标题")
    for i, p in enumerate(hit, 1):
        stamp = p["date"] or "(无日期)"
        flag = "LATEST " if i == 1 else "ARCHIVE"
        out("  %-2d %-10s  %-7s  %-13s  %s" % (i, stamp, flag, p["rtype"], p["title"]))
        out("     node_id=%s  updated=%s" % (p["id"], fmt_ts(p["updated_at"])))
    out("")

    same_day = [p for p in hit[1:] if p["date"] and p["date"] == hit[0]["date"]]

    if len(hit) == 1:
        out("SCAN_RESULT: HISTORY_FOUND")
        out("  ★ 命中 1 版历史报告 —— **必须停下，向用户确认评估模式**：")
        out("      A 全面重新评估（从头跑全流水线；⑩ 节须有「前次判断复盘」段）")
        out("      B 基于旧报告更新（沿用旧版结构与框架，只更新已变化的数据与事实）")
        out("    未答复前不得开始取数。确认结果写进当日 memory 日志。")
        out("    （同日多类型共存、或扫描到重复上传，也可能只剩 1 版；两种情况都无需归档。）")
    else:
        out("SCAN_RESULT: MULTI_VERSION")
        out("  ★ 命中 %d 版，同标的新老并存 —— 两件事都要做：" % len(hit))
        out("     1) 向用户确认评估模式（A 全面重估 / B 基于旧版更新），未答复前不得取数；")
        out("     2) **新版上传后**把下列旧版移入「旧版归档」，使「个股报告」内只剩最新一版：")
        for p in hit[1:]:
            mark = "  ⚠ 与最新版同日、仅类型不同" if p in same_day else ""
            out("        · %s   node_id=%s%s" % (p["title"], p["id"], mark))
        out("")
        out("LATEST     : %s   node_id=%s" % (hit[0]["title"], hit[0]["id"]))
        out("TO_ARCHIVE : %s" % ", ".join(p["id"] for p in hit[1:]))
        if same_day:
            out("")
            out("  ⚠ 上表标 ⚠ 的与最新版**同日、仅报告类型不同**（如「投资分析报告」与专题测算）。")
            out("    这类可能属**互补文档而非新老版本**，归档会一并移走。**归档前必须人工判断**：")
            out("    确属互补 → 保留，不归档；确属取代 → 才归档。脚本只给建议清单，不代替判断。")
    return 0


def fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


# ---------------------------------------------------------------- audit

def group_key(item: dict, name_codes: dict) -> str:
    """归组键：有代码用代码；无代码看该名称在全库是否只对应一个代码，是则借用。"""
    code = code_key(item.get("code"))
    if code:
        return code
    name = item.get("name") or ""
    codes = name_codes.get(name) or set()
    if name and len(codes) == 1:
        return next(iter(codes))
    return "name:" + name if name else ""


def cmd_audit(args) -> int:
    lib_dir = load_lib_dir(args.lib_dir)
    space_id, folder_id, _ = resolve_ids(args)

    nodes = list_all_nodes(lib_dir, space_id, folder_id)
    folders = [n for n in nodes if (n.get("kind") or "") == "folder"]
    nodes = [n for n in nodes if (n.get("kind") or "") != "folder"]
    parsed = []
    for n in nodes:
        item = parse_title(n.get("title"))
        item.update({"id": n.get("id"), "title": n.get("title") or "",
                     "updated_at": n.get("updatedAt") or 0})
        parsed.append(item)

    # 名称 → 代码集合（供无代码节点借码）
    name_codes = {}
    for p in parsed:
        if p.get("name") and code_key(p.get("code")):
            name_codes.setdefault(p["name"], set()).add(code_key(p["code"]))

    groups = {}
    unkeyed = []
    for p in parsed:
        k = group_key(p, name_codes)
        if k:
            groups.setdefault(k, []).append(p)
        else:
            unkeyed.append(p)
    for v in groups.values():
        v.sort(key=sort_key, reverse=True)

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    dup_titles = {}
    for p in parsed:
        dup_titles.setdefault(p["title"], []).append(p)
    dup_titles = {k: v for k, v in dup_titles.items() if len(v) > 1}

    plans = []          # 每个需要归档的标的：{key, name, latest, old[], same_day_old[]}
    for k, v in sorted(multi.items(), key=lambda kv: kv[1][0]["name"]):
        same_day = [p for p in v[1:] if p["date"] and p["date"] == v[0]["date"]]
        plans.append({"key": k, "name": v[0]["name"] or k, "latest": v[0],
                      "old": v[1:], "same_day": same_day})

    to_archive = [p for pl in plans for p in pl["old"]]

    if args.json:
        out(json.dumps({
            "total_nodes": len(parsed) + len(folders),
            "reports": len(parsed),
            "folders": len(folders),
            "duplicate_titles": [{"title": k, "ids": [p["id"] for p in v]} for k, v in dup_titles.items()],
            "unkeyed": unkeyed,
            "all_groups": {k: v for k, v in sorted(groups.items())},
            "multi_groups": plans,
            "to_archive": to_archive,
            "audit_result": "CLEAN" if not plans and not dup_titles else "NEEDS_ACTION",
        }, ensure_ascii=False, indent=1))
        return 0

    out("=== 资料库「个股报告」全量盘查 ===")
    out("space : %s" % space_id)
    out("folder: %s   （个股报告）" % folder_id)
    out("节点: %d（报告 %d / 子文件夹 %d）    独立标的组: %d    多版本组: %d"
        % (len(parsed) + len(folders), len(parsed), len(folders), len(groups), len(multi)))
    out("")

    if unkeyed:
        out("--- ⚠ 无法归组（标题里既无代码、名称也解析不出）%d 条，需人工看 ---" % len(unkeyed))
        for p in unkeyed:
            out("   · %s   node_id=%s" % (p["title"], p["id"]))
        out("")

    if dup_titles:
        out("--- ⚠ 完全同名（同一标题出现 ≥2 次，疑重复上传）%d 组 ---" % len(dup_titles))
        for t, v in dup_titles.items():
            out("   · %s   ×%d" % (t, len(v)))
            for p in v:
                out("        node_id=%s  updated=%s" % (p["id"], fmt_ts(p["updated_at"])))
        out("")

    if not plans:
        out("AUDIT_RESULT: CLEAN")
        out("  未发现同标的多版本并存，无需归档。")
        return 0

    out("--- 需要归档的标的（%d 组，共 %d 条旧版）---" % (len(plans), len(to_archive)))
    for pl in plans:
        borrowed = "" if code_key(pl["latest"].get("code")) else "   ← 借名归组"
        out("[%s] %s   共 %d 版%s" % (pl["key"], pl["name"], len(pl["old"]) + 1, borrowed))
        p = pl["latest"]
        out("   KEEP     %-10s %-13s %s   id=%s" % (p["date"] or "(无日期)", p["rtype"], p["title"], p["id"]))
        for q in pl["old"]:
            mark = "  ⚠ 与最新版同日、仅类型不同" if q in pl["same_day"] else ""
            out("   ARCHIVE  %-10s %-13s %s   id=%s%s"
                % (q["date"] or "(无日期)", q["rtype"], q["title"], q["id"], mark))
        out("")

    out("AUDIT_RESULT: NEEDS_ACTION")
    out("  待归档 %d 条（每个标的只保留上面 KEEP 的那一版）：" % len(to_archive))
    out("    %s" % ", ".join(p["id"] for p in to_archive))
    if any(pl["same_day"] for pl in plans):
        out("")
        out("  ⚠ 标 ⚠ 的条目与最新版**同日、仅报告类型不同**，可能属互补文档而非新老版本。")
        out("    归档前必须人工判断：确属互补 → 保留；确属取代 → 才归档。")
    out("")
    out("  执行（先 --dry-run 看清要动哪些）：")
    out("    python lib_reports.py archive --manifest <manifest> \\")
    out("      %s" % " \\\n      ".join("--node-id %s" % p["id"] for p in to_archive))
    out("  执行后必须回扫核对：python lib_reports.py audit   → 期望 AUDIT_RESULT: CLEAN")
    return 0


# ---------------------------------------------------------------- archive

def cmd_archive(args) -> int:
    lib_dir = load_lib_dir(args.lib_dir)
    space_id, _, archive_id = resolve_ids(args)
    if not archive_id:
        raise SystemExit("[ERROR] 缺少归档文件夹 ID：用 --archive-id 或 --manifest 提供。")

    moved, skipped, failed = [], [], []
    for node_id in args.node_id:
        cur = None
        try:
            info = call_api(lib_dir, "space.workspace.node-info", {"node_id": node_id})
            node = info.get("node") or info
            cur = node.get("parentId")
        except SystemExit:
            cur = None
        if cur == archive_id:
            skipped.append(node_id)
            out("[SKIP ] %s 已在「旧版归档」内（幂等跳过）" % node_id)
            continue
        if args.dry_run:
            moved.append(node_id)
            out("[DRY  ] 将移动 %s  →  %s" % (node_id, archive_id))
            continue
        try:
            call_api(lib_dir, "space.workspace.move-node",
                     {"node_id": node_id, "target_parent_id": archive_id})
            moved.append(node_id)
            out("[MOVE ] %s  →  旧版归档(%s)" % (node_id, archive_id))
        except SystemExit as exc:
            failed.append(node_id)
            out("[FAIL ] %s  %s" % (node_id, exc))

    out("")
    out("归档结果：moved=%d  skipped=%d  failed=%d%s"
        % (len(moved), len(skipped), len(failed), "  (dry-run)" if args.dry_run else ""))
    if not args.dry_run and moved:
        out("回扫核对（必须）：python lib_reports.py scan --code <代码> --name <简称>")
        out("  期望 SCAN_RESULT=HISTORY_FOUND（只剩最新一版）。")
    return 1 if failed else 0


# ---------------------------------------------------------------- 参数

def resolve_ids(args):
    space_id = getattr(args, "space_id", None) or DEFAULT_SPACE_ID
    folder_id = getattr(args, "folder_id", None) or DEFAULT_FOLDER_ID
    archive_id = getattr(args, "archive_id", None) or DEFAULT_ARCHIVE_ID
    manifest = getattr(args, "manifest", None)
    if manifest:
        with io.open(manifest, encoding="utf-8") as fh:
            space = (json.load(fh) or {}).get("space") or {}
        space_id = args.space_id or space.get("space_id") or space_id
        folder_id = args.folder_id or space.get("report_folder_id") or folder_id
        archive_id = args.archive_id or space.get("archive_folder_id") or archive_id
    return space_id, folder_id, archive_id


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lib-dir", help="library skill 目录（含 space_api.py）")
    common.add_argument("--manifest", help="watchlist_manifest.json 路径（读取 space 段）")
    common.add_argument("--space-id")
    common.add_argument("--folder-id")
    common.add_argument("--archive-id")

    p = argparse.ArgumentParser(description="资料库个股报告检索 / 旧版归档")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", parents=[common], help="检索同标的历史版本（只读）")
    s.add_argument("--code", help="6 位代码；港股 5 位或 5位.HK")
    s.add_argument("--name", help="标的简称（代码不可得时的兜底）")
    s.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    s.set_defaults(func=cmd_scan)

    u = sub.add_parser("audit", parents=[common], help="全量盘查：列出所有多版本组与重复标题（只读）")
    u.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    u.set_defaults(func=cmd_audit)

    a = sub.add_parser("archive", parents=[common], help="把旧版节点移入「旧版归档」（幂等）")
    a.add_argument("--node-id", action="append", required=True, help="可重复传多个")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_archive)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
