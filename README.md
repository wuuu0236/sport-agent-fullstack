# sport-agent-fullstack

个人体育训练助理的**全栈多智能体**版本。在原有 Python 零依赖 MVP（`sport-agent-mvp`）基础上，  
升级为产品级混合栈：**Spring Boot 做网关层，Python(FastAPI) 做 Agent 能力微服务（含主-从多 Agent 编排），Vue 做前端**。

> 设计核心：**分级响应**——健身域问题统一由谭成义人格教练单 Agent 直答（多数请求单次调用完成），  
> 多源汇合任务（周报 / 阶段总结 / 数据驱动计划）才升级多 Agent 编排：主 Agent（Supervisor）把任务拆解后显式派发给  
> 各子 Agent 隔离执行，只回收摘要。**「拆解是模型的判断，派发/验收是代码的门控」**，  
> 杜绝模型答跑偏还把结果硬塞给用户。

> 📌 **文档导航**：本文件只讲**当前状态**（架构 / 功能 / 快速开始 / 验证）。按时间倒序的**完整版本迭代记录**见 [CHANGELOG.md](CHANGELOG.md)，文末「更新记录」一节给出最近版本摘要。面试讲法与追问应答见 `面试要点.md`。

## 项目亮点（为什么值得讲）

1. **Claude Code 式主-从多 Agent 协作（分级触发 + LangGraph 编排）**——健身域问题统一由谭成义人格教练单 Agent 直答；  
   多专长协作任务才升级编排（由 `src/intent.py` 的 **LLM 结构化分类**判定，关键词规则仅作 mock/失败兜底）：主 Agent 用 LLM 把任务拆成结构化子任务（强 JSON schema，**拆几步、派给谁、写不写 @**、子 Agent 白名单校验），  
   再经**依赖校验**（`@sN` 漏引自动补、无效引用清除）后逐节点**代码门控派发**，只回收产出摘要（截断防超长），最后由主 Agent 亲自综合收口。  
   整个主循环是 **LangGraph StateGraph**（plan → validate → dispatch ⇄ → review → rewrite → synthesize），条件边表达分支而不是散落的 if。  
   记录解析 / 数据计算类子 Agent（recorder / analyst）全程为确定性代码、不调 LLM；康复知识库（clinician）以确定性知识库为主体，真实模式下仍会调一次 LLM 把知识组织成回复。  
   协作全程通过 **SSE 实时推送**到前端看板：拆解了哪几步、谁在跑、谁失败、谁产出，全部**肉眼可见**。
2. **子 Agent 独立工作空间**——写库子 Agent（recorder）解析结果先进**暂存区**，主循环结束发 `pending_commit`  
   事件，前端确认后才 `/commit` 落库。图片导入同样先暂存（顺带修复「导入即入库」的 P0-3 回归）。  
   暂存区落 **SQLite（WAL）**：**服务重启后待确认记录仍在**（此前是进程内 list，重启即清零），并发保护也不再依赖手写锁。  
   落库失败时**不清暂存**（返回 `ok:false + kept:true`，前端保留待确认卡片可重试）：写盘失败会抛 `IOError`，  
   且出队发生在落库**成功之后**——不会出现「没进磁盘、也不再待确认」的无声数据丢失。  
   确认侧再做**原子抢占**（`staged → committing`，只有 UPDATE 影响行数为 1 的调用者才有资格落库）：  
   两个请求同时点确认时，同一条记录只会写进训练库一次；抢占用 120s 租期兜底，抢占方崩溃不会让记录永久卡死。
3. **失败门控 + 评审三层**——子 Agent 空返回/空串兜底文案（哨兵）→ 判该节点失败（`agent_error`）、跳过继续，  
   绝不把模型废话当产出喂给下一步；综合阶段空/异常自动降级为「如实汇总各节点真实产出」。  
   收口前还有一道`reviewer`复核：**规则检查先行**（机械缺陷直接判不过，不花 token）+ **结构化清单逐项判定** + **可换模型评审**，未消化的意见附进最终产出。  
   **评审不可用 ≠ 评审通过**：评审模型降级或评审节点异常会置 `review_unavailable`，成品末尾如实标注「本轮未完成质量评审」——  
   旧实现把这种情况静默读成通过，评审服务一挂质量门就等于不存在。
4. **依赖链 `@s1` 引用**——LLM 拆解时若判断某步需要前序结果，在 input 里写 `@s2`，执行时代码替换成  
   前序节点真实产出（截断 400 字），子 Agent 成果在代码层串起来，不靠模型"记得"。
5. **本地隐私优先**——训练截图走**本地 OCR**，图片永不离开本机，解析后先暂存、确认后结构化落库。
6. **可演进架构**——Java 网关层**改为薄转发**，把 8001 的 SSE 事件流原样透传前端；  
   Agent 能力全部收敛在 `agent-service/src`（Python），换引擎/加 Agent 不动前端契约。
7. **优雅降级**——无 LLM key 时自动 mock，三服务依旧跑通；LLM 拆解失败回退代码模板计划，永不空转。


## 多 Agent 协作机制（主-从分发）

```
两条发送路径（都由用户在输入框触发）：
  A) 普通发送 → 前端 useAgentChat.send() → POST /api/chat（一次性返回）
     后端若判定需编排，会随响应带回 events[]，前端按 90ms 逐条回放成协作时间轴（非 SSE）
  B) 手动点「多 Agent 编排」→ orchestrateNow() → EventSource 订阅 /api/orchestrate(SSE)
     ——真正的 SSE 实时推送只在这条路径上

  走不走编排由后端 src/intent.py 的 LLM 分类决定（与前端选哪条发送路径无关）
  ↓ Java 网关 :8080 —— Orchestrator 薄转发：POST 8001/supervise?stream=1，读帧重组后透传
  ↓ Python 主 Agent :8001 —— LangGraph StateGraph（src/graph.py）
      start → plan(LLM 拆解→JSON steps；失败→按任务类型分档的代码兜底)
           → validate(依赖校验：@sN 漏引自动补、无效引用清除)
           → dispatch ⇄ dispatch（逐节点：替换@s1→调子Agent→空/哨兵判失败→agent_done|agent_error）
           → review(规则检查先短路 → 放行后一次带结构化清单的 LLM 评审；配 REVIEW_MODEL 则换模型做这次评审) ──ISSUES 且被评节点是 planner──→ rewrite(仅重写一次) → synthesize
           → synthesize(单步/最后成功步是 planner 且产出**可交付**（非空、非哨兵、非降级文案）才直接用；否则主 Agent 亲自 LLM 综合)
           → complete(output, final) → 若有暂存 → pending_commit(count, records)
  ↓ 子 Agent 独立执行 —— 上下文隔离（技能按主理 Agent 门控注入 `match_skills_for`：未声明 owner 全开放 / 同名才注入 / coach 例外吸收 clinician、expert；无对话历史 / 记忆按需召回 Top5；
     planner 例外：强制全量注入用户画像，防伤病限制被语义召回漏掉），只交产出字符串
  ↓ 数据层 —— recorder 解析 → 暂存队列（SQLite，WAL）→ 前端「确认入库」→ /commit（原子抢占）→ 落库
```

**子 Agent 名录**（`agent-service/src/agents/`），按实现方式分两类：

- **执行型（确定性代码，全程不调 LLM）**：`recorder`(正则解析训练描述→暂存)、  
  `analyst`(心率区间/TRIMP/渐进趋势计算)；
- **知识库型（确定性知识 + 一次 LLM 组织回复）**：`clinician`(疼痛排查/康复动作知识库 + 就医红线)——  
  核心是确定性知识库（覆盖膝盖 / 下背 / 圆肩 / 足底 4 个部位），真实模式下调 LLM 把命中的知识组织成自然语言；
- **生成型（LLM + 受控注入）**：`searcher`(联网搜索 + 诚实降级)、`expert`(知识问答 + 用户基线注入)、  
  `planner`(周报/计划综合，强制全量注入用户画像)、`memory`(长期记忆)、`scheduler`(日程提醒)、  
  `writer`(文案写作)、`general`(兜底)；
- 另有 `reviewer`(评审 Agent，PASS/ISSUES 协议) 供编排收口前复核——**评审三层加固**：
  ① 规则检查（`review_rules.py`，纯代码）把空产出/空串哨兵/降级文本/过短直接判不过，省掉一次 LLM 调用；
  ② 评审按**五维结构化清单**逐项给出 `[OK]`/`[NG]`，而不是开放式"看看行不行"；
  ③ 配 `REVIEW_MODEL` 可让评审走**另一套模型**（消除同模型自评的盲区共享与自我偏好），
  未配置则回退同模型并在事件里如实标注 `reviewer_model`。非 planner 步骤的评审意见不再丢弃，会传给综合节点供修正或标注；  
  评审不可用（降级/异常）**单独置位 `review_unavailable`**，不混同「通过」——重写失败时评审意见也必须继续传到综合层，  
  否则用户拿到的是「已知有问题」的成品却毫无提示。
  **`coach`(谭成义人格教练) 是独立入口而非别名**——健身域问题统一由它单 Agent 直答。
  **人格显式分两层**：① *基础人格层* `CoachAgent.PERSONA_CORE`（身份 / 核心原则 / 动作铁律 / 表达风格 / 边界声明），**只接受人工改代码**——`存技能` / `patch 技能` 只落盘 `skills/`，没有任何代码路径能回写它，所以模型自进化改不跑偏人格；② *补充知识层* = `skills/` 下归属 coach 的 SKILL.md，运行时按触发词注入（对话路径经基类 Tier 3，结构化路径的「补一句建议」经 `_tip`）。**边界要说清**：跑步/力量解析、心率区间数值、TRIMP 全是 `sport_data.py` 的确定性计算、不消费技能——知识层改的是**判读口径**，不是 `ZONES` 里的数值边界。**人格数据的来源与验证口径**：谭成义人格由 2026-08-23 一次联网调研蒸馏而成（`谭成义健身视角.md`，附录列来源清单）——数据是该博主的**公开文字材料**（公众号/头条对视频口播的逐句整理、B站/抖音视频的文字形态、粉丝体系整理），未下载视频、未做 ASR，故文中金句均为可搜索回溯的原话引用，二手材料置信度中等，已在文档「诚实边界」章节如实声明；人格蒸馏无法对本人验证，正确性靠"来源可溯 + 引用可查 + 结构自检（每条模型带证据/局限）+ 产品边界（声明非本人）"四层兜底。
- 保留旧别名：`research`→searcher、`posture`→clinician、`memorist`→memory。
- 编排触发：`src/intent.py` 的 LLM 分类判定「单 Agent 直答 / 数据操作 / 多 Agent 编排」——需要「查资料 + 算数据 + 出成品」两件以上、跨期对比、或要周报/阶段总结/排期计划成品时才编排；记录类与健身域问答不进图（分类失败或 mock 模式退回原关键词规则，宁可少拆一次也不误升级）。

## 技术栈（混合栈）

| 层         | 技术                                                                          |
| --------- | --------------------------------------------------------------------------- |
| 前端        | Vue 3 + Vite（设计令牌体系 · **深/浅双主题** + 4 模块工作台 + 自研 SVG 图表 + SSE EventSource；多 Agent 协作走内联时间轴） |
| 网关        | Spring Boot 3（薄转发：/api/chat、/api/import-image、/api/orchestrate、/api/commit、/api/health） |
| Agent 能力层 | Python + FastAPI 微服务 + **LangGraph StateGraph** 编排（plan → validate → dispatch → review → rewrite → synthesize）：10 个可派发子 Agent，另有 `reviewer` 评审节点与 `coach` 直答入口 |
| 记忆        | **SQLite 唯一真源（WAL 并发）** + 双存储（关于用户 / 助理笔记）+ **jieba + FTS5 混合召回** + 冻结快照注入；Markdown 仅作只读视图；画像面板支持**按稳定 id 逐条删除**（`POST /memory/forget` body {"id":N}，精确删，内容有包含关系的条目不会误删）+ Skill 三级渐进加载                 |
| 数据引擎      | SportStore 确定性计算：周聚合 / 周环比（缺口如实标注）/ 日负荷 / ACWR 急慢性负荷比（伤病风险）                 |
| LLM       | DeepSeek `deepseek-chat`（OpenAI 兼容接口，无 key 自动 mock 降级）                     |


## 目录结构

```
sport-agent-fullstack/
├── backend/            # Spring Boot (Java) —— 网关/薄转发层
│   ├── pom.xml
│   └── src/main/java/com/sportagent/
│       ├── SportAgentApplication.java
│       ├── controller/ChatController.java   # /api/chat /api/import-image /api/commit /api/orchestrate(SSE) /api/health
│       └── orchestrator/Orchestrator.java   # SSE 薄转发：POST 8001/supervise?stream=1 → 读帧 → 透传前端
├── agent-service/      # Python Agent 微服务（编排大脑）
│   ├── app.py          # FastAPI: /chat /supervise(JSON 或 ?stream=1 SSE) /commit /import-image /agent/{name} /route /plan(|/plans) /plan/* /memory /sessions /health
│   ├── requirements.txt / requirements-dev.txt / requirements-ocr.txt
│   ├── .env            # 含 LLM_API_KEY（已被根目录 .gitignore 排除，切勿提交）
│   ├── data/           # 记忆与训练记录（自动生成）；暂存队列在 staged.db（SQLite，抗重启）
│   ├── tests/          # pytest 274 条：解析 / 意图(LLM分类+规则兜底) / 编排图 / 评审规则 / 分析 / 计划(质量门+产出类型) / 技能 / 人格分层 / 存储 / 记忆删除接口 / 检索 / 暂存 / 落库防线 / 截图导入 / LLM 调用层 / 编排上下文 / HTTP 鉴权
│   ├── skills/         # 4 个可插拔教练技能（SKILL.md，按触发词动态挂载）——即 coach 的「补充知识层」
│   ├── .venv/          # 项目专属虚拟环境（LangGraph 依赖，不入库）
│   ├── _dump_prompt.py # 诊断工具：打印任意输入真正发给 LLM 的完整提示词（4 层拼装结果，排障/自查用）
│   └── src/
│       ├── graph.py             # LangGraph StateGraph 编排图：plan→validate→dispatch⇄→review→(rewrite)→synthesize
│       ├── review_rules.py      # 评审第一层：规则检查（空/哨兵/降级/过短直接判不过，疑点提示不裁决）
│       ├── intent.py            # 意图分类：LLM 结构化输出为主，原关键词规则 _needs_orchestration 为兜底
│       ├── orchestrator.py      # SupervisorAgent 门面（对外契约 run(task, emit) 不变，内部委托 graph）
│       ├── supervisor.py        # 单 Agent 关键词路由（健身域统一归 coach 直答）
│       ├── sport_data.py        # SportStore：暂存队列（SQLite+WAL，抗重启）+ 周聚合/环比/日负荷/ACWR 确定性计算
│       ├── plan_store.py        # 计划库：pending 两段确认 / 切换 / 删除
│       ├── skill_loader.py      # Skill 三级渐进加载 + 蒸馏 / patch（注册表版本号驱动目录缓存热更新）
│       ├── memory.py            # 双存储记忆：SQLite 唯一真源 + WAL + jieba/FTS5 混合召回（向量侧可选）
│       └── agents/              # 10 个可派发子 Agent + reviewer + coach + 注册表 agent_catalog
│           ├── recorder_agent.py / analyst_agent.py / research_agent.py（类名 SearcherAgent）
│           ├── posture_agent.py（类名 ClinicianAgent）/ expert_agent.py / planner_agent.py
│           ├── memory_agent.py / scheduler_agent.py / writer_agent.py / general_agent.py
│           ├── coach_agent.py      # 谭成义人格教练：健身域唯一直答入口；PERSONA_CORE 人格层（不可自进化）+ skills/ 知识层
│           ├── reviewer_agent.py   # 评审：PASS / ISSUES 协议（主循环内部节点，不参与 LLM 拆解）
│           └── base.py         # BaseAgent._llm：空串注入哨兵兜底文案（供门控识别）
├── frontend/           # Vue 3 + Vite（设计令牌 + 组件分层）
│   ├── package.json / vite.config.ts / index.html   # index.html：首屏按明暗偏好上色 + 品牌 favicon
│   ├── public/favicon.ico          # 品牌图标（渐变底+哑铃，7 档尺寸），同时被桌面快捷方式复用
│   ├── scripts/gen-favicon.py      # 图标生成脚本（纯标准库 struct/zlib，不需要 Pillow；重跑可逐字节复现）
│   └── src/
│       ├── App.vue / AppWorkbench.vue   # 工作台外壳：导轨导航 + 模块切换（Transition + KeepAlive）
│       ├── styles/          # tokens.css（设计令牌，含深/浅双主题）/ base.css（reset+动效）/ prose.css（Markdown 排版）
│       ├── utils/           # wallpaper（壁纸预设灰白4+深色4 / 明暗偏好持久化）/ markdown / image（压缩上传）/ session
│       ├── components/
│       │   ├── ui/          # AppCard / StatTile / AppButton / AppPill / SectionTitle / EmptyState / SkeletonBlock / StatusDot
│       │   ├── charts/      # LineChart（渐变面积+平滑曲线+悬停提示）/ ZoneBar（心率区间）/ types.ts
│       │   ├── chat/        # SessionList / ChatHeader / MessageBubble / ThinkingTrace（多 Agent 时间轴）/ ChatComposer / ProfilePanel / PendingCommitCard / DropOverlay
│       │   └── ThemeSettings.vue   # 外观抽屉：界面明暗 + 灰白/深色壁纸分组 + 自定义上传
│       ├── composables/     # useSessions（多会话持久化）/ useAgentChat（发送/编排/导入/确认/画像）
│       ├── constants/agents.ts     # 子 Agent 中文名 + 职责 + 图标 + 色相
│       ├── views/           # Chat / DashboardView / PlanView / MemoryView
│       └── api/client.ts    # chat / health / importImage / orchestrate(EventSource) / commitRecords / plan / memory
├── start-all.bat       # 一键启动三服务（各自独立窗口；项目根由 %~dp0 自推导，可移到任意位置/多副本共存；启动前清空代理变量防 TLS 被本机代理掐断；顶部内置 JDK/Node/Python 路径，运行时升级后需同步改）
├── AGENTS.md           # 项目规则：沟通语言 / 改动约束 / 测试要求 / 版本迭代
├── _token_check.py     # 诊断工具：子 Agent 上下文体量对照（全量记忆+20轮历史 vs 按需召回+关历史，打桩不触网）
├── docker-compose.yml  # 三服务编排（见下方「Docker 部署」说明，当前需补 Dockerfile）
├── .gitignore          # 排除 .env 密钥 / 构建产物 / 运行时数据
├── 架构方案.md         # 完整架构、接口契约、演进路线
├── 谭成义健身视角.md   # 教练人格蒸馏来源（2026-08-23 联网调研：公开文字材料蒸馏，来源清单与诚实边界见其附录）
├── 谭成义减脂三分化计划.md   # 应用篇：基于视角.md 的 5 心智模型推导出的具体排期（非蒸馏来源）
└── 面试要点.md         # 面试讲法与追问应答
```


## 快速开始（开发模式，三服务分别启动）

> 前置：JDK 17+、Maven 3.9+、Node 22+、Python 3.13
>
> 本机已就绪路径（供参考）：JDK17 `C:/Users/24162/tools/jdk17/jdk-17.0.20+8`、  
> Maven `C:/Users/24162/tools/maven/apache-maven-3.9.9`、Node/Python 用 WorkBuddy 托管运行时。

**1. agent-service（端口 8001）**

> 2026-09-16 起编排层用 LangGraph，agent-service **不再依赖全局环境**，走项目专属 venv。

```bash
cd agent-service
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
.venv/Scripts/python -m uvicorn app:app --port 8001 --host 127.0.0.1
```

**2. backend（端口 8080，需 JDK17 + Maven）**

```bash
cd backend
mvn clean package -DskipTests
java -jar target/sport-agent-backend-0.1.0.jar --server.port=8080
```

> ⚠️ 本机环境（WorkBuddy 后台进程）会无视 `application.properties` 里的 `server.port`、  
> 把端口随机化成 5xxxx。务必在命令行**显式加 `--server.port=8080`**，否则前端代理连不上。  
> （已确认不是配置写错：jar 内 `BOOT-INF/classes/application.properties` 确实写了 8080，  
> 但仍被环境覆盖成随机端口，CLI 参数优先级最高，可强制锁回 8080。）

**3. frontend（端口 5173）**

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 **<http://localhost:5173>** （注意用 `localhost` 而非 `127.0.0.1`：  
Vite 默认绑 IPv6 `[::1]`，IPv4 的 127.0.0.1 连不上）。消息经 Vite 的 `/api` 代理  
（见 `vite.config.ts`）到 Spring Boot(8080) → agent-service(8001)。

## 一键启动（可选）

项目根目录提供 `start-all.bat`，一次性拉起三个服务到各自独立窗口（JDK17 / Node / Python 路径已内置在脚本顶部，但**本机运行时版本会升级**——若某个窗口报"找不到命令/path"，按实际安装目录改脚本第 7 / 8 / 14 行的路径即可，例如 2026-11 实测 Node 从 `22.22.2-2` 升级到了 `22.22.2-6`）：

```bat
start-all.bat
```

> 前提：`backend\target\sport-agent-backend-0.1.0.jar` 已构建——若 backend 窗口报找不到 jar，  
> 请先按上方「快速开始 · 步骤 2」执行 `mvn clean package -DskipTests`。  
> 注意：脚本直接 `java -jar`，若 8080 已被占用会启动失败，先释放端口再跑。
>
> 项目根目录由脚本自身位置推导（`set BASE=%~dp0`）：**整个文件夹搬到别处、或同时存在多份副本时，双击哪份就启动哪份**。  
> 早期版本写死绝对路径，副本双击会静默启动**原目录**的服务，表现为「改了没生效」，排查成本很高。

## 安全（2026-09 加固）

- **服务鉴权**：`agent-service/.env` 里 `AGENT_AUTH_TOKEN` 非空时，除 `/health` 外所有接口要求  
  请求头 `X-Agent-Token` 匹配（FastAPI 中间件）。防三类威胁：浏览器恶意网页打本机接口、  
  DNS rebinding、容器化后裸奔局域网。留空 = 关闭（纯本机开发默认）。
- **启用方法（三处同步）**：`agent-service/.env`、`backend/src/main/resources/application.properties`  
  的 `agent.service.token`、`frontend/vite.config.ts` 的 `X-Agent-Token`。Spring 侧改完需  
  `mvn clean package -DskipTests` 重新打包。
- **CORS**：旧版 `src/server.py`（休眠的 stdlib HTTP 入口）从 `*` 收紧为仅回显本机 Origin，并走同一 token 校验。
- **异常脱敏**：Agent 内部异常只记服务端日志，客户端拿通用文案；旧版 `.env` 上传限制等回归见 `CHANGELOG.md`。

## 测试（274 个用例，`pytest tests/` 全绿）

```bash
cd agent-service
.venv/Scripts/python -m pip install -r requirements-dev.txt   # pytest + httpx（venv 内）
.venv/Scripts/python -m pytest tests/ -q
```

`tests/` 下 19 个文件，覆盖十七层：

| 层 | 文件 | 覆盖内容 |
| --- | --- | --- |
| 解析 | `test_parsers.py` | 文件导入（GPX / CSV / OCR 规则兜底） |
| 意图 | `test_intent.py` | 目标检测、规则兜底判定、**LLM 分类（JSON 解析 / 垃圾输出回退 / 显式编排）**、coach 意图分流（「要点/技巧/怎么做」不被误判成查数据） |
| 编排图 | `test_graph.py` | **事件序列契约（前端/网关依赖）**、逐步派发与失败继续、`@sN` 依赖校验（补引 / 清无效引用）、评审三层接线（规则短路 / 意见传到综合）、评审重写只做一次、兜底模板分档、**评审不可用 ≠ 评审通过**（降级/异常置位 `review_unavailable` 并在成品上如实标注）、**重写失败不丢评审意见**、坏产出（空/哨兵/降级）不直出 |
| 评审 | `test_review_rules.py` | 规则层判据边界（只有空 / 哨兵 / 降级 / 过短判 blocking，缺段落与数字无出处**只提示不裁决**）、`format_issues` 与评审闸门协议一致 |
| 分析 | `test_analyze.py` | 心率区间 / 负荷 / 力量趋势 |
| 计划 | `test_plan_store.py` · `test_plan_guard.py` · `test_planner_prompt.py` | 流转与并发、写入点质量门（拦降级文本）、planner 产出类型（周报 vs 计划）、**`plans.json` 原子写**（临时文件 + `os.replace`，不留半个 JSON、不留 tmp） |
| 技能 | `test_skills.py` | 三级渐进加载 / 触发词去重 / 主理 Agent 门控 |
| 人格分层 | `test_coach_persona.py` | **人格层不被自进化写入**（patch 技能后 `PERSONA_CORE` 字节不变）、知识层在对话路径与结构化路径（补建议）都被注入、`存技能` 后目录缓存热更新 |
| 存储 | `test_memory.py` | 双存储读改写 + **WAL 并发（多线程 append 零丢失）** + 旧 Markdown/session.json 一次性迁移（幂等）+ 整套替换重建索引 + **`reset_long_term` 的「重置演示数据」语义**（长期记忆与会话历史一并清，与注释一致） |
| 暂存 | `test_staged_store.py` | **跨进程/跨重启耐用**（新连接仍读到暂存记录）、FIFO 顺序、按 `_staged_id` 精确清除、8 线程并发暂存零丢失、**并发确认不重复入库**（原子抢占 `staged → committing`，起跑线对齐的多线程确认每条只落一次）、抢占租期回收（抢占方崩溃不卡死）、旧库自动补列 |
| 截图导入 | `test_import_stage.py` | **截图导入闭环**：`staged_records` 必须带 `_staged_id`（前端要靠它精确确认，只给布尔量前端只能整队清空）、`_stage_import_data` 返回记录本体而非 bool、解析成功但无法入库时给出可读原因 |
| 落库防线 | `test_commit_guard.py` | **落库失败不许丢数据 + 并发不重复入库**：`/commit` 检查 `_import_save` 的返回值（它失败只标记、不抛异常），`_save` 失败抛 `IOError`，`commit_staged` **先落库成功才出队**、失败记录留在暂存可重试；带 records 的路径与空提交共用同一套**按 id 原子抢占**（staged→committing，rowcount==1 才落库），Barrier 双线程并发确认同一条只落库一次、抢不到的一方如实报 skipped，落库失败把抢占退回 staged |
| LLM 调用层 | `test_llm_timeout.py` | **timeout 透传**（拆解 15s / 综合 30s，打桩捕获实参 kwargs）、失败时异常类型与原因进服务端日志、面向用户的降级文案不变 |
| 编排上下文 | `test_session_context.py` | **编排中间产出写进 session**（拼成一条 `[编排过程]` 摘要，不挤占 50 条滚动窗口）、摘要能被 `session_turns` 读回注入 |
| 记忆接口 | `test_memory_api.py` | **画像逐条删除**（`POST /memory/forget`）：删掉要连 FTS 索引一起清（否则被删条目还会被召回注入上下文）、按 target 隔离（删 user 不动 memory）、删不存在的如实回 `ok:false`（**返回值式错误必须显式判**，否则界面会「显示删成功、条目还在」）、连点两次幂等；并用字符级子串语义钉住旧契约；**按稳定 id 精确删**（`/memory` 每条带主键，两条内容有包含关系的条目按 id 删长条、短条不受伤——旧子串匹配会删错） |
| 检索 | `test_memory_search.py` | **中文自然语言召回**（钉住旧实现「整句一个 token → 0 命中」的回归）、词/bigram 双索引、bm25 分列权重、向量侧降级与近重复合并 |
| HTTP | `test_http_auth.py` | 鉴权中间件 + 异常脱敏 |

LLM 调用不打真实 API（mock/打桩）。OCR 可选依赖见 `requirements-ocr.txt`。


## 当前已验证（端到端全通 ✅，最近复核 2026-09-20）

> 以下记录跨多次迭代累积：9/13 为旧流水线时期的双路径实测；9/16 起编排层迁 LangGraph、记忆/暂存迁 SQLite、评审三层加固、画像删除、records 原子抢占等改动见 [CHANGELOG.md](CHANGELOG.md) 与各轮回归测试（当前 274 passed）。**9/13 的秒数与事件条数对应旧实现，仅供历史参考，不代表当前版本的实测值。**

完整链路已实测跑通，三服务均 LISTENING（8001 / 8080 / 5173）：

**双路径实测（2026-09-13，旧流水线时期，真实 LLM，6/6）**
- ✅ coach 直答：「怎么练胸」6.2s /「我膝盖疼还能跑吗」4.8s（命中 `posture_relief`）
- ✅ supervisor 编排：「帮我生成周报」27.4s /「总结这周的训练情况」21.6s（`mode=orchestrated`，携带 13 / 11 条 SSE 事件）
- ✅ 边界不编排：「周报的格式是什么」「总结一下卧推要点」——谈论 ≠ 触发
- ✅ coach 修复对照：「深蹲有进步吗」「卧推怎么样」仍走力量分析（无记录时如实提示），分析路径未被改坏

**OCR 截图导入（2026-08-19 布局配对修复后）**
- ✅ 华为户外跑步小结截图：平均心率 149 / 平均配速 8'00" / 运动时长 47:22 / 距离 5.92km / 日期 全部正确解析入库
- ✅ 修复前「平均心率后接步数 → 心率为 0」的左右两列错位问题

**多 Agent 主-从编排（本次大改核心，全链路实测）**
- ✅ **`/supervise` JSON**：LLM 拆解 `[searcher, analyst, planner]`，planner 通过 `@s2` 依赖引用
  拿到 analyst 真实数据（5.0km / 心率区间 Z3 90% / TRIMP 23.7）生成周报，无兜底废话。
- ✅ **失败门控**：expert 节点空返回 → 被哨兵检测 → `agent_error`，searcher 真实结果照常交付；
  `_synthesize` 空返回自动降级为「各节点真实产出汇总」，绝不丢结果。
- ✅ **`/supervise?stream=1` SSE**：`start→plan→(agent_start/agent_done|agent_error)*→complete` 事件流逐帧推送。
- ✅ **Java 薄转发**：`GET /api/orchestrate` 把 Python 事件流原样透传前端，200 `text/event-stream` 正常。
- ✅ **工作空间隔离闭环**：「记录6公里/配速6分半/心率145」→ recorder 解析进**暂存区** → `pending_commit(count=1)`
  → `/commit` 落库 → analyst 立即读到新记录（6.0km/145）。
- ✅ **`/commit` 幂等**：暂存区为空时返回 `{"ok":false,"msg":"暂存区为空，无需提交"}`，不误报。

**既有链路（仍全通）**
- ✅ 前端 → 后端 → Python Agent 单 Agent 对话、图片导入（本地 OCR + 解析 + 先暂存后落库）、健康检查。
- ✅ 无 LLM key 时 mock 降级，三服务依旧跑通。

## 记忆持久化（2026-09-16 迁 SQLite ✅）

- **唯一真源 `data/memory.db`（SQLite + WAL）**：条目与会话都进库，并发保护交给 SQLite 的 WAL 模式，
  **不再需要手写文件锁**。`USER.md` / `MEMORY.md` 退化为「写入后同步的只读人读视图」——不再被读取，
  只为方便肉眼看内容。
- **一次性迁移**：首次建库自动导入旧的 `USER.md` / `MEMORY.md` / `session.json`（靠 meta 标记保证幂等，
  用户删空记忆后重启不会被旧文件灌回来）。实测迁移 7 条画像 + 50 条会话历史，原文件保持不动。
- **长期画像**：由「记住 / 记下 …」意图触发 `memory_agent` 调用 `remember()` 写入，跨会话常驻并注入
  各 Agent 的 system prompt（真实 LLM 模式下自动解析落地；mock 模式仅提示、不写盘）。
- **按需召回（2026-09-16 重写）**：`jieba` 分词 + `词/bigram` 双索引列 + FTS5 `bm25` 分列权重。
  配 `EMBED_API_KEY` 后叠加向量余弦相似度融合，并对相似度 > 0.9 的条目**更新而非新增**。
  - ⚠️ **旧实现的中文召回实际是坏的**：`[\w\u4e00-\u9fff]+` 里的 `\w` 本身就匹配 CJK，
    整句被当成**一个 token**，再拿整句去条目里找子串 → 独立复核 **5 条记忆 × 14 个真实问句 = 0/14 命中**；
    生产路径传入的还是合成 prompt，连子串退路也没有，`<memory-context>` 块**从不注入**。
    重写后在真实 7 条画像上：**旧 1/8 → 新 8/8**。
  - 中文 FTS5 的两个坑（实测）：内置 `unicode61` 对中文全 0 命中；`trigram` 只支持 ≥3 字符，
    2 字词（膝盖/心率/卧推/增肌）全失效。所以索引列必须自己喂切好的 token。
  - 未配 `EMBED_API_KEY` 是**默认正常状态**（DeepSeek 不提供 embedding），纯关键词召回照常工作。
- **训练记录展示**：`GET /sessions`（agent-service）返回最近训练；前端经 Vite 代理 `/agent/sessions` 拉取，
  供「训练数据」模块渲染图表（早期聊天页顶部的「最近训练」卡片已在 2026-08-20 重构时移除，避免与专属模块重复）。**训练记录本体**持久化在 `data/sessions/*.json`（与记忆库分开）。

## 诚实说明（尚未完成）
- Docker 部署仍不可用（缺 Dockerfile；需先补 `.dockerignore` 排除 .env 与 data/）
- 长期记忆仍需「记住/记下」触发 + 真实 key 才落盘（现写入 SQLite，不再是 USER.md）
- 向量召回需自备 `EMBED_API_KEY`（DeepSeek 无 embedding 接口），未配置时只有关键词召回，
  `膝盖`/`膝关节` 这类同义词字面不重合仍召不回
- 子 Agent 的语义质量（答非所问/数据编错）尚无自动化评测，靠主 Agent 综合阶段人工兜底
- 意图路由准确率尚未标注评测（计划：50 条真实消息跑混淆矩阵）


## 接口契约

```
前端 → POST /api/chat {message} → Spring Boot → POST http://localhost:8001/chat {message}
                                                              ↓
                                            {agent, output, metadata} → 原路返回前端
```

前端 → POST /api/import-image (multipart 图片) → Spring Boot → POST http://localhost:8001/import-image {image:base64, mime}
                                                              ↓
                              OCR 本地读字（不上传图片）→ LLM 解析 → 进暂存区（staged）→ 确认后 /commit 落库

**多 Agent 主-从编排（核心链路）**
```
前端 → GET /api/orchestrate?message=... → Spring Boot(Orchestrator 薄转发)
        → POST http://localhost:8001/supervise?stream=1 {message}
        → SupervisorAgent: start → plan(steps) → 逐节点 agent_start/agent_done|agent_error
          → complete(output, final) → [若暂存] pending_commit(count, records)
        → Java 逐帧透传 → 前端 EventSource 订阅 → 看板实时刷新 → complete 渲染最终输出
```

**暂存提交**
```
前端「确认入库」→ POST /api/commit → Spring Boot → POST http://localhost:8001/commit
        → commit_staged() 把暂存区记录整批落库 → {ok, msg, count}
```

**展示与画像管理（前端经 Vite `/agent` 代理直连 8001，不过 Spring Boot）**
```
GET /sessions?limit=N   → 最近训练（含心率区间/配速/负荷等结构化字段，供图表渲染）
GET /memory             → 长期记忆（USER 关于用户 / MEMORY 助理笔记；每条带稳定 id）
POST /memory/forget     → 删除一条长期记忆（对话页「用户画像」面板的逐条删除；
                          body {"id": N} 按主键精确删；旧契约 {target,text} 子串匹配仍兼容）
GET /plan               → 计划库（activeId / pending 待确认 / plans 列表）
POST /plan/apply | /plan/switch | /plan/delete | /plan/generate | /plan/discard
```

> ⚠️ **部署提示**：`/agent` 前缀的直连代理只存在于 Vite dev server。若日后把
> `dist/` 构建产物放到 Java 网关 / Nginx 后面，必须在网关补一条 `/agent` → 8001
> 的转发，否则画像删除、训练数据、计划等页面功能会静默失效。

agent-service 还提供：
- `POST /supervise`（JSON：返回 `{agent:"supervisor", output, events[]}`；`?stream=1` 走 SSE）
- `POST /commit`（`{}` 提交全部暂存；`{records:[...]}` 指定提交）
- `POST /agent/{name}` 按名调用单个 Agent（供编排层/调试）
- `POST /route` 仅做意图路由，返回 agent 名
- `GET /sessions` 最近训练记录

## Docker 部署（当前不可用，需补 Dockerfile）

`docker-compose.yml` 已写好三服务编排（依赖 `depends_on` + 端口映射），但各服务目录下**尚未提供 `Dockerfile`**，
因此 `docker compose up` 暂时跑不起来。开发阶段请按上方「快速开始」分别启动。
补齐 `agent-service/Dockerfile`、`backend/Dockerfile`、`frontend/Dockerfile` 后即可切换为容器部署。

## 更新记录（Changelog）

> 完整迭代脉络（每轮的动机 / 修法 / 验证）见 **[CHANGELOG.md](CHANGELOG.md)**。这里只列主干里程碑，倒序排列。
> 记录格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)：倒序 + 日期 + 变更分类；本项目按内部方案代号（P0/P1/P2）+ 测试用例数脉络组织。

| 日期 | 版本 / 主题 | 类型 | 测试数 |
|------|------------|------|--------|
| 2026-09-20 | records 直提路径补原子抢占 + 画像按稳定 id 精确删除 | `Fixed` `Security` | 265 → **274** |
| 2026-09-17 | 画像面板支持用户自主逐条删除（`POST /memory/forget`） | `Added` | 256 → 265 |
| 2026-09-17 | 正常提问不再被塞进固定模板（修意图兜底四处叠加问题） | `Fixed` | 250 → 256 |
| 2026-09-16 | 复查 6 项修复（截图导入闭环 / 评审门 / 原子抢占等） | `Fixed` `Security` | 223 → 250 |
| 2026-09-16 | 代码审查 9 项修复（静默失败专项） | `Fixed` | 197 → 223 |
| 2026-09-16 | 暂存队列迁 SQLite（WAL，重启不丢待确认记录） | `Changed` | 182 → 197 |
| 2026-09-16 | 教练人格分层 + 知识层自进化通道（P1-3） | `Added` | — |
| 2026-09-16 | 记忆迁 SQLite + jieba/FTS5 中文混合召回（P1-2） | `Changed` `Added` | — |
| 2026-09-16 | 评审三层加固（P1-1） | `Added` `Security` | — |
| 2026-09-16 | 编排层迁移 LangGraph StateGraph + LLM 意图分类（P0） | `Changed` `Added` | 第一轮大改 |
| 2026-08-13 | 多 Agent 体系重设：硬编码流水线 → 主-从分发 | `Changed` | 架构级重构 |
| 2026-08-12 之前 | Vue3 + Spring Boot 3 + Python FastAPI 全栈搭建 | `Added` | 项目起点 |

**测试数演进主线**：`104 → 127 → 147 → 168 → 182 → 197 → 223 → 250 → 256 → 265 → 274`（每一跳都对应上表某轮的新增回归用例）。

## 演进路线

1. 阶段 0（已完成）：三服务代码 + agent-service 跑通
2. 阶段 1（已完成并实测验证）：Claude Code 式主-从多 Agent 编排 + SSE 链路看板 + 暂存-确认数据隔离
3. 阶段 2：向量库替代关键词重叠（RAG 语义记忆）
4. 阶段 3：MySQL 持久化训练记录
5. 阶段 4：微信/企业微信真实接入（复用现有 /agent/{name} 契约）
6. 阶段 5：子 Agent 产出自动化评测（LLM-as-Judge），把「语义质量」也纳入门控
