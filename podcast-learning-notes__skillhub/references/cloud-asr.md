# 云转写 API 配置

当用户想用通义、飞书、讯飞、Deepgram 等云转写，或已经拿到这些服务导出的 JSON/TXT/Markdown 结果时读取本文件。

## 何时优先云 ASR

云 ASR 适合单次、低频、希望省配置时间的任务：

- 用户可接受按量付费。
- 不想下载 FunASR 模型或等待本地 CPU 长时间推理。
- 希望直接获得标点、时间戳、说话人分离或专名优化能力。
- 用户已经有飞书妙记、通义听悟等工具生成的文字稿/API 结果。

本地 FunASR 仍适合跑批、长期低成本、隐私敏感或离线环境。

## 输出约定

无论云服务返回什么格式，都必须汇合到：

```text
source/asr/<provider>/transcript.md
source/asr/<provider>/raw.json
source/asr/<provider>/extraction-notes.md
source/transcript.md          # 最终采用版，由确认后的 provider transcript 复制/规范化而来
source/extraction-notes.md    # 顶层索引和共通风险
```

provider 自己的 `transcript.md` 必须诚实标注：

- 云服务名称和模型。
- 是否有说话人分离。
- 是否有时间戳。
- 是否未核对原音频。
- 若说话人只是匿名编号，保留“说话人1/说话人2”，不要硬猜姓名。

顶层 `source/extraction-notes.md` 不要平铺堆满每个 provider 的细节。它只记录：本期播客来源、最终采用哪一版、为什么采用、候选专名纠错、对最终笔记有影响的共通风险。某个 provider 的独有问题写到 `source/asr/<provider>/extraction-notes.md`。

## 通义 / DashScope

用户需要提供：

```text
DASHSCOPE_API_KEY=...
```

优先使用音频直链。小宇宙页面先用 `scripts/download_xiaoyuzhou_episode.py` 提取 `media.xyzcdn.net/...m4a`，再把直链传给通义；这通常比上传本地文件更省事。

运行示例：

```bash
python scripts/transcribe_cloud_asr.py tongyi \
  --audio-url "https://media.xyzcdn.net/.../episode.m4a" \
  --output source/asr/tongyi/transcript.md \
  --raw-json source/asr/tongyi/raw.json
```

若脚本提示当前 `dashscope` SDK 不支持某个参数，先去掉说话人分离参数跑通转写；不要为了凑格式伪造说话人。

## 飞书妙记

飞书更适合作为“用户已在飞书侧完成转写/导出”的输入来源。不同租户的妙记、云文档和开放平台权限差异较大，不要在 skill 里假设所有用户都有同一个可调用的转写端点。

推荐路径：

1. 用户在飞书妙记完成转写。
2. 导出 `.txt`、`.md`、`.docx`，或通过用户自己的飞书开放平台应用拿到 JSON。
3. 使用 `scripts/transcribe_cloud_asr.py normalize` 规范化为 `source/transcript.md`。

示例：

```bash
python scripts/transcribe_cloud_asr.py normalize \
  --provider feishu \
  --input-json source/asr/feishu/raw.json \
  --output source/asr/feishu/transcript.md
```

若用户只给了飞书导出的 `.txt/.md`，走文字稿输入路径，直接规范化为 `source/transcript.md`。

## 失败处理

- **缺少 API Key**：提示用户设置环境变量，不要要求把密钥写进聊天或 repo。
- **云服务要求公网可访问 URL**：优先传小宇宙音频直链；本地音频文件不能直接传时，让用户选择上传到自己的对象存储或改走本地 FunASR。
- **没有说话人分离**：继续产出 provider transcript，但在头部标注“未分离说话人”，并在 `source/asr/<provider>/extraction-notes.md` 标记风险；若最终采用该版，再把风险提升到顶层 `source/extraction-notes.md`。
- **没有时间戳**：继续产出 transcript，后续笔记跳过关键结论时间戳锚点，或使用 show notes 的章节时间戳作为粗粒度辅助。
- **专名错误**：结合 `source/show-notes.md` 做候选纠错。provider 专属错误写进 `source/asr/<provider>/extraction-notes.md`；最终采用稿仍存在或影响笔记的错误再写进顶层 `source/extraction-notes.md`。不要静默改写不确定内容。
