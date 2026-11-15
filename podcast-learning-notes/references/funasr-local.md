# 本地 FunASR 配置（带说话人分离）

第一次处理音频、配置本地 FunASR、测试转写服务，或向用户解释输入格式时读取本文件。

播客是多人对话，转写稿必须区分说话人，否则只是一坨没人头的文字，无法做学习笔记。本文件统一走 **FunASR `AutoModel` + `cam++` 说话人分离** 路线，不再使用纯转写的 OpenAI-compatible server（那条链路不输出说话人）。

## 何时使用本地 FunASR

本地 FunASR 适合跑批和长期使用：

- 多期播客批量转写。
- 不想按分钟付费。
- 希望音频尽量留在本地。
- 能接受一次性安装模型和依赖。

如果用户只是偶尔处理一两期播客，优先建议：

- 直接上传官方文字稿（最好是带说话人区分的稿子）。
- 用通义听悟、飞书妙记、讯飞、Deepgram 等带说话人分离的付费转写服务导出 `.md/.txt`。

本 skill 不应把“本地 FunASR”当成唯一转写路径。但只要走 FunASR，就走带 `cam++` 的 diarization 链路。

## 推荐方案：AutoModel + cam++

不要用 `/v1/audio/transcriptions` 这种纯转写接口——它只出文本，不分说话人。改为本地直接调 FunASR 的 `AutoModel`，挂上说话人模型：

```python
from funasr import AutoModel

model = AutoModel(
    model="paraformer-zh",   # 转写（英文用 paraformer-en）
    vad_model="fsmn-vad",    # 语音活动检测 / 切句
    punc_model="ct-punc",    # 加标点
    spk_model="cam++",       # ← 说话人分离，关键
)
res = model.generate(input="audio.wav", batch_size_s=300)
# res[0]["sentence_info"]：逐句列表，每句带 text / start / end / spk
```

关键产物是 `res[0]["sentence_info"]`：每个元素是一句话，带 `text`、`start`/`end`（毫秒）、`spk`（说话人编号，整数）。`spk` 就是说话人分离的结果。

约定配置项：

```text
FUNASR_ASR_MODEL=paraformer-zh
FUNASR_SPK_MODEL=cam++
FUNASR_DEVICE=auto            # auto / cuda / cpu
```

`spk` 是匿名编号（0、1、2…），不是真实姓名。把它映射成“说话人1/说话人2”这种占位标签，真实姓名由人工或结合 show notes 后续对应。不要假设编号顺序等于出场顺序，也不要假设说话人数量。

## 安装与设备选择

基础安装：

```bash
pip install funasr modelscope torch torchaudio
```

首次运行会自动下载 paraformer / fsmn-vad / ct-punc / cam++ 模型，是一次性成本，可能较慢。

设备选择（脚本里 `--device auto` 会自动判断）：

- **有 NVIDIA GPU**：用 `cuda`，cam++ diarization 速度可接受。
- **只有 CPU / Mac**：用 `cpu` 兜底，能跑通但长音频明显慢；先用几分钟短音频验证流程，再上整集。Mac 上没有 CUDA，`auto` 会落到 `cpu`。
- 显存/内存不足时，调小 `--batch-size-s`（如 `120`）。

本文件不假设用户已装好环境。若 `import funasr` 失败，提示安装命令，不要把任务卡死——可改走用户上传的、带说话人区分的文字稿。

## 运行转写脚本

优先用 `scripts/transcribe_funasr.py`，它封装了上面的 pipeline，并先产出带说话人标签和时间戳的 provider 转写稿。不要直接覆盖最终 `source/transcript.md`，除非已经确认本地 FunASR 是最终采用版：

```bash
python scripts/transcribe_funasr.py source/audio.m4a \
  --output source/asr/funasr/transcript.md \
  --device auto \
  --raw-json source/asr/funasr/raw.json
```

常用参数：

- `--model paraformer-en`：英文播客。
- `--hotword "嘉宾名 公司名 术语"`：用 show notes 里的专名做热词，降低误识别。
- `--spk-model ""`：临时关闭说话人分离（一般不需要）。
- `--raw-json <path>`：同时保存原始结果，便于排查 `sentence_info` 是否带 `spk`。

脚本会在缺少 `sentence_info` 时退化为纯文本，并在 stderr 明确告警“未做说话人分离”，提示检查 `spk_model` 是否生效、模型是否下载完成。出现这种情况不要假装稿子分好了说话人。

## 输出格式

`source/asr/funasr/transcript.md` 的形态：

```markdown
# 转写稿

> 模型：paraformer-zh + fsmn-vad + ct-punc + cam++
> 说话人：自动分离为 2 个；下列编号为占位标签，需人工对应到真实姓名
> 时间戳：每段起始，格式 [mm:ss]
> 音频核对：未核对原音频；转写可能有漏词/专名误识别/说话人切分错误

## 说话人对照（待人工填写）

- 说话人1 → ？
- 说话人2 → ？

---

[00:00] **说话人1**：……
[00:12] **说话人2**：……
```

“说话人对照”表是给人工/后续步骤填真实姓名用的。结合 `source/show-notes.md` 里的嘉宾信息可以辅助对应，但 cam++ 给的只是匿名编号，对应关系不确定时标“存疑”，不要硬编。

若本地 FunASR 是最终采用版，再把它复制/规范化为 `source/transcript.md`，并在顶层 `source/extraction-notes.md` 写明“最终采用 FunASR”。FunASR 专属风险（模型下载慢、ct-punc 卡住、无 sentence_info、说话人数量异常等）写入 `source/asr/funasr/extraction-notes.md`。

## 输入建议

用户可以提供以下任一输入：

- 本地音频文件路径：`.mp3`、`.m4a`、`.wav`、`.flac` 等，具体取决于 FunASR/ffmpeg 环境。
- 可直接下载的音频 URL。
- 播客单集页面 URL。小宇宙单集页优先用 `scripts/download_xiaoyuzhou_episode.py` 从页面源码/渲染页提取 `media.xyzcdn.net/...m4a` 音频直链；其他播客平台可尝试 RSS/enclosure。
- 已有 `.md` 或 `.txt` 文字稿（最好带说话人区分），跳过 FunASR。

若用户提供的是 Spotify、Apple Podcasts 等播放页链接，可能不是直接音频链接。优先尝试找到该节目的 RSS feed，再从对应 episode 的 `<enclosure url="...">` 里取真实音频地址。小宇宙不要优先走 RSS；按 `references/xiaoyuzhou-source.md` 的页面提取流程处理。

## 音频链接获取

常见方法：

1. 从播客官网或节目页找 RSS feed。
2. 打开 RSS XML，搜索目标单集标题。
3. 找该单集下的 `<enclosure>` 标签，取其中的 `url`，通常就是 mp3/m4a 音频地址。
4. 若没有 RSS，可让用户下载音频文件后直接提供本地路径。

不要绕过平台权限、登录限制或 DRM。拿不到直接音频链接时，改用用户提供的本地文件或官方文字稿。

## 失败处理

- **funasr 未安装**：提示 `pip install funasr modelscope torch torchaudio`，或改走用户上传文字稿路径。
- **模型首次下载慢**：说明这是正常的一次性成本。
- **结果无 `sentence_info` / 无 `spk`**：说明说话人分离没生效。检查 `spk_model=cam++` 是否传入、cam++ 模型是否下载完成、FunASR 版本是否支持。在修好前不要把稿子当作已分说话人。
- **说话人数量明显不对**（如双人对话被切成 5 个人）：保留原始编号，在 `source/asr/funasr/extraction-notes.md` 标记“说话人切分存疑”，必要时回听核对，不要手动合并到看不出依据。若最终采用该版，再把风险提升到顶层 `source/extraction-notes.md`。
- **输出无时间戳**：继续生成笔记，但跳过时间戳锚点。
- **专名识别差**：用 `--hotword` 注入 show notes 里的专名；仍存疑的在 `source/asr/funasr/extraction-notes.md` 标出。若最终采用该版，再把影响笔记的候选纠错写入顶层 `source/extraction-notes.md`。不要硬改不确定内容。
