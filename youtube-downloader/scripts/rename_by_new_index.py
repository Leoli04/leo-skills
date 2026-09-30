"""按 new_index 重命名: 通过 video_id 精确匹配"""
import json, os, re, shutil

OUT = r"F:\lixiaofei\freelancers\youtube-work\Maisy_Mouse"
with open(r"f:\lixiaofei\leo-skills\youtube-downloader\data\series\Maisy_Mouse.json", encoding="utf-8") as f:
    data = json.load(f)

# 构建 video_id -> new_index 映射
vid_to_new = {}
vid_to_old = {}
for vid, v in data["videos"].items():
    if v.get("new_index") is not None:
        vid_to_new[vid] = v["new_index"]
        vid_to_old[vid] = v["index"]

# 扫描目录，根据文件内容类型识别 video_id
# 文件名模式: {NNN}_{Name}_{suffix}.ext
# 我们需要知道每个文件属于哪个 video
# 方案: 从 JSON 的 video_file/burned.file 字段推断 old index

files = os.listdir(OUT)
renamed = 0

for fname in sorted(files):
    old_path = os.path.join(OUT, fname)
    if not os.path.isfile(old_path):
        continue
    m = re.match(r'^(\d{3})_(.+)', fname)
    if not m:
        continue
    old_num = int(m.group(1))
    rest = m.group(2)
    
    # 找到 old_num 对应的 video
    # 从 JSON 中找到 old index == old_num 的 video
    target_vid = None
    target_new = None
    for vid, v in data["videos"].items():
        if v["index"] == old_num:
            target_new = vid_to_new.get(vid)
            break
    
    if target_new is None:
        continue
    
    new_fname = f"{target_new:03d}_{rest}"
    if new_fname == fname:
        continue
    
    new_path = os.path.join(OUT, new_fname)
    if os.path.exists(new_path):
        print(f"  [COLLISION] {fname} <-> {new_fname}")
        # 移走碰撞文件
        backup = new_path + ".bak"
        shutil.move(new_path, backup)
        print(f"    backed up to {os.path.basename(backup)}")
    
    shutil.move(old_path, new_path)
    print(f"  {fname} -> {new_fname}")
    renamed += 1

# 清理备份
for f in os.listdir(OUT):
    if f.endswith(".bak"):
        os.remove(os.path.join(OUT, f))
        print(f"  cleaned: {f}")

print(f"\n重命名: {renamed} 个文件")
