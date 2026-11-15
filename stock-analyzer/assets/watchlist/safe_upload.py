# -*- coding: utf-8 -*-
"""台账上传的唯一入口：先备份、再比对模块、然后才覆盖，事后回拉校验。

**为什么需要这个脚本**（2026-11-09 事故）：
资料库的页面导入 API 语义是「整页 blob 替换」，没有 patch 能力。所以
「本地重建 → 覆盖上传」这条链必然全损，而 `import_html.py --node-block-id`
本身不做任何比对、也不留旧版。事故当时施洛斯视图就是这么被吃掉的，
且我在上传前拿「本地旧件 grep 不到」去证否线上存在性 —— 那个检验在结构上
不可能给出证据（本地从来没落过那一版）。

**本脚本把三件事变成不可跳过**：
  1. 覆盖前强制拉当前线上版到 `.tmp/lib-backup/<node>/v<N>-<时间>/`，
     拉不到就中止 —— 没有备份就不允许覆盖。
  2. 上传前做模块比对：线上有、新件没有的模块直接 block（退出码 4），
     必须显式 `--allow-module-loss` 才放行。
  3. 上传后回拉新版本再比一次，确认模块没少、体积没塌。

用法：
    python assets/watchlist/safe_upload.py \
        --html "投资观察池台账-20261109.html" \
        --node-block-id "D7PSM0kGVEWKGFnUaSehu7" \
        --space-id "lWmChDNEl28HPp3VjuY5W7"

    # 只做「备份 + 比对」，不上传（推荐每次上传前先跑这个）
    python assets/watchlist/safe_upload.py --html x.html --node-block-id D... --dry-run

    # 首次发布（线上还没有这个节点）
    python assets/watchlist/safe_upload.py --html x.html --space-id S... --parent-id P...

退出码：0 成功 ｜ 2 本地文件缺失 ｜ 3 找不到资料库脚本 ｜ 4 模块缺失被拦截
        ｜ 5 备份失败 ｜ 6 上传失败 ｜ 7 回拉校验不通过
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import time

# ── 线上页面必须存在的模块。key=人话名，value=页面里的稳定锚点 ───────────────
# 只用 id / class 这类结构性锚点，不用文案（文案会随数据变）。
GUARDED_MODULES = [
    ("施洛斯策略观察视图", 'id="view-schl"'),
    ("施洛斯 Tab 按钮", 'data-v="schl"'),
    ("持仓视图", 'id="view-pos"'),
    ("持仓数据表绑定", 'id="posSrc"'),
    ("分页/筛选 Tab 组", 'data-v="pool"'),
    ("页脚口径说明", 'id="ledger-foot"'),
    ("页内刷新现价", 'function refresh('),
]

# 体积 / 结构退化阈值：新件相对旧件低于这个比例就告警（block 由模块比对负责）
SIZE_RATIO_WARN = 0.90


def find_library_page_dir(explicit=""):
    """定位 WorkBuddy 内置 library 技能的 page 目录。跨平台、不写死用户名。"""
    if explicit:
        return explicit if os.path.isdir(explicit) else ""
    cands = []
    env = os.environ.get("WORKBUDDY_LIBRARY_PAGE_DIR", "")
    if env:
        cands.append(env)
    roots = [
        os.environ.get("LOCALAPPDATA", ""),
        os.path.join(os.path.expanduser("~"), "AppData", "Local"),
        "/Applications",
        os.path.join(os.path.expanduser("~"), "Applications"),
        "/opt",
        "/usr/lib",
    ]
    rels = [
        "Programs/WorkBuddy/resources/app.asar.unpacked/resources/plugins/"
        "workbuddy-builtin/skills/library/page",
        "WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/plugins/"
        "workbuddy-builtin/skills/library/page",
    ]
    for r in roots:
        if not r:
            continue
        for rel in rels:
            cands.append(os.path.join(r, rel))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "import_html.py")):
            return c
    # 兜底：在常见安装根下做一层通配（不递归全盘）
    for r in roots:
        if not r or not os.path.isdir(r):
            continue
        hits = glob.glob(os.path.join(r, "*", "resources", "app.asar.unpacked",
                                      "resources", "plugins", "workbuddy-builtin",
                                      "skills", "library", "page"), recursive=False)
        hits += glob.glob(os.path.join(r, "*.app", "Contents", "Resources",
                                       "app.asar.unpacked", "resources", "plugins",
                                       "workbuddy-builtin", "skills", "library", "page"))
        for h in hits:
            if os.path.isfile(os.path.join(h, "import_html.py")):
                return h
    return ""


def run_tool(page_dir, script, args, timeout=300):
    """调资料库脚本，返回 (ok, payload)。脚本约定：成功打一行 `KS_<TAG> {...}`（TAG 有
    ARTIFACTS_OK / IMPORT_OK / ARTIFACTS_LIST 等，不统一），失败打一行 {"error": ...}，
    退出码恒 0 —— 所以只能解析 stdout，不能看 returncode。"""
    cmd = [sys.executable, os.path.join(page_dir, script)] + args
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout)
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^KS_[A-Z_]+\s+(\{.*\})$", line)
        if m:
            try:
                return True, json.loads(m.group(1))
            except ValueError:
                return True, {}
        if line.startswith("{") and '"error"' in line:
            try:
                return False, json.loads(line)
            except ValueError:
                return False, {"error": line}
    return False, {"error": (err or out or "无输出").strip()[:400]}


def list_version(page_dir, node_id):
    ok, d = run_tool(page_dir, "download_page_artifacts.py",
                     ["--node-id", node_id, "--list-only"])
    if not ok:
        return None, d.get("error", "list 失败")
    return d, ""


def backup_current(page_dir, node_id, base_dir, tag=""):
    """把线上当前版整包拉到本地，返回 (entry_path, version, backup_dir)。"""
    meta, err = list_version(page_dir, node_id)
    if meta is None:
        return None, None, err
    ver = str(meta.get("version") or "v")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(base_dir, "v%s-%s%s" % (ver, stamp, ("-" + tag) if tag else ""))
    ok, d = run_tool(page_dir, "download_page_artifacts.py",
                     ["--node-id", node_id, "--version", ver, "--out-dir", out_dir])
    if not ok:
        return None, None, "备份下载失败：%s" % d.get("error", "")
    work = d.get("work_dir") or out_dir
    entry = d.get("entry_html") or ""
    path = entry if os.path.isabs(entry) else os.path.join(work, entry)
    if not os.path.isfile(path):
        cand = glob.glob(os.path.join(work, "*.html"))
        if not cand:
            return None, None, "备份目录里没有 html：%s" % work
        path = cand[0]
    if os.path.getsize(path) < 1024:
        return None, None, "备份文件异常小：%s" % path
    return path, ver, ""


def module_report(old_html, new_html):
    """比对受保护模块。返回 (lost, added, sizes)。"""
    lost, added = [], []
    for label, anchor in GUARDED_MODULES:
        o, n = old_html.count(anchor), new_html.count(anchor)
        if o > 0 and n < o:
            lost.append("%s（线上 %d 处 → 新件 %d 处，锚点 %s）" % (label, o, n, anchor))
        elif o == 0 and n > 0:
            added.append(label)
    return lost, added


def structure_stats(html):
    """结构指纹。**故意不用原始字节数比大小**：线上件被平台注入了
    data-page-node-id、_lazy/_vis、inject.js 等，体积会膨胀 50%–100%，
    拿本地件跟线上件比字节必然误报。改用剥离 script/style/注释/标签后的
    纯文本长度，这个口径两边可比。"""
    txt = re.sub(r"(?is)<script.*?</script>", " ", html)
    txt = re.sub(r"(?is)<style.*?</style>", " ", txt)
    txt = re.sub(r"(?s)<!--.*?-->", " ", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", "", txt)
    return {
        "bytes": len(html.encode("utf-8")),
        "text": len(txt),
        "sections": len(re.findall(r"<section\b", html)),
        "buttons": len(re.findall(r"<button\b", html)),
        "tables": len(re.findall(r"<table\b", html)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="要上传的本地台账 HTML")
    ap.add_argument("--node-block-id", default="", help="覆盖已有节点时的 node id")
    ap.add_argument("--space-id", default="", help="目标空间 id（首次发布用）")
    ap.add_argument("--parent-id", default="", help="目标父节点 id（首次发布用）")
    ap.add_argument("--file-name", default="", help="首次发布时的展示名")
    ap.add_argument("--backup-root", default="",
                    help="备份根目录，缺省 <html 所在目录>/.tmp/lib-backup/<node>")
    ap.add_argument("--library-page-dir", default="", help="手动指定 library/page 目录")
    ap.add_argument("--allow-module-loss", action="store_true",
                    help="明知会丢模块仍要上传（会在日志里留痕）")
    ap.add_argument("--dry-run", action="store_true", help="只备份+比对，不上传")
    ap.add_argument("--skip-post-verify", action="store_true", help="跳过上传后回拉校验")
    a = ap.parse_args()

    if not os.path.isfile(a.html):
        print("ERR 本地文件不存在：%s" % a.html)
        return 2
    page_dir = find_library_page_dir(a.library_page_dir)
    if not page_dir:
        print("ERR 找不到资料库脚本目录（library/page）。")
        print("    可用 --library-page-dir 指定，或设 WORKBUDDY_LIBRARY_PAGE_DIR。")
        return 3
    print("资料库脚本：%s" % page_dir)

    new_html = io.open(a.html, encoding="utf-8").read()
    ns = structure_stats(new_html)
    print("新件：%s ｜ %.0f KB ｜ section %d ｜ button %d ｜ table %d"
          % (os.path.basename(a.html), ns["bytes"] / 1024.0,
             ns["sections"], ns["buttons"], ns["tables"]))

    # ── 1. 备份 ────────────────────────────────────────────────────────
    old_html, old_ver, old_stats = None, None, None
    if a.node_block_id:
        base = a.backup_root or os.path.join(
            os.path.dirname(os.path.abspath(a.html)), ".tmp", "lib-backup",
            a.node_block_id[:12])
        os.makedirs(base, exist_ok=True)
        print("[1/4] 备份线上当前版 …")
        path, ver, err = backup_current(page_dir, a.node_block_id, base)
        if path is None:
            print("ERR 备份失败，已中止（没有备份就不覆盖）：%s" % err)
            return 5
        old_ver = ver
        old_html = io.open(path, encoding="utf-8").read()
        old_stats = structure_stats(old_html)
        print("      v%s → %s ｜ %.0f KB" % (ver, path, old_stats["bytes"] / 1024.0))

        # ── 2. 模块比对 ────────────────────────────────────────────────
        print("[2/4] 模块完整性比对 …")
        lost, added = module_report(old_html, new_html)
        for label in added:
            print("      + 新增模块：%s" % label)
        if lost:
            print("      ✗ 以下模块会在这次覆盖中消失：")
            for x in lost:
                print("        - %s" % x)
            if not a.allow_module_loss:
                print("BLOCK 已中止。确认要丢这些模块就加 --allow-module-loss；"
                      "否则先补回内容再上传。")
                print("      备份仍在：%s" % path)
                return 4
            print("      ! 已按 --allow-module-loss 放行 —— 本次上传会丢上述模块")
        else:
            print("      ✓ 受保护模块 %d 项全部保留" % len(GUARDED_MODULES))
        ratio = ns["text"] / float(old_stats["text"] or 1)
        if ratio < SIZE_RATIO_WARN:
            print("      ! 正文字数仅旧版的 %.0f%%（%d → %d 字），请确认不是半成品"
                  % (ratio * 100, old_stats["text"], ns["text"]))
        else:
            print("      正文 %d → %d 字（%.0f%%，按去标签纯文本比，可与线上件直比）"
                  % (old_stats["text"], ns["text"], ratio * 100))
    else:
        print("[1/4] 首次发布（无 node-block-id），跳过备份与比对")
        print("[2/4] 跳过")

    if a.dry_run:
        print("[dry-run] 未上传。备份位置见上。")
        return 0

    # ── 3. 上传 ────────────────────────────────────────────────────────
    print("[3/4] 上传 …")
    args = [os.path.abspath(a.html)]
    if a.node_block_id:
        args += ["--node-block-id", a.node_block_id]
    if a.space_id:
        args += ["--space-id", a.space_id]
    if a.parent_id:
        args += ["--parent-id", a.parent_id]
    if a.file_name and not a.node_block_id:
        args += ["--file-name", a.file_name]
    ok, d = run_tool(page_dir, "import_html.py", args, timeout=600)
    if not ok:
        print("ERR 上传失败：%s" % d.get("error", ""))
        return 6
    node = d.get("node_block_id") or a.node_block_id
    print("      ✓ %s ｜ %s" % (d.get("file_name", os.path.basename(a.html)),
                                d.get("url", "")))
    print("      node_block_id = %s" % node)

    # ── 4. 回拉校验 ────────────────────────────────────────────────────
    if a.skip_post_verify or not node:
        print("[4/4] 已跳过回拉校验")
        return 0
    print("[4/4] 回拉新版本校验 …")
    base = a.backup_root or os.path.join(
        os.path.dirname(os.path.abspath(a.html)), ".tmp", "lib-backup",
        node[:12])
    path2, ver2, err = backup_current(page_dir, node, base, tag="post")
    if path2 is None:
        print("ERR 上传已成功，但回拉校验失败：%s" % err)
        print("    线上可能正常，请手工核对。")
        return 7
    got = io.open(path2, encoding="utf-8").read()
    lost2, _ = module_report(old_html or "", got)
    # 上传后是平台注入版：体积会膨胀，只比模块与关键锚点，不比字节。
    need = ['id="view-schl"', 'data-v="schl"', 'id="view-pos"', 'id="posSrc"']
    miss = [x for x in need if x in new_html and x not in got]
    print("      v%s ｜ %.0f KB ｜ 模块缺失 %d 项"
          % (ver2, len(got.encode("utf-8")) / 1024.0, len(lost2) + len(miss)))
    if lost2 or miss:
        print("ERR 回拉校验不通过：%s" % ("；".join(lost2 + miss)))
        return 7
    print("      ✓ 模块齐全，上传完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
