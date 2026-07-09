---
name: image-workbench
description: "Use when a task needs AI-generated or AI-edited bitmap assets, visual QA of generated images, screenshot-backed image work, UI annotations, or the local image workbench CLI. Not for deterministic local edits such as crop, resize, or compress, and not for diagrams, charts, or images that must carry precise text or code — those belong in vector tools such as SVG/HTML, Typst, or Mermaid."
metadata:
  version: "3"
  short-description: gpt-image-2 generation, editing, repair, and visual QA of generated images
---

# Image Generation Workbench

用 `gpt-image-2` 做视觉整合和风格。精确的文字、规则术语、双语标签、代码、表格、测量和最终文档摆放，留在 Typst、HTML、slides 或宿主文档里，不进光栅图。参数的权威来源是 `profiles --json` 和每个子命令的 `--help`。

## 选方法

- 源状态、对象身份、UI 状态、卡面或截图内容要保真：附原图出首版，目视 PNG，再 `repair-image` 带 `--previous-response-id` 并重新附上原图。
- 保真首版按任务选命令。标注和教程叠加用 `annotate-image`，它不传 `--prompt` 时默认注入教程叠加模板。调亮、去元素这类非标注编辑，迭代用 `response-image`，一次性用 `image-edit`，硬要用 `annotate-image` 就必须传 `--prompt` 覆盖默认模板。
- 需要多轮迭代、多张输入图、或生成前先解读源图：走 Responses API，即 `annotate-image`、`repair-image`、`response-image`。打算迭代就用 `annotate-image` 或 `response-image` 起手，它们返回可链的 `response_id`，`repair-image` 靠 `--previous-response-id` 接上一轮。
- 只做一次性、确定不迭代的生成或编辑：走 Images API，即 `image-generate`、`image-edit`。它们不返回 `response_id`，`repair-image` 接不上，所以要迭代别拿它们起手。
- 可复用的 icon、token、贴纸、组件、绿幕素材：`image-generate` 或 `response-image` 生成在不透明或绿幕背景上，绿幕用 `--prompt assets/prompts/greenscreen-component.txt` 起手，抠图用 `chroma-alpha`，变体比较用 `contact-sheet`。从零生成带文字的 logo 或 wordmark 归矢量工具，无文字的图形 mark 可以走 `image-generate`。
- 从零生成又想延续风格时，把上一版 PNG 当 `--image` 喂给 `response-image`，作用和 source-backed 每轮重附源图一样，防止风格漂移。
- model 由 CLI 写死，图像生成用 `gpt-image-2`，`diagnose-image` 的解读用 reasoning model，都没有 model flag，实际值以输出 metadata 的 `image_model` 和 `reasoning_model` 字段为准。

## 纪律

CLI 管参数，管不了下面这些。

- 生成前先用一句话写清这张图要教什么。
- 保源不造字。别让模型渲染长段落或精确 UI 文案，别造源图里没有的 logo、水印、卡名、截图、人手或领域事实。标记少而准就够：spotlight、crop、dim、arrow、ring、编号点、callout。
- 目视 QA 是必须的，API 成功响应不算 QA。每次生成都自己看 PNG，拒绝裁切、扭曲源事实、看不清的标记、假文字或风格漂移的输出。需要结构化视觉证据时跑 `diagnose-image`，但把它的 `next_repair_issue` 当 `repair-image` 输入之前，先确认它和你看到的一致。
- `repair-image` 每轮只修一个具体 issue，并重新附上源图。`--previous-response-id` 保住对话状态，源图防止视觉漂移。
- 每个 CLI 调用都是独立的：`--previous-response-id` 携带的是 API 对话，不是 CLI 参数，所以每条生成命令都要自己带全 geometry 和 quality flag，必填项从 `<subcommand> --help` 拿。
- aspect ratio 在命令和 prompt 里都要写。别把竖屏或移动 UI 重构成横板，除非用户要求。

## CLI 契约

入口是 `scripts/image_workbench.py`，按这个 skill 目录的绝对路径解析。选参数前先跑发现命令：

```bash
SKILL_DIR=/absolute/path/to/image-workbench
uv run --script "$SKILL_DIR/scripts/image_workbench.py" profiles --json
uv run --script "$SKILL_DIR/scripts/image_workbench.py" <subcommand> --help
```

`profiles --json` 给推荐的参数 bundle，比如源图定稿用 `source-final`。`--help` 给每个子命令的必填和可选 flag。不要发明 flag：help 和 profiles 里没有的参数不要传。

- `--json` 供下游进程、脚本或 CI 消费。结构化 stdout 是 JSON metadata 或 profiles，stderr 是校验、鉴权和 API 错误。普通 stdout 只有输出路径和可选的 response ID。校验、鉴权、API 错误非零退出且 stdout 为空。
- `annotate-image`、`repair-image`、`diagnose-image`、`response-image`、`image-generate`、`image-edit` 会调 OpenAI API，是计费的远程操作。`contact-sheet`、`chroma-alpha` 和 reference `case.py` 只在本地跑，其中仅 source-backed-mobile-ui 的 case 提供 `--run-cli` 走真实 API。
- 凭据只走环境变量，别把 API key 写进 prompt、命令文件、日志、metadata 或提交的示例。从目标项目根目录跑，让输入输出保持项目相对路径。用过真实 API key 的工作收尾前，先跑仓库配置的 secret scanner，再扫一遍 key、token、secret、base URL 的常见泄漏形态。

一个完整的源图定稿回合，参数即 `source-final` bundle，其余子命令的 flag 同样从 `--help` 拿：

```bash
SKILL_DIR=/absolute/path/to/image-workbench
export OPENAI_API_KEY=...   # OpenAI-compatible 网关改用 PYDANTIC_AI_GATEWAY_API_KEY / _BASE_URL
uv run --script "$SKILL_DIR/scripts/image_workbench.py" annotate-image \
  --image path/to/source-screenshot.png \
  --aspect-policy match-input --quality high --output-format png \
  --detail high --background auto \
  --out outputs/visuals/figure.png --json
```

## 配套文件

`assets/prompts/` 的模板除绿幕模板外由子命令默认注入，只在改 prompt 文本或调试生成的 prompt 行为时读。`references/` 的两个 case 是改脚本后的回归检查，按任务干活不读。

## 改脚本后的收尾

改过 `scripts/image_workbench.py` 后，按 [`references/AGENTS.md`](references/AGENTS.md) 的清单收尾：编译、lint、类型检查、`--help` 冒烟和两个 case 的本地回归。
