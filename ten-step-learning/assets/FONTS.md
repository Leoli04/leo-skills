# assets/fonts-inline.css 的来源与许可

该文件是**生成物**，不是手写样式：内容为 Fraunces 与 Inter（仅 latin / latin-ext 子集，woff2）的
base64 内联 `@font-face`，约 151 KB。作用是让产物在**断网**环境下仍保留标题的衬线观感，
符合本 skill「零外链单文件」的硬约束。

| 字体 | 上游 | 许可 |
|---|---|---|
| Fraunces | https://github.com/undercasetype/Fraunces | SIL Open Font License 1.1 |
| Inter | https://github.com/rsms/inter | SIL Open Font License 1.1 |

两者均为 OFL 1.1，允许随软件再分发与嵌入；本仓库未对字体做字形修改，仅做子集化与 base64 内联。

重新生成（需能访问 fonts.googleapis.com 一次）：

```bash
node scripts/fetch-fonts.mjs --force
```

脚本按 URL 去重、合并字重区间，只保留 latin / latin-ext（中文由系统字体栈承担），
缓存目录 `.font-cache/` 已忽略、不入库。

**不用它也能跑**：不加 `render.py --fonts` 即不注入，字体回退 Georgia / 系统字体，功能与布局不受影响。
