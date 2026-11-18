# 开发计划

本计划供执行 agent 按任务领取。每个任务写明依赖、改动范围、验收标准，以及是否需要人工参与。背景与已有结论见 [README](../README.md) 和 [历史记录](history/)，尤其是 [三分钟版复盘](history/03-v3/全流程复盘与重制方案.md)、[《再等一班》编剧及导演稿](history/03-v3/再等一班-编剧及导演稿.md) 和 [三机位试拍](history/05-v5/咖啡馆资产与三机位试拍.md)。

## 现状

- 仓库只有文档与公开样例，没有可运行的制作代码。`examples/history/v3/` 下的脚本只用于复盘，不再沿用。
- 《再等一班》共 24 镜、约 180 秒。已有资产是林夏、周远的四视图，次日咖啡角的空场图，俯视机位图，以及 A（同框）、B（女方肩后看男方）、C（男方肩后看女方）三张机位参考。
- 上一轮卡点：B、C 机位图没能上传到 Flow，所以还没有基于新资产的动态镜头。现有 14 秒审片版来自旧原片的编辑与拼接。
- 三分钟审片版没通过的原因：动态画面只占 40%，角色没有同步对白，跨镜人物、服装和道具不一致。后续所有验收都要逐条对照这三项。

## 执行规则（所有 agent 遵守）

1. 一个任务一个分支、一个 PR，通过 merge commit 保留任务历史。PR 描述写明对应的任务编号。多 agent 并行须有用户明确授权。
2. 不提交原片、音频和生成中间件。素材放 `projects/<slug>/input|build|output/`，这几个目录已在 `.gitignore` 中忽略。仓库里只记录文件路径和 sha256。
3. 后续新增或修改的文件不超过 1 MB，示例图优先 JPG/WebP。现有归档 PNG/GIF 保留，修改时再压缩并更新引用。
4. `docs/history/` 是归档，不修改，只能新增阶段记录。
5. 审片是否通过由人决定。agent 可以准备材料、跑技术检查、写检查清单，但不能把镜头状态改成 `approved`，除非审片记录里有人工结论。
6. 已授权范围内的生成、上传、下载可由 agent 通过可用入口执行。新增费用、平台协议和真人授权按实际动作处理。用户负责最终视听审片。公开仓库不保存账号内链接或凭据。
7. 文档用中文。代码、文件名、字段名用英文。

## M0 待决定事项（人工）

下列事项由项目负责人决定。决定之前，agent 按“默认”执行，不要修改 README 的项目定位。

| 编号 | 问题 | 默认 | 影响 |
|---|---|---|---|
| D1 | 项目定位：给真实新人做的婚礼短视频，还是虚构微电影的方法验证 | 先做虚构《再等一班》验证方法，真实新人版放到 M5 | M5 是否启动，README 标题和简介 |
| D2 | 音频和原片怎么保存 | 继续忽略 `*.wav`、`*.mp3`、`*.mp4`。原片留在本地，清单记录 sha256。需要共享时用 GitHub Release 附件 | T2.1 的 `file` / `sha256` 字段，T2.5 的大文件检查 |
| D3 | `lin.jpg`、`zhou.jpg` 能不能认出最初 Pexels 参考图里的真人 | v5 四视图来自 v4 文本生成的虚构角色，v1–v3 曾用 Pexels 人物参考。先记录来源链与人工核对，再决定是否重做（T1.0） | M1 资产是否重做 |
| D4 | 主生成引擎 | 先用已有权限的 Flow，Grok 作可选对照。素材与分镜方法参考 Seedance 2.5；实际调用 Seedance 待用户另行选择 | T1.2 的候选来源 |

## M1 咖啡馆 15 秒场次审片通过

目标：用现有新资产生成 A→B→C→A 四个镜头，得到一条有同步对白的 15 秒审片版。镜头次序和台词沿用[三机位试拍](history/05-v5/咖啡馆资产与三机位试拍.md)中的“拍摄次序”，对应导演稿第 15–16 镜的精简版。

| 任务 | 内容 | 依赖 | 人工 |
|---|---|---|---|
| T1.1 生成提示词 | 在 `projects/zaideng/prompts/` 为四个镜头各写一份提示词，注明引用的资产、机位、动作分时、台词和说话人、闭口倾听的一方、环境声。Flow 版为主，按需提供 Grok 适配版；素材职责与分镜方法参考 Seedance 2.5。格式参考 [Seedance 2.5 提示词指南](https://docs.volcengine.com/docs/ark/seedance-2-5-prompt-guide?lang=zh) | T2.1 的目录约定 | 否 |
| T1.2 生成候选 | 用户或已获授权的 agent 在生成服务里上传资产、提交任务、下载原片，放到 `projects/zaideng/input/<shot>/`。先每镜 1 条，发现具体问题后按已确认预算补候选并记录淘汰原因 | T1.1 | 是 |
| T1.3 登记与粗剪 | 把候选登记进 `shots.yaml`，跑校验，用 `assemble.py --draft` 出粗剪，并写一份待审记录（逐镜列出时间点和需要审的问题） | T1.2，T2.2，T2.3 | 否 |
| T1.4 审片与补拍 | 用户开声、静音各审一轮，记录结论。不通过的镜头回到 T1.2 只补那一镜 | T1.3 | 是 |

验收：

- 开声：两句台词归属正确，口型对得上，说话时对方闭口倾听，音色在 B、C 之间保持一致。
- 静音：男左女右、窗左门右不变，视线方向符合机位图，杯子和车票的数量与位置连续，推杯的起点和落点前后一致。
- 技术：四个镜头都是动态画面，保留原声，FFmpeg 完整解码无报错。
- 交付：`output/` 下的审片版、`shots.yaml` 中的候选与选用记录、`reviews/` 下的审片记录，以及在 `docs/history/06-v6/` 新增的阶段记录。

## M2 仓库工具（可与 M1 并行）

全部用 Python 3.11+，依赖写进 `requirements.txt`（PyYAML、pytest）。外部依赖只有 FFmpeg。

### T2.1 项目目录与镜头清单格式

依赖：无。

新增 `projects/zaideng/`，结构如下：

```
projects/zaideng/
  project.yaml      # 入库：片名、分辨率、帧率、资产表
  shots.yaml        # 入库：场次与镜头
  prompts/          # 入库：每镜提示词
  reviews/          # 入库：审片记录
  input/ build/ output/   # 忽略：原片、中间件、成片
```

`project.yaml` 示例：

```yaml
slug: zaideng
title: 再等一班
fps: 24
resolution: 1920x1080
assets:
  lin:    {path: examples/cafe/assets/lin.jpg,    kind: character, version: 1}
  zhou:   {path: examples/cafe/assets/zhou.jpg,   kind: character, version: 1}
  cafe:   {path: examples/cafe/assets/cafe.jpg,   kind: set,       version: 1}
  shot-A: {path: examples/cafe/assets/shot-A.jpg, kind: framing,   version: 1}
  shot-B: {path: examples/cafe/assets/shot-B.jpg, kind: framing,   version: 1}
  shot-C: {path: examples/cafe/assets/shot-C.jpg, kind: framing,   version: 1}
```

`shots.yaml` 示例。镜号沿用导演稿的 01–24，同一镜拆出的机位加字母后缀：

```yaml
shots:
  - id: "15a"
    scene: 次日咖啡角
    camera: A
    target_duration: 2.0
    action: 周远推茶，林夏顺着杯子看过去
    dialogue: []
    refs: [lin, zhou, cafe, shot-A]
    kind: performance          # performance | insert（有叙事作用的图片短插入）
    status: candidate          # pending | candidate | approved
    candidates:
      - id: c1
        engine: flow-omni-1.2-flash
        file: input/15a/c1.mp4  # 相对项目目录，本地文件
        sha256: "<hex>"
        note: 杯子推过中线后位置跳变
    selected: null             # approved 时必填：{candidate: c1, in: 0.4, out: 2.5, audio: source}
  - id: "15b"
    camera: B
    dialogue:
      - {speaker: zhou, at: 0.3, end: 4.8, text: 昨天让你白等了。以后来不了，我先告诉你。}
    listener: lin
    # 其余字段同上
```

字段规则：

- `audio` 取值为 `source`（保留原声，默认）、`replace:<file>` 或 `mute`。选 `replace` 和 `mute` 时需要在 `note` 里写原因。
- `kind: insert` 的镜头可以用图片，但必须在 `note` 写清叙事作用，时长不超过 3 秒。
- `at` 是台词相对选用片段入点的秒数，增加 `end` 记录台词结束秒数。校验 `0 <= at < end <= out-in`；字幕加上该镜成片起始时间。

验收：写出完整 M1 四镜（15a–15d）的 `shots.yaml`，状态为 `pending`。

### T2.2 校验脚本 `tools/validate.py`

依赖：T2.1。

用法：`python tools/validate.py projects/zaideng [--check-media]`

检查项：

- 字段齐全、取值合法、镜号唯一。
- `refs` 引用的资产在 `project.yaml` 里存在，资产文件在仓库里存在。
- `approved` 镜头必须有 `selected`，`selected.candidate` 指向的候选存在，`in < out`。
- `performance` 镜头选用的候选必须是视频文件（`.mp4`、`.mov`）。
- 有台词的镜头必须写 `listener`（独白镜头写 `none`）。
- 加 `--check-media` 时，检查本地候选文件是否存在、sha256 是否一致。显式启用此参数时，缺选用文件、哈希不符都报错。CI 不加该参数，只校验清单。正式剪辑强制媒体检查，并核对裁切不超源时长，有对白且保留原声时必须有音轨。

验收：pytest 覆盖每条规则的通过和失败两种情况。

### T2.3 剪辑脚本 `tools/assemble.py`

依赖：T2.1。T2.2 可以并行，但 assemble 运行前要先调用校验。

用法：`python tools/assemble.py projects/zaideng [--draft] [--shots 15a-15d]`

行为：

- 按 `shots.yaml` 的顺序取镜头，按 `in`/`out` 裁切，统一到 `project.yaml` 的分辨率和帧率。默认按比例缩放加黑边，裁切须在选用记录中明确。不做时长填充（禁止 `tpad` 复制尾帧）。
- 默认保留源音轨。每个剪点的音频做 10 ms 淡入淡出，避免爆音。
- 正式模式下，任何选中范围内的镜头不是 `approved` 就报错退出。
- `--draft` 模式下，非 `approved` 镜头用其第一条候选；没有候选的镜头插入一张写着“缺镜 15b”的灰底提示卡，时长取 `target_duration`。提示卡必须明显，不能是内容静帧。
- 输出：
  - `build/edl.json`：每镜的源文件、入出点、在成片中的起止时间。
  - `build/subs.srt`：由 `dialogue`、`at`、`end` 与成片偏移生成。
  - `output/<slug>-<shots>-<YYYYMMDD>[-draft].mp4`：H.264 + AAC。
- 结束时跑 `ffprobe` 核对分辨率、帧率、时长，并用 `ffmpeg -v error -i <out> -f null -` 完整解码，有报错则退出码非零。

验收：pytest 用 FFmpeg `lavfi`（`testsrc2` + `sine`）生成几段带音频的测试片，覆盖正式模式拒绝未通过镜头、draft 模式插入提示卡、入出点裁切的时长误差不超过 1 帧、输出能完整解码。

### T2.4 审片记录模板

依赖：无。

新增 `docs/templates/review.md`，审片记录存到 `projects/<slug>/reviews/<YYYYMMDD>-<范围>.md`。模板包含：

- 审片对象（成片文件名、`edl.json` 对应的提交号）。
- 开声检查：台词归属、口型、停顿、倾听反应、音色连续、环境声是否服从画面。
- 静音检查：动作因果、视线、站位、道具状态、服装与脸的一致性。
- 逐镜结论表：镜号、结论（通过 / 补拍 / 换候选）、时间点、问题。
- 审片人（必须是人）。

### T2.5 CI

依赖：T2.2、T2.3。

新增 `.github/workflows/ci.yml`，在 push 和 PR 时运行：

1. Markdown 相对链接检查（新增 `tools/check_links.py`，忽略 http 链接）。
2. 对 `projects/*/` 逐个跑 `validate.py`（不加 `--check-media`）。
3. 大文件检查：PR 中新增或修改的文件超过 1 MB 则失败。
4. 安装 FFmpeg 后运行 pytest。

验收：在一个故意加入断链和 2 MB 文件的测试分支上 CI 失败，修正后通过。

## M3 60 秒段落：导演稿第 11–17 镜

依赖：M1 通过。目标：雨夜站厅等待（11–14）接次日咖啡角和好（15–17），约 53 秒，验证跨场连续。

| 任务 | 内容 | 人工 |
|---|---|---|
| T3.1 新资产 | 雨夜站厅空场、等候牌、两杯热饮道具；林夏、周远的雨夜服装版（沿用四视图格式）；更新 `project.yaml` 版本号 | 由用户或已授权 agent 生成，用户审片 |
| T3.2 镜头清单 | 把 11–17 镜按机位拆进 `shots.yaml`。15–16 镜按导演稿补回两张同车次的票和“你想什么时候走？” | 否 |
| T3.3 生成、粗剪、审片 | 流程同 T1.2–T1.4 | 是 |

验收：在 M1 验收项之外，增加跨场检查——雨夜到次日的人物、服装状态、音色一致；14→15 镜的雨声断开和白天切入干净；杯子、空椅、窗的衔接成立。

## M4 三分钟完整版

依赖：M3 通过。

| 任务 | 内容 | 人工 |
|---|---|---|
| T4.1 剩余场景资产 | 旧站台、当代站台、小画室、海岸、海边礼堂空场；童年林夏和童年周远参考；车票、信封、火漆等道具 | 由用户或已授权 agent 生成 |
| T4.2 全片镜头清单 | 01–24 镜全部写入 `shots.yaml`。童年段压缩为画本、纸飞机等短动作。第 18 镜沿用已认可的海边追信原片，先核对服装、信封和手位 | 否 |
| T4.3 逐场生成与补拍 | 按场推进，每场通过再进下一场 | 是 |
| T4.4 后期 | 对白、环境、拟音、音乐分轨混音；调色统一；字幕。先拍齐再定总长，不硬凑 180 秒 | 混音与调色的审美判断需人工 |
| T4.5 完整审片与试播 | 完整有声连播审片；在实际播放场地试播 | 是 |

验收：

- 对照三分钟版没通过的三项逐条核对：动态表演覆盖整条主线，图片只作 `insert` 短插入；关键场角色同步说话；跨镜人物、服装、道具一致。
- `validate.py` 正式模式通过，全部镜头 `approved`。
- 成片完整解码通过，现场试播无问题。

## M5 真实新人版（取决于 D1）

D1 决定启动后再细化。范围：

- 新人照片和素材的授权确认、隐私处理流程。素材只放 `projects/<slug>/input/`，不入库。
- 把《再等一班》验证过的场次结构做成可替换人物和故事的模板。

## 任务依赖一览

```
D1–D4（人工，可随时决定，未决定按默认）

T2.1 ─┬─ T2.2 ─┐
      ├─ T2.3 ─┼─ T2.5
      └─ T1.1  │
T2.4           │
T1.1 → T1.2(授权生成) → T1.3(需 T2.2、T2.3) → T1.4(人工) → M3 → M4
```

可以立即并行领取：T2.1、T2.4。T2.1 合入后可以并行：T2.2、T2.3、T1.1。
