# AI 专名误转写对照表

Phase 1 全文清洗前读取本文件。它用于主动排查“听起来像正常词、但在 AI 语境里语义全变”的危险误转写。

## 使用原则

- 只在上下文强支持时修正；拿不准就标“存疑”，不要硬改。
- 修正后在 `source/extraction-notes.md` 记录“原转写 -> 修正值”和依据。
- 优先结合 `source/show-notes.md` 的标题、嘉宾信息、官方大纲和专名写法。
- 不要把所有相似词都替换成 AI 专名；逐处判断语境。

## 高频危险误转写

| 误转写候选 | 可能正确写法 | 排查线索 |
| --- | --- | --- |
| scale | skill | 技能、SOP、可复用经验、Codex/Claude Code skill 语境 |
| AG / A G / 艾基 | agent | 智能体、工具调用、多 agent 协作语境 |
| promote | prompt | 提示词、system prompt、prompt engineering 语境 |
| cloud / Cloud Code | Claude / Claude Code | Anthropic、Claude Code、coding agent 语境 |
| 拆 GPT / chat g p t / chat gbt | ChatGPT | OpenAI 聊天模型语境 |
| long chain | LangChain | Agent 框架、LangGraph 并列出现 |
| long graph | LangGraph | Agent 框架、graph/node/pipeline 语境 |
| m c b / m c p | MCP | Model Context Protocol、工具协议语境 |
| c l i / seal eye | CLI | 命令行、bash、shell、GitHub CLI 语境 |
| cash / cache / case | cache / KV cache | prompt caching、上下文缓存语境 |
| Laura / lower / 老二 | LoRA | 个性化模型、热插拔、低秩适配语境 |
| tail scale / tile scale | Tailscale | 组网、exit node、远程访问语境 |
| next s / net x | Next.js | Web 框架类比语境 |
| transformer 被译成“变形金刚” | Transformer | 模型架构、attention 语境 |
| token 被译成“口令/令牌” | token | 上下文长度、计费、token efficiency 语境 |
| embedding 被译成“嵌入”但上下文断裂 | embedding | 向量、检索、RAG 语境 |
| vector 被译成“维克多/向量”混乱 | vector | 向量搜索、数据库、RAG 语境 |
| RAG 被译成“rag/瑞格/拉格” | RAG | 检索增强生成语境 |
| SOTA 被译成“索塔/苏打” | SOTA | state-of-the-art、模型能力比较语境 |

## 本地补充

每期播客可在 `source/extraction-notes.md` 追加本期专属修正，例如嘉宾姓名、公司名、产品名、开源项目名。跨多期反复出现的修正，再考虑加入本表。
