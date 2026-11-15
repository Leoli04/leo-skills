# 小宇宙单集页输入

当用户提供 `xiaoyuzhoufm.com` 单集页面 URL 时读取本文件。

## 目标

把小宇宙单集页拆成两个 source 文件：

```text
source/audio.m4a
source/show-notes.md
```

音频用于后续 FunASR 转写；show notes 是辅助元数据，用于帮助确认标题、发布时间、音频时长、节目简介、官方分段大纲、嘉宾信息和专名线索。

## 推荐命令

```bash
python podcast-learning-notes/scripts/download_xiaoyuzhou_episode.py \
  "https://www.xiaoyuzhoufm.com/episode/..." \
  --audio-out source/audio.m4a \
  --notes-out source/show-notes.md
```

若没有指定输出路径，脚本会在当前目录写出 `audio.m4a` 和 `show-notes.md`。

## 提取规则

- 先用普通 HTTP 请求读取页面 HTML。
- 在源码中查找 `media.xyzcdn.net` 域名下的 `.m4a` 音频直链。
- 同时从页面源码中的 meta、JSON、`__NEXT_DATA__` 和可见文本中提取 show notes。
- 在 `show-notes.md` 顶部写入“元数据”块，尽量包含单集标题、节目名、原始链接、发布时间、音频时长和音频直链。若页面没有暴露某个字段，就省略该字段，不编造。
- 如果普通请求拿不到音频或 show notes，再尝试 Playwright 渲染页面后提取。
- 找不到音频地址时，清楚提示用户，不绕过登录、权限限制或 DRM。

## 使用边界

- `show-notes.md` 不替代 `transcript.md`。
- show notes 可辅助专名纠错和结构规划，但不能用来编造 transcript 中没有的说话内容。
- 若 show notes 与 transcript 冲突，在 `source/extraction-notes.md` 标注“来源不一致”。
- 若 show notes 里有时间戳大纲，而 transcript 无时间戳，可把 show notes 时间戳作为“官方大纲时间戳”标明来源，不要伪装成逐句转写时间戳。
