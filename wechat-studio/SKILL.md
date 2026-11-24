---
name: wechat-studio
description: 跑公众号文章流水线（写作 → 人工审核 → 配图/卡片 → 排版 → 人工发布）。当用户要写公众号文章、做公众号配图、排版成可粘贴的公众号 HTML、把文章做成贴图卡片，或查询/重跑已有文章的某道工序时使用。触发词：公众号文章、写篇公众号、公众号排版、公众号配图、贴图、图片消息、wechat-studio。
agent_created: true
---

# wechat-studio —— 公众号文章流水线

## 项目位置

流水线本体（契约 `SPEC.md` + 编排脚本 `tools/` + 产物 `posts/`）在**独立工程目录**，不在技能目录内。路径一律由环境变量给出，本文件不写死任何本机绝对路径。

| 变量 | 指向 | 缺省 / 缺失时 |
|---|---|---|
| `WECHAT_STUDIO_DIR` | 流水线工程根（含 `SPEC.md`、`tools/`、`posts/`） | **无缺省，必须先设置**；未设置就停下来问用户 |
| `PYTHON` | 带 Pillow 的解释器（`inline_images.py` 用） | 依次退到 `~/.workbuddy/pyenv/shared/Scripts/python.exe`（公用 venv，见下）→ `python3` → `python`；全探不到就停下报错 |
| `SKILLS_DIR` | CodeBuddy 已装技能根目录（取别的技能的参考资料时才用） | `~/.workbuddy/skills`（Windows 为 `%USERPROFILE%\.workbuddy\skills`） |

```bash
# 会话开始先确认，三个都空就不要再往下走
echo "studio=${WECHAT_STUDIO_DIR:-<未设>} python=${PYTHON:-<默认>} skills=${SKILLS_DIR:-<默认>}"
```

```
$WECHAT_STUDIO_DIR/
├── SPEC.md                契约（单一事实来源，动手前必读）
├── tools/pipeline.js      工序编排 + 哈希幂等
├── tools/cdp.js           零依赖 CDP 浏览器驱动
├── tools/inline_images.py 图片 → base64 内联
├── tools/rename_images.js 出图后按契约重命名
└── posts/<slug>/          一篇文章一个目录
```

**第一件事：读 `$WECHAT_STUDIO_DIR/SPEC.md`。** 它是契约，本 skill 只是入口说明。契约与本文件冲突时以 SPEC 为准。

本 skill 自带写法细则，**按文体路由**（写作前先判，判错整篇都白做）：

| 文体 | 细则 | 触发 |
|---|---|---|
| 技术文档族 | `SPEC.md` 6.1 | 技术拆解 / 工程实践 / 源码解析 / 架构说明 / API·字段文档 / 故障复盘 |
| 叙事观点族 | `references/voice-narrative.md` + `SPEC.md` 6.2 | 观点 / 职业 / 行业观察 / 个人经验 |
| 其余 | `SPEC.md` §6 映射表默认 | — |

## 已定型的项目设置

| 项 | 值 |
|---|---|
| 作者署名 `author` | **Leo** |
| 签名句（文末「我是 ＿＿，＿＿ 。」） | **一个努力让生活变得更美的人** |
| 发布方式 | 人工：复制 → 粘贴 → 群发（不接 API） |
| 默认主题 | 红白色系（`red-white`），用于观点 / 深度分析 |

这些是**长期资产，不要每篇重问**；用户明确要改才改。

## 新会话启动（用户只丢一句话时）

新会话没有上下文，用户的第一句通常只有「用公众号流水线写篇关于 XX 的文章」。**动手前先补齐三件事**：

1. **形式 `format`**：`rich`（图文长文）还是 `image`（贴图卡片）。用户没说就默认 `rich`，但要告知「同一篇可以再派生一套贴图版去小红书 / 朋友圈」。
2. **话题 → 标题**：用户给的永远是**话题**，不是标题。标题必须另出 2–4 个候选，附推荐与各自代价，让他拍板。
3. **文体 `article_type`**：它同时决定写法与排版主题（见上面的路由表）。判定为**叙事观点族**时，写作前必须先要三样料：一件亲耳听到的事、一个你不同意的说法、一个自造的类比。**拿不到就停下问，不许自己补**——补出来的不是亲历感，是伪造的事实主张。

然后：

```bash
cd "$WECHAT_STUDIO_DIR"
node tools/pipeline.js init <slug> --format rich
```

`slug` 用英文 kebab-case 意译标题，**一次定死**——它是标识符不是标题，后面改标题不动它。

写作产出 `article.md` → `stamp <slug> 01-write` → **加载 `humanizer` 技能做去AI味**（重写草稿、`stamp <slug> 02-deai`）→ **⛔ 停下**，等用户明确说「审核过了」才往下走。这一步绝不抢跑：下游 AI 出图烧积分，且配图会回写 `article.md`，位点绑死当时的文本结构。

## 铁律（踩过坑的，别绕）

1. **形式（图文 / 贴图）在写作之前定**，写进 `meta.json` 的 `format`。形式会改变写法——先写通用稿再改形式，等于让那次人工审核白做。唯一例外：不改变写法的派生版（同一篇文章再切一套贴图版）可以后置。
2. **两个人工审核门，别跳过，也别抢跑**：去AI味（工序 2）之后必须停下等用户审。图文支线是**硬门**（下游 AI 出图烧积分），贴图支线是**柔门**（下游渲染免费）。**没有用户明确说「审核过了」，不要往下跑配图。**
3. **幂等 = 哈希幂等**，不是「文件存在即跳过」。每道工序跑完立刻 `stamp`。用户改了源文件后，下游会自动标 `stale`——不重跑就可能发出旧文本。
4. **但 `stale` ≠「必须重跑」，要按该工序的真实依赖判定。** 哈希是文件级、故意粗粒度的（宁可多报）。`03-illustrate` 判 `stale` 时先看变更性质：**动了段落 / 章节 → 必须重跑；只改了 frontmatter、署名、错别字 → 位点未变，直接 `stamp` 认领，不要重跑**（一次误重跑 = 15–30 积分）。判据一句话：**看 `imgs/*.png` 有没有变。** 反过来 `04-layout` 必须真重跑——作者名 / 签名在排版产物里是正文的一部分（引言卡署名 + 文末签名区）。题外：`article.md` 的 `title` **不进正文 HTML**（只在发布时填进后台），所以单改标题不用重跑排版。
5. **排版工序只准机械转换**（标点全角化、`<span leaf>` 包裹、Markdown → 组件），**不准改措辞**。改了就破坏了「用户审过的 = 发出去的」。
6. **卡片 / 摘要 / 金句一律用 HTML → PNG 渲染，不用图像模型。** 图像模型承载中文长文本必然糊；渲染确定性、秒级、零积分。AI 生成图只用于不含中文长文本的视觉装饰。
7. **AI 插图里的中文标签控制在 2–5 个词**。这是出图一次全对的关键，长句是中文渲染出错的主要来源。
8. **禁止用代码修补位图上的文字**（OCR 覆盖/擦除）。文字错就换 prompt 重新生成。
9. 凭证不进仓库。本项目不接公众号 API，发布是**人工**：复制 → 粘贴 → 群发。
10. **去 AI 味和加人味是两件事，方向相反。** `02-deai`（humanizer）只做减法，删套话、拆长句；叙事观点族要的人味必须由 `01 写作` 供给（材料 + `references/voice-narrative.md` 的八条约束）。指望去味把一篇 AI 稿变成亲历叙事，只会得到"干净但没有人的"文字——这是本流水线最容易误判的一道工序。

## 工序与命令

```bash
cd "$WECHAT_STUDIO_DIR"

node tools/pipeline.js init   <slug> --format rich|image
node tools/pipeline.js status <slug>          # 查全部工序状态
node tools/pipeline.js check  <slug> <id>     # exit 0=可跳过 1=需重跑
node tools/pipeline.js stamp  <slug> <id>     # 跑完后立刻记哈希
```

| 槽位 | `format: rich`（图文） | `format: image`（贴图） |
|---|---|---|
| 1 写作 | `article.md` | `cards/src/NN-{slug}.md` |
| 2 去AI味 | `02-deai`（humanizer 重写） | `02-deai`（同左） |
| — 审核 | **硬门**（去味后审） | **柔门**（去味后审） |
| 3 载体填充 | `03-illustrate` AI 插图 | `03-visual` 卡片元素 |
| 4 终态渲染 | `04-layout` 行内样式 HTML | `04-render` HTML → PNG |
| 5 交付 | `05-clipboard` 预览壳 | `05-publish` 素材清单 |
| — 发布 | 人工粘贴 | 人工发图片消息 |

渲染与内联的具体命令见 `SPEC.md` 第 8 节。

## 各工序要点

**01 写作**
- rich：`##` 分章，首段 `>` 引用块作引言卡，图片写相对路径 `imgs/NN-{type}-{slug}.png`
- **叙事观点族反着来**：不写 `##`、不写引言卡、纯段落流（30–35 段），见 `SPEC.md` 6.2。缺这些信号时**不许为了套红白骨架去造章节标题**——那会让工序 4 从「机械转换」越界成「改内容」
- image：一片一文件 `NN` 两位递增，frontmatter 带 `kind`，**单张卡片正文 ≤60 字**，每片只承载一个信息点
- **三种文字别混，寿命不同**：`title`（一篇一个，在信息流里被扫一眼）/ `description`（一篇一个，≤120 字，转发卡片用）/ 文末签名（**长期不变，是签名不是文章简介**，当前值见上文「已定型的项目设置」）
- **用户给的是话题，不是标题。** 标题必须由 agent 另出候选，附推荐 + 取舍理由，别把话题直接当标题用。
- **标题开头走「概念路线」还是「金句路线」，是取舍不是对错——给用户两条路的代价让他拍板，别替默认。** ① 自造概念开头：读者不认识，会消耗首屏最值钱的几个字；但如果这个词要做成账号的**长期概念标签 / 系列**，前置就是对的（资产靠重复累积）；② 直接搬文章最有冲击力的那句话。（首篇《通胀式努力》用户选 ①：前半句立概念、后半句「越努力，越不值钱」给冲突）
- **签名句式的硬约束**：它嵌在「我是 ＿＿，＿＿ 。」里 → 第二个空**只能是身份型或主张型**；栏目型（「在这里写点什么」）语法上填不进去，必须拆成独立一句。选签名时优先"长期成立"，避开只有当前这篇才成立的措辞。

**02 去AI味（写作后、审核前，AI 自审第二道）**
- 加载 `humanizer` 技能，按其四层自检（L1 硬性规则 / L2 风格 / L3 内容 / L4 活人感）定向改写 `article.md` / `cards/src/*.md`
- 禁词表：`$SKILLS_DIR/unclecheng-reduce-ai-perception-v2/references/banned-words.md`（该技能未装则跳过此表，只按 humanizer 自带规则；别把路径当硬依赖）
- 只动措辞标点，不增删事实、不改章节结构、不动图片位点（位点一变会误触发下游重跑）
- 改完 `stamp <slug> 02-deai`，随后停硬门等用户审
- 人工改动后本工序会判 `stale`，**预期内，不重跑**——直接 `stamp` 认领，人工措辞是最终文本
- 叙事观点族补一道体检：`node tools/voice_lint.js posts/<slug>/article.md`。它查 5 类可判定病灶（开场铺垫 / 元叙述句 / 发卷子 / 二分收尾 / 动作密度），**只报 warning 不阻断**，逐条给段号与命中句。**解释得通就留**——机器不懂语境，判定权在人和审核门

**03 载体填充**
- 三维法：`type` × `style` × `palette`；**隐喻要画它背后的概念，不画字面图像**
- 每张图**先落盘 prompt** 到 `imgs/prompts/`，再调生成后端（换后端不用重写 prompt）
- rich：生成图显示宽度 ≤677px，**回写 `article.md` 的图片引用**

**04 终态渲染**
- rich：复用 gzh-design 排版引擎，跑校验脚本要求 **0 ERROR / 0 WARNING**，再做 base64 内联（内联前**必须先缩到 1354px**，否则 HTML 涨到 8MB）
- image：渲染宽度 **1080px**（不是 677）；长图**分段**，单张 PNG **≤1MB**，否则微信二次压缩糊小字；输出 PNG 不用 JPEG

## 交付

最终产物用 present_files 给用户：
- rich：`article.预览.html`（带「复制到公众号」按钮）+ 配图 + 排版验证截图
- image：渲染好的卡片 PNG（按编号顺序）

交付时必须一并说明：**积分消耗**（AI 出图每张约 5–10 积分；若因 `stale` 判定而跳过重跑，要说明「省下了几张图」）、**是否还有未替换的占位符**（署名已定型，通常为零，新增字段要检查）、以及下一步的人工操作。

## 环境注意

以下是与具体机器无关的老坑，另有两条与解释器 / 依赖有关，按变量走：

- bash shim 的 PATH 可能损坏（`ls`/`head`/`dirname` 等 command not found），PowerShell stdout 也可能不被捕获 → 取输出用「重定向到文件再 Read」或 `node -e`。
- Chrome 会回收由 CDP 新建的标签页 → `cdp.js` 已改为复用常驻页；后台窗口截图需先 `bringToFront`。
- `inline_images.py` 依赖 **Pillow**。`$PYTHON` 必须指向装了这个库的解释器，**跑前先探活**，别等脚本半路失败：

```bash
"${PYTHON:-python3}" -c "import PIL, sys; print(PIL.__version__, sys.executable)" || \
  echo "缺 Pillow 或解释器不对：用 PYTHON=<带 Pillow 的 python> 覆盖"
```

- 需要长期固定解释器时，写进用户级环境变量（PowerShell：`setx PYTHON "<venv 里的 python.exe>"`），**不要写回本文件**。

### 公用 Python 环境（跨技能复用，不动系统解释器）

约定位置：`~/.workbuddy/pyenv/shared`（Windows 即 `%USERPROFILE%\.workbuddy\pyenv\shared`）。**只往这个 venv 装包，绝不用 `pip install` 装进系统 / 开发用解释器。**

```bash
# 用 WorkBuddy 自带运行时建 venv（基解释器只被读取，不被写入）
"<WorkBuddy>/binaries/python/versions/<ver>/python.exe" -m venv ~/.workbuddy/pyenv/shared

# 装依赖只落在 venv 内
~/.workbuddy/pyenv/shared/Scripts/python.exe -m pip install --index-url https://pypi.org/simple Pillow
```

- **重建**：删掉整个 `~/.workbuddy/pyenv/shared` 重跑上面两条即可，无状态、可复制。
- **验证隔离**：`<基解释器> -c "import PIL"` 必须报 `ModuleNotFoundError`；报得出来说明装错地方了。
- ⚠️ **pip 镜像坑**：本机全局 `pip config` 把 `index-url` 指向清华镜像，走代理时它不通，pip 只吐一句 `Could not find a version that satisfies the requirement ... (from versions: none)`，看着像包不存在，其实是网络。加 `--index-url https://pypi.org/simple` 就地覆盖，**不要去改全局 pip 配置**。
- 已验证组合：基解释器 3.13.x + `Pillow 13.0.0`（3.11 + Pillow 10.2.0 也跑得通，历史产物由它出）。
