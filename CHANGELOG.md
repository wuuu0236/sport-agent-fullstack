# 更新日志（迭代脉络）

> 本文件由 README 拆出（2026-09-15）：README 只保留项目介绍 / 功能 / 架构 / 快速开始等当前状态，
> 按时间的迭代记录统一放这里。

### 2026-09-14 planner 产出类型切换：修掉「要周报却给计划」
- **问题**：编排路径里要「周报」，产出标题却是「你的训练计划（修正版）」——**要周报给计划**。根因是一条链：`_fallback_plan` 把周报拆成 `searcher + analyst + planner` → `planner_agent` 的提示词**写死「生成一份训练计划」** → `_synthesize`「最后一步是 planner 就直接采用其产出」。更麻烦的是 `_critic` 的重写路径调的是同一个写死提示词，**评审就算正确指出「用户要的是周报」也救不回来**；
- **修法**（`f86fbaa`）：`planner_agent` 改为产出类型可切换——新增 `deliverable_of(task)` 判定 `WEEKLY` / `PLAN`，两套骨架各自独立（周报＝本期概览 / 数据解读 / 问题诊断 / 下周建议；计划骨架保持原样），`_build_plan_prompt` 更名 `_build_prompt(user_msg, kind)`；`orchestrator._dispatch` 与 `_critic` 都补传 `ctx["task"]`——否则被 `@s1`/`@s2` 拼进来的前序产出（含「计划」字样）会把周报带偏，重写路径更是完全取不到「周报」字样；
- 新增 `tests/test_planner_prompt.py` 10 条覆盖两个方向，测试 94 → **104 passed**。

### 2026-09-13 coach 意图分流修复：「要点/技巧/怎么做」不再被误判成查训练数据
- **问题**：`coach_agent._classify` 的兜底是「消息 ≤12 字 + 能抠出一个动作名 → 走力量趋势分析」，而「要点 / 技巧 / 怎么做」这组技术问法**不在任何白名单里** → 实测 4/4 误判：`总结一下卧推要点` 抠出动作名「总结」→ 回「『总结』还没记录过训练数据」；`卧推要点` / `深蹲技巧` / `引体向上怎么做` 同理；
- **对照组暴露根因**：`总结一下卧推的发力要点` 因带「发力」（属 training-advice 白名单）而侥幸走对 → **漏的是词表，不是兜底逻辑**。修法是把技术问法词并入「交给 LLM 直答」的词表，**不收紧兜底**（避免误伤既有行为）；
- 新增 `TestCoachClassify` 双向锁定：4 条修复用例须正常作答，同时 `深蹲有进步吗` / `卧推怎么样` 仍须走力量分析（回归保护）。测试 90 → **94**；
- 同批跑通**编排双路径实测 6/6**：coach 直答「怎么练胸」6.2s /「我膝盖疼还能跑吗」4.8s（命中 `posture_relief`）；编排「帮我生成周报」27.4s /「总结这周的训练情况」21.6s（均 `mode=orchestrated`，携带 13 / 11 条 SSE 事件）；边界「周报的格式是什么」「总结一下卧推要点」正确不编排。

### 2026-09-13 晚 导轨重做 + 品牌图标 + 启动脚本去硬编码
- **导轨重做**（`ef58412`）：四个模块入口（对话 / 数据 / 计划 / 记忆）原先是一小簇居中挤着的图标，改成**等分导轨高度的 110px 大卡片**——48px 模块色实心底座 + 26px 图标 + 中文标签；悬停先用模块色预告，选中态底色向 `#0b1220` 压深 28%~52%（青色 `#2ad4c8` 直填时白图标对比度只有约 1.7，压深后到约 4）。布局改 `justify-content: space-evenly` + 固定卡片高度——`flex:1` 撞上 `max-height` 后多余空间不会回流，靠它只会得到「中间一小簇 + 上下全空」；
- **品牌图标**（`6a37a4a` + `a5649b7`）：项目原先**连 favicon 都没有**，补 `frontend/public/favicon.ico`（圆角方形 `#3d8bff→#2ad4c8` 渐变底 + 白色哑铃，配色取自 `tokens.css` 的 `--accent`/`--accent-2`，整体压深保白图标对比度）。7 档尺寸 = 16/24/32/48/64/128 走 BMP + 256 走 PNG 压缩，共 106KB（全部用 BMP 是 372KB）；`index.html` 补 `icon` / `apple-touch-icon`；生成脚本 `frontend/scripts/gen-favicon.py` 一并入库（纯标准库，**已验证重跑输出与仓库版 sha256 逐字节一致**，不是不可复现的黑盒）；
- **启动脚本去硬编码**（`113d1d1`）：`start-all.bat` 原先写死绝对路径，复制到别处双击会静默启动**原目录**的服务（表现为「改了没生效」）；改为 `set BASE=%~dp0` 由脚本自身位置推导，多副本共存时双击哪份启动哪份。

### 2026-09-13 晚 灰白（浅色）主题 + 字号整体上调一档
- **浅色主题**（`093a870`）：`tokens.css` 新增 `:root[data-theme='light']` 整套令牌——层级逻辑由「越亮越高」翻转成「越白越高」（`surface-0` 最灰 → `surface-2` 纯白卡片），描边/内高光/投影/毛玻璃全部换成适配浅底的极淡灰晕，语义色与心率区间统一压深一档保白底对比度；兼容层里几个指向深色硬编码值的旧变量（`code-bg` / `pre-bg` / `pre-text` / `user-msg`）同步覆盖；
- **灰白壁纸四款**：云白 / 雾灰 / 米白 / 石墨。预设带 `theme` 字段，选浅色壁纸自动切换浅色令牌（否则白底叠深色面板会发脏），也可在外观抽屉里手动覆盖；自定义图片默认深色并给出提示；
- **字号整体 +2px**（正文 14→16、次要 13→15、辅助 12→14），新增 `--fs-2xs: 13px` 收编原先散落的 10 / 10.5 / 11 / 11.5px 硬编码微字号——22 处全部改为引用令牌，组件里不再有写死的字号；
- **外观抽屉**：新增「界面明暗」分段控件，背景按「灰白系 / 深色系」分组；`index.html` 首屏底色按已存偏好上色，避免加载瞬间闪成反色；
- **功能完整性核对**：13 个后端能力逐个确认仍有前端入口；被替换掉的旧组件（HeaderBar / MessageList / TrainingCharts / SessionSidebar / UserProfileSidebar）逐一比对，能力只增不减；
- 构建 166 模块，CSS 64.2 kB / JS 307.9 kB（gzip 11.7 / 123.5 kB）。

### 2026-09-13 计划写入点加质量门（修脏计划）
- **问题**：计划模块出现一份内容是「主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总：」的脏计划——降级文本一路被当成正常回答，最后由 `plan_store.set_pending` 直接落库；今天仍可达的同类入口还有 `_coach_answer` 用 try/except 吞掉异常后返回「教练生成建议时出错：…」；
- **修法**（`0f7d582`）：新增 `_PLAN_DEGRADED_MARKERS`，`_stage_plan` 作为唯一写入点先校验再落库（空内容或命中降级标记一律拒收）；`_coach_answer` 改为失败即抛异常，由调用方决定降级话术；三处调用点同步改造（chat 计划分支 / `/plan/generate` 失败回 503 不落库 / `_handle_goal_change`）；
- 新增 `tests/test_plan_guard.py` 16 条用例；pytest 74 → **90 passed**。

### 2026-09-07 晚 技能链路修复（蒸馏接线 / 编排注入 / 触发词去重 / 主理门控）
- **「存技能 / patch 技能」接线到线上入口**（`cda660d`）：元动作拦截原先只留在旧入口 server.py，全栈化后 app.py 未接，主路径下技能蒸馏等于死功能；
- **编排路径子 Agent 按步注入技能**（`bd02742`）：`_dispatch` 原先传 `skills:[]`，编排子 Agent 全裸跑；改为用原始任务匹配 + 主理 Agent 门控，编排 metadata 新增 `used_skills` / `skill_hits` 可观测；
- **触发词跨技能去重**（`b9ef3b3`）：「配速」同时挂在 run_log_parse 与 coach_hr_zones，多命中无仲裁互相串味；移除解析侧重复触发词；
- **主理 Agent 门控推广到单 Agent 路径**（`82d1b50`）：判定收敛为 `match_skills_for`，编排与单 Agent 共用；**coach 例外吸收 clinician / expert 技能**，防伤痛回答丢就医红线（回归测试 `test_coach_absorbs_clinician_skill` 锁死）；
- 测试 61 → **74**（新增 8 条技能回归）。

### 2026-09-07 伤痛提示词冲突修复 + 运维加固 + 仓库清理
- **修复提示词自相矛盾**：`coach._build_prompt` 曾把 focus 提取的词**无条件**拼进
  「请给一份具体的『XX训练日』」——问「我膝盖疼还能跑吗」会被引导去排"膝盖疼训练日"，
  与同时注入的 `posture_relief` SOP（定位诱因 → 康复动作 → 就医红线）正面冲突。
  根因是**意图分类与提示词构建用了两套判断**：抽出 `_PAIN_WORDS` + `_is_pain()` 共用同一份，
  伤痛命中时改走康复引导语。61 个测试全绿。
- **运维坑固化**：`start-all.bat` 启动前清空 `HTTP(S)_PROXY`——本机代理会让 Python 的
  urllib 到 api.deepseek.com 的 TLS 握手被掐断（`SSL: UNEXPECTED_EOF_WHILE_READING`），
  表现为 `/chat` 一律降级；且 curl 走同一代理是通的，极易误判。DeepSeek 为国内服务，直连即可。
- **仓库清理**：删除 9 个临时冒烟输出（`_smoke*.txt` / `_sup*.json` / `_uvicorn_smoke*.log`）
  与已完成使命的验证脚本（`_week_check.py`，注释即写"验证完即删"）；
  移除 `pom.xml` 中从未启用的 langgraph4j 注释依赖块。

### 2026-09-03 教练技能落地 + 运动科学数据引擎
- **skills/ 落地 4 个可插拔教练技能**（心率区间、久坐缓解、力量记录解析、跑步记录解析），
  skill_loader 按用户输入动态挂载——扩能力不改主流程代码；测试套件随本提交入库
- **SportStore 数据引擎**：周聚合（ISO 周，只列有记录的周）、周环比（缺口如实标注、不伪造插值）、
  日负荷、**ACWR 急慢性负荷比**（运动医学伤病风险指标；>14 天停练返回 stale，不把长休误判为减训）
- 修复空回复、带 × 号的力量记录解析、伤痛意图路由

### 2026-08-24 健身域统一路由：单 persona 直答
- 跑步/减脂/增肌/练部位/伤痛/计划等健身域问题统一路由至 coach（谭成义人格）单 Agent 直答；
  编排仅保留给周报等复杂任务——多数请求单次调用完成，响应速度与人设稳定性兼得

### 2026-09-02 安全与质量加固（面试导向的一轮硬化）
- **鉴权**：FastAPI 增加 `X-Agent-Token` 中间件（`AGENT_AUTH_TOKEN` 控制），Spring 拦截器透传、Vite 代理带头；旧版 server.py CORS `*` 收紧 + 同 token 校验。
- **并发**：`memory.py` / `plan_store.py` 文件读改写加锁（RLock 处理 apply_pending→active_plan 重入），16 线程并发 append 回归测试零丢失。
- **Bug**：修复意图管线顺序（记忆意图先于目标检测，「我想起来了你记得吗」不再被误判成目标变更）；修复 `_rule_parse_ocr` 力量行正则不认「组×次×kg」；Spring multipart 调到 10MB（默认 1MB 挡截图）；`Map.of` null NPE；SSE 编排异常静默截断补 error 事件。
- **质量**：新增 61 个 pytest 用例（解析/意图/分析/存储/HTTP 五层）；Java URL 与 token 移入 application.properties；新增 requirements-dev.txt / requirements-ocr.txt；面试讲法见根目录《面试要点.md》。

### 2026-09-13 前端 Vue3 重构第二版：设计系统 + 组件分层 + 交互提质

**设计系统（`src/styles/`）**
- 新增 `tokens.css`：把颜色/排版/圆角/阴影/动效全部收敛成令牌。质感三件套＝**分层表面**（`--surface-0..4`，靠明度差而非边框堆叠建立层级）、**发丝内高光**（`--hairline-top`，卡片顶部 1px 内阴影）、**大范围柔和投影**（`--shadow-1/2/3`，层级越高投影越大越散）；
- 新增 `base.css`（reset / 滚动条 / 焦点环 / 关键帧 / `prefers-reduced-motion`）与 `prose.css`（Markdown 富文本统一外观：表格做成内嵌卡片、代码块独立深底、标题带渐变锚点）；旧变量名保留兼容映射，未重构组件不破。

**组件分层（`src/components/`）**
- `ui/` 8 个基础件：AppCard（双层描边+内高光+语义色竖条）、StatTile（KPI 磁贴，右上柔光+渐变数字）、AppButton / AppPill / SectionTitle / EmptyState / SkeletonBlock / StatusDot；
- `charts/` 自研 SVG 升级：LineChart 支持**渐变面积填充 + Catmull-Rom 平滑曲线 + 悬停十字线与提示卡 + 描边入场动画**，坐标用 ResizeObserver 取像素（不再拉伸 viewBox，描边不变形）；ZoneBar 心率区间分段条 + 占比图例；
- `chat/` 8 个业务件：SessionList（排序/搜索/二步删除）、ChatHeader、MessageBubble（用户气泡 / 助理卡片 / 复制）、**ThinkingTrace 多 Agent 协作时间轴**（节点状态四态、进度条、失败自动展开产出）、ChatComposer（自动高度 / Enter 发送 / 粘贴截图）、ProfilePanel、PendingCommitCard（暂存确认）、DropOverlay；
- **逻辑抽离**：`composables/useSessions`（多会话+持久化）与 `useAgentChat`（发送/编排 SSE/导入/确认/画像），Chat 视图只做编排与布局；`constants/agents.ts` 沉淀子 Agent 中文名+职责+图标+色相。

**外壳与交互**
- 侧栏改为极窄毛玻璃导轨（品牌区+图标+滑动高亮+模块专属色），模块切换走 `Transition` + `KeepAlive`（切走再回来不丢会话状态）；
- 新增**氛围层**（模块色晕 + 遮罩网格），有壁纸时自动隐藏避免浑浊；外观面板改成右侧抽屉（预设色块 + 自定义上传预览 + 移除）。

**清理**：删除被替换的 9 个旧组件（MessageList / SessionSidebar / ChatInput / Dropzone / HeaderBar / SvgLineChart / TrainingCharts / RecentSessions / UserProfileSidebar）；构建产物 165 模块，CSS 60.4 kB / JS 304.9 kB（gzip 10.9 / 122.4 kB）。

### 2026-08-20 工作台模式 + 用户画像侧栏

- **工作台模式**：从单聊天页升级为多模块工作台——左侧小众线性 SVG 图标导航（对话 / 训练数据 / 记忆 / 外观），模块注册表式扩展（`AppWorkbench.vue`）；
- **训练数据模块**：6 张统计卡（跑步次数/总跑量/平均配速/平均心率/最大单次跑量/最近负荷）+ 心率区间/配速/跑量/TRIMP 趋势图表；
- **记忆模块**：USER（关于用户）/ MEMORY（助理笔记）双栏查看 + 注入快照预览（后端新增 `GET /memory`）；
- **用户画像侧栏**：主对话框右侧常驻展示 USER 长期记忆，对话后自动刷新；
- **全局放大**：图表尺寸、字号全面加大；聊天区移除"最近训练/训练数据"卡片（专属模块已有）。

### 2026-08-19 前端重构 + 暗色主题 + 会话管理 + 训练图表 + 多 Agent 会诊

**前端（Vue 3）**
- **组件化重构**：656 行单文件 `Chat.vue` 拆为 7 个组件（HeaderBar / MessageList / ChatInput / Dropzone / AgentBoard / RecentSessions / ThemeSettings）+ 工具模块（markdown / image / wallpaper / session）；
- **暗色主题 + 自定义壁纸**：全站颜色收敛为 CSS 变量（`styles/theme.css`）；右上角 🎨 设置弹窗可上传本地图片作全屏壁纸（canvas 压缩存 localStorage）或选 4 款预设渐变；
- **会话管理**：左侧会话栏（新建/切换/删除），每个会话独立持久化；首条消息自动命名会话；旧单会话历史自动迁移；
- **训练图表**：`/sessions` 接口增强返回结构化数据（配速/负荷/心率区间/动作明细），前端新增纯 SVG 折线图（配速/跑量/TRIMP 趋势）+ 心率区间 Z1-Z5 堆叠条；
- 按钮「生成周报（多 Agent）」改为通用「多 Agent 协作」。

**Agent 层（Python）**
- **伤病三 Agent 会诊**：`orchestrator.py` 新增 `_injury_plan()`——输入命中伤病/疼痛关键词时，固定走 `searcher（检索资料）→ analyst（训练数据诱因排查）→ clinician（分诊+危险信号强制就医）` 三 Agent 协作，`@s1/@s2` 依赖引用由代码替换，效果稳定可复现；
- `/sessions` 接口结构化增强（前端图表数据源）。

**数据层（Python）**
- `sport_data.py`：暂存队列加线程锁 + 每条记录唯一 `_staged_id`（按 id 精确清除，防并发误清他人暂存）；文件名时间戳加微秒（防同秒覆盖丢数据）；
- `app.py /commit`：带 records 时按 `_staged_id` 精确清除本次确认的暂存。

### 2026-08-19 OCR 布局配对修复：左右两列截图标签-数值错位 → 坐标空间配对

**问题**：华为/Keep 等训练截图是「左右两列」布局，旧 `ocr_image` 按行平铺拼接文本，
右列内容会插进左列标签与数值之间——实测「平均心率」后面直接接「步数」，
心率值 149 被挤到远处，规则/LLM 解析取不到数字，导入后心率为 0。

**修复**（`agent-service/src/ocr.py` + `src/server.py`）：
- OCR 识别块不再丢坐标：`_assemble()` 按块中心坐标做**空间配对**，
  标签 → 正下方（或同行右侧）最近的数值块，输出「平均心率: 149次/分钟」结构化文本；
- 单位词并入邻近数字块（`5.92 + 公里 → 5.92 公里`），避免数字与单位被拆两行；
- 配对距离公式给 x 偏差高权重，防孤立数字块抢配对（实测步频 88 vs 167步/分钟）；
- 顺带修 `_rule_parse_ocr`：配速/时长正则改**分步匹配**消除跨正则取组的 IndexError；
  时长解析优先取「运动时间: HH:MM:SS」，不再被状态栏时间（00:12:46）误抢。

**实测**（华为户外跑步小结截图，1080×2414）：平均心率 149 ✓ / 平均配速 8'00" ✓ /
运动时长 47:22 ✓ / 距离 5.92km ✓ / 日期 2026-05-31 ✓。


### 2026-08-13 多 Agent 体系重设：硬编码流水线 → Claude Code 式主-从分发（本次大改）

**机制层**（`agent-service/src/`）
- `orchestrator.py`（新增）：`SupervisorAgent` 主循环——`_plan` 用 LLM 拆解成强 JSON schema 子任务
  （失败/空回退代码模板计划）；`_dispatch` 显式逐节点派发（`@s1` 引用替换 + 截断 400 字）；
  `_synthesize` 主 Agent 亲自综合收口（单步直接用 / 最后成功步是 planner 用其产出 / 空则降级汇总）。
- `sport_data.py`：新增模块级**暂存队列** `_STAGED`，`stage_run` / `stage_strength` / `staged` /
  `commit_staged` / `discard_staged` —— 子 Agent 写库先隔离、确认后落库（工作空间隔离在数据层的落地）。
- `agents/base.py`：`_llm` 空串注入哨兵兜底文案，供主循环门控识别「模型未生成」。
- `agents/`（重设）：新增 `recorder_agent.py`（解析+暂存）、`analyst_agent.py`（心率区间/TRIMP）、
  `expert_agent.py`（知识问答）、`planner_agent.py`（周报/计划综合）；`research→searcher`、
  `posture→clinician` 改名并保留别名；`__init__.py` 重建注册表 `agent_catalog`。
- `app.py`：新增 `POST /supervise`（`stream=1` → SSE，否则 JSON events[]）、`POST /commit`；
  `/import-image` 改为**先暂存后确认**（修复导入即入库的 P0-3 回归）。

**网关层**（`backend/`）
- `Orchestrator.java`：由「编排大脑（research→coach→writer 流水线）」**改为 SSE 薄转发**——
  POST 8001 `/supervise?stream=1`，逐帧读 `data:` JSON 原样透传前端。
- `ChatController.java`：`/api/orchestrate`（GET SSE）对接新 Orchestrator；新增 `POST /api/commit`。

**前端层**（`frontend/`）
- `Chat.vue`：AgentChainBoard 动态化——`plan` 事件预填链条格子、`agent_start/done/error` 更新节点状态、
  `complete` 渲染最终输出、`pending_commit` 弹「确认入库」按钮调 `commitRecords`。
- `client.ts`：OrchestrateEvent 扩展 `plan | pending_commit` 类型与 `steps/count/records` 字段；新增 `commitRecords`。

### 2026-08-12 之前（Vue3 + Spring Boot 3 + Python FastAPI 全栈迭代）
- **SSE 实时推送**（Spring `SseEmitter` + 前端 `EventSource`）—— 多 Agent 编排过程可视化看板
- **前端 `localStorage` 持久化** —— 聊天记录刷新/重开不丢
- **真实 LLM 打通**（DeepSeek `deepseek-v4-flash`，OpenAI 兼容接口）
- **构建环境标准化** —— 补装 JDK17 + Maven（原机仅 Java 8，Spring Boot 跑不了）
- **教练概念问答修复**：意图分类器对 `z1~z5`/`区间` 概念问题改走 LLM 对话，不再硬塞训练记录
- **编排层容错**（旧流水线时代遗留）：每节点独立超时 + 退避重试 + 失败跳过继续 + writer 失败降级报告兜底
- **图片导入链路**：前端拖拽/点击/粘贴截图 → 本地 OCR + LLM 解析 →（现为先暂存后确认）

