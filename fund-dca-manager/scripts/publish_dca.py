# -*- coding: utf-8 -*-
"""
定投台账一键发布
------------------------------------------------------------
做三件事：
  1. 渲染 HTML（调用 render_dca_html.py）
  2. 上传到资料库；已有节点则原地覆盖，不产生重复条目
  3. 首次上传后把 node_block_id 回写进 dca_plan.json，之后自动覆盖

用法：
  python publish_dca.py                 # 渲染 + 发布
  python publish_dca.py --no-upload     # 只渲染，不上传
  python publish_dca.py --rebuild       # 忽略已存 node id，新建节点
------------------------------------------------------------
"""
import io
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = ("C:/Users/MrLi/AppData/Local/Programs/WorkBuddy/resources/"
           "app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/library")
SPACE_ID = "lWmChDNEl28HPp3VjuY5W7"
FOLDER_ID = "ujlYAui5OmAlkvfEjReBOW"


def find_lib_dir():
    """自动定位 library skill 目录（各机器用户名不同，不能硬编码）"""
    rel = os.path.join("resources", "app.asar.unpacked", "resources", "plugins",
                       "workbuddy-builtin", "skills", "library")
    cands = []
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            cands.append(os.path.join(base, "Programs", "WorkBuddy", rel))
    cands.append(os.path.join(os.path.expanduser("~"), "AppData", "Local",
                              "Programs", "WorkBuddy", rel))
    for c in cands:
        if os.path.exists(os.path.join(c, "page", "import_html.py")):
            return c
    return ""


def arg(name, default=None):
    a = sys.argv[1:]
    if name in a:
        i = a.index(name)
        return a[i + 1] if i + 1 < len(a) else default
    return default


def main():
    cfg_path = arg("--config", os.path.join(HERE, "dca_plan.json"))
    no_upload = "--no-upload" in sys.argv
    rebuild = "--rebuild" in sys.argv
    lib_dir = arg("--lib-dir", "") or find_lib_dir() or LIB_DIR

    # 0) 读配置：台账与产物路径都跟配置走，不落到 skill 安装目录
    with io.open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg_dir = os.path.dirname(os.path.abspath(cfg_path))
    out_dir = cfg.get("output_dir") or os.path.join(cfg_dir, "定投记录")
    ledger_path = os.path.join(out_dir, "ledger.csv")

    # 1) 渲染
    render = os.path.join(HERE, "render_dca_html.py")
    out_html = os.path.join(cfg_dir, "定投台账_%s.html" % time.strftime("%Y-%m-%d"))
    r = subprocess.run([sys.executable, render, "--config", cfg_path,
                        "--ledger", ledger_path, "--out", out_html],
                       cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("渲染失败，终止")
        return 1
    m = re.search(r"已生成\s+(.+?html)", r.stdout)
    if not m:
        print("未拿到输出路径，终止")
        return 1
    html_path = m.group(1).strip()

    if no_upload:
        print("（--no-upload 已指定，未上传）")
        return 0

    # 2) 读配置里的节点信息
    lib = cfg.get("library", {}) or {}
    node_id = "" if rebuild else lib.get("node_block_id", "")
    space_id = lib.get("space_id", SPACE_ID)
    folder_id = lib.get("folder_id", FOLDER_ID)

    # 3) 上传
    importer = os.path.join(lib_dir, "page", "import_html.py")
    if not os.path.exists(importer):
        print("找不到 import_html.py：%s" % importer)
        print("请用 --lib-dir 指定 library skill 目录")
        return 1

    cmd = [sys.executable, importer, html_path, "--space-id", space_id]
    if node_id:
        cmd += ["--node-block-id", node_id]
        print("原地覆盖已有节点 %s" % node_id)
    else:
        cmd += ["--parent-id", folder_id]
        print("首次上传，在文件夹 %s 下新建节点" % folder_id)

    r2 = subprocess.run(cmd, cwd=lib_dir, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    out = (r2.stdout or "") + (r2.stderr or "")
    print(out.strip())
    m2 = re.search(r"KS_IMPORT_OK\s+(\{.*\})", out)
    if not m2:
        print("上传未返回成功标记")
        return 1

    info = json.loads(m2.group(1))
    new_id = info.get("node_block_id", "")

    # 4) 回写节点 id
    if new_id and new_id != node_id:
        cfg["library"] = {
            "space_id": space_id,
            "folder_id": folder_id,
            "node_block_id": new_id,
            "url": info.get("url", ""),
            "_备注": "首次上传后自动写入；之后发布自动原地覆盖",
        }
        with io.open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("已把 node_block_id 写回配置：%s" % new_id)

    url = info.get("url", "")
    if url:
        print("\n资料库地址：%s" % url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
