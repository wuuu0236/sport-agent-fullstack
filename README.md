# sport-agent-fullstack

个人体育训练助理的**全栈多智能体**版本。在原有 Python 零依赖 MVP（`sport-agent-mvp`）基础上，  
升级为产品级混合栈：**Spring Boot 做网关层，Python(FastAPI) 做 Agent 能力微服务（含主-从多 Agent 编排），Vue 做前端**。

> 设计核心：**分级响应**——健身域问题统一由谭成义人格教练单 Agent 直答（多数请求单次调用完成），  
> 多源汇合任务（周报 / 阶段总结 / 数据驱动计划）才升级多 Agent 编排：主 Agent（Supervisor）把任务拆解后显式派发给  
> 各子 Agent 隔离执行，只回收摘要。**「拆解是模型的判断，派发/验收是代码的门控」**，  
> 杜绝模型答跑偏还把结果硬塞给用户。

## 项目亮点（为什么值得讲）

1. **Claude Code 式主-从多 Agent 协作（分级触发 + LangGraph 编排）**——健身域问题统一由谭成义人格教练单 Agent 直答；  
   多专长协作任务才升级编排（由 `src/intent.py` 的 **LLM 结构化分类**判定，关键词规则仅作 mock/失败兜底）：主 Agent 用 LLM 把任务拆成结构化子任务（强 JSON schema，**拆几步、派给谁、写不写 @**、子 Agent 白名单校验），  
   再经**依赖校验**（`@sN` 漏引自动补、无效引用清除）后逐节点**代码门控派发**，只回收产出摘要（截断防超长），最后由主 Agent 亲自综合收口。  
   整个主循环是 **LangGraph StateGraph**（plan → validate → dispatch ⇄ → review → rewrite → synthesize），条件边表达分支而不是散落的 if。  
   执行类子 Agent（记录解析 / 数据计算 / 康复知识库）以确定性代码为主，不依赖 LLM 自觉。  
   协作全程通过 **SSE 实时推送**到前端看板：拆解了哪几步、谁在跑、谁失败、谁产出，全部**肉眼可见**。
2. **子 Agent 独立工作空间**——写库子 Agent（recorder）解析结果先进**暂存区**，主循环结束发 `pending_commit`  
   事件，前端确认后才 `/commit` 落库。图片导入同样先暂存（顺带修复「导入即入库」的 P0-3 回归）。
3. **失败门控**——子 Agent 空返回/空串兜底文案（哨兵）→ 判该节点失败（`agent_error`）、跳过继续，  
   绝不把模型废话当产出喂给下一步；综合阶段空/异常自动降级为「如实汇总各节点真实产出」。
4. **依赖链 `@s1` 引用**——LLM 拆解时若判断某步需要前序结果，在 input 里写 `@s2`，执行时代码替换成  
   前序节点真实产出（截断 400 字），子 Agent 成果在代码层串起来，不靠模型"记得"。
5. **本地隐私优先**——训练截图走**本地 OCR**，图片永不离开本机，解析后先暂存、确认后结构化落库。
6. **可演进架构**——Java 网关层**改为薄转发**，把 8001 的 SSE 事件流原样透传前端；  
   Agent 能力全部收敛在 `agent-service/src`（Python），换引擎/加 Agent 不动前端契约。
7. **优雅降级**——无 LLM key 时自动 mock，三服务依旧跑通；LLM 拆解失败回退代码模板计划，永不空转。


## 多 Agent 协作机制（主-从分发）

```
你点发送
  ↓ 前端 Chat.vue —— 判断走编排 → EventSource 订阅 /api/orchestrate(SSE)
  ↓ Java 网关 :8080 —— Orchestrator 薄转发：POST 8001/supervise?stream=1，读帧透传
  ↓ Python 主 Agent :8001 —— LangGraph StateGraph（src/graph.py）
      start → plan(LLM 拆解→JSON steps；失败→按任务类型分档的代码兜底)
           → validate(依赖校验：@sN 漏引自动补、无效引用清除)
           → dispatch ⇄ dispatch（逐节点：替换@s1→调子Agent→空/哨兵判失败→agent_done|agent_error）
           → review(PASS/ISSUES) ──ISSUES 且被评节点是 planner──→ rewrite(仅重写一次) → synthesize
           → synthesize(单步直接用；最后成功步是 planner 用其产出；否则主 Agent 亲自 LLM 综合)
           → complete(output, final) → 若有暂存 → pending_commit(count, records)
  ↓ 子 Agent 独立执行 —— 上下文隔离（技能按主理 Agent 门控注入 `match_skills_for`：未声明 owner 全开放 / 同名才注入 / coach 例外吸收 clinician、expert；无对话历史 / 记忆按需召回 Top5；
     planner 例外：强制全量注入用户画像，防伤病限制被语义召回漏掉），只交产出字符串
  ↓ 数据层 —— recorder 解析 → 暂存队列 _STAGED → 前端「确认入库」→ /commit → 落库
```

**子 Agent 名录**（`agent-service/src/agents/`），按实现方式分两类：

- **执行型（确定性代码，不依赖 LLM 自觉）**：`recorder`(正则解析训练描述→暂存)、  
  `analyst`(心率区间/TRIMP/渐进趋势计算)、`clinician`(疼痛排查/康复动作知识库 + 就医红线)；
- **生成型（LLM + 受控注入）**：`searcher`(联网搜索 + 诚实降级)、`expert`(知识问答 + 用户基线注入)、  
  `planner`(周报/计划综合，强制全量注入用户画像)、`memory`(长期记忆)、`scheduler`(日程提醒)、  
  `writer`(文案写作)、`general`(兜底)；
- 另有 `reviewer`(评审 Agent，PASS/ISSUES 协议) 供编排收口前复核；  
  **`coach`(谭成义人格教练) 是独立入口而非别名**——健身域问题统一由它单 Agent 直答。
- 保留旧别名：`research`→searcher、`posture`→clinician、`memorist`→memory。
- 编排触发：`src/intent.py` 的 LLM 分类判定「单 Agent 直答 / 数据操作 / 多 Agent 编排」——需要「查资料 + 算数据 + 出成品」两件以上、跨期对比、或要周报/阶段总结/排期计划成品时才编排；记录类与健身域问答不进图（分类失败或 mock 模式退回原关键词规则，宁可少拆一次也不误升级）。

## 技术栈（混合栈）

| 层         | 技术                                                                          |
| --------- | --------------------------------------------------------------------------- |
| 前端        | Vue 3 + Vite（设计令牌体系 · **深/浅双主题** + 4 模块工作台 + 自研 SVG 图表 + SSE EventSource；多 Agent 协作走内联时间轴） |
| 网关        | Spring Boot 3（薄转发：/api/chat、/api/import-image、/api/orchestrate、/api/commit） |
| Agent 能力层 | Python + FastAPI 微服务 + **LangGraph StateGraph** 编排（plan → validate → dispatch → review → rewrite → synthesize）：10 个可派发子 Agent，另有 `reviewer` 评审节点与 `coach` 直答入口 |
| 记忆        | 双存储 USER.md / MEMORY.md（冻结快照注入）+ Skill 三级渐进加载 + session 短期记忆                |
| 数据引擎      | SportStore 确定性计算：周聚合 / 周环比（缺口如实标注）/ 日负荷 / ACWR 急慢性负荷比（伤病风险）                 |
| LLM       | DeepSeek `deepseek-v4-flash`（OpenAI 兼容接口，无 key 自动 mock 降级）                  |


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
│   ├── data/           # 记忆与训练记录（自动生成）
│   ├── tests/          # pytest 127 条：解析 / 意图(LLM分类+规则兜底) / 编排图 / 分析 / 计划(质量门+产出类型) / 技能 / 存储 / HTTP 鉴权
│   ├── skills/         # 4 个可插拔教练技能（SKILL.md，按触发词动态挂载）
│   ├── .venv/          # 项目专属虚拟环境（LangGraph 依赖，不入库）
│   ├── _dump_prompt.py # 诊断工具：打印任意输入真正发给 LLM 的完整提示词（4 层拼装结果，排障/自查用）
│   └── src/
│       ├── graph.py             # LangGraph StateGraph 编排图：plan→validate→dispatch⇄→review→(rewrite)→synthesize
│       ├── intent.py            # 意图分类：LLM 结构化输出为主，原关键词规则 _needs_orchestration 为兜底
│       ├── orchestrator.py      # SupervisorAgent 门面（对外契约 run(task, emit) 不变，内部委托 graph）
│       ├── supervisor.py        # 单 Agent 关键词路由（健身域统一归 coach 直答）
│       ├── sport_data.py        # SportStore：暂存队列 _STAGED + 周聚合/环比/日负荷/ACWR 确定性计算
│       ├── plan_store.py        # 计划库：pending 两段确认 / 切换 / 删除
│       ├── skill_loader.py      # Skill 三级渐进加载 + 蒸馏 / patch
│       ├── memory.py            # 双存储记忆（文件锁并发保护）
│       └── agents/              # 10 个可派发子 Agent + reviewer + coach + 注册表 agent_catalog
│           ├── recorder_agent.py / analyst_agent.py / research_agent.py（类名 SearcherAgent）
│           ├── posture_agent.py（类名 ClinicianAgent）/ expert_agent.py / planner_agent.py
│           ├── memory_agent.py / scheduler_agent.py / writer_agent.py / general_agent.py
│           ├── coach_agent.py      # 谭成义人格教练：健身域唯一直答入口（内部再分流记录/分析/问答）
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
├── start-all.bat       # 一键启动三服务（各自独立窗口；项目根由 %~dp0 自推导，可移到任意位置/多副本共存；启动前清空代理变量，防 TLS 被本机代理掐断）
├── AGENTS.md           # 项目规则：沟通语言 / 改动约束 / 测试要求 / 版本迭代
├── _token_check.py     # 诊断工具：子 Agent 上下文体量对照（全量记忆+20轮历史 vs 按需召回+关历史，打桩不触网）
├── docker-compose.yml  # 三服务编排（见下方「Docker 部署」说明，当前需补 Dockerfile）
├── .gitignore          # 排除 .env 密钥 / 构建产物 / 运行时数据
├── 架构方案.md         # 完整架构、接口契约、演进路线
├── 谭成义健身视角.md / 谭成义减脂三分化计划.md   # 教练人格蒸馏来源（训练观 / 周期计划方法）
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

项目根目录提供 `start-all.bat`，一次性拉起三个服务到各自独立窗口（已内置 JDK17 / Node / Python 路径）：

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

## 测试（127 个用例，`pytest tests/` 全绿）

```bash
cd agent-service
.venv/Scripts/python -m pip install -r requirements-dev.txt   # pytest + httpx（venv 内）
.venv/Scripts/python -m pytest tests/ -q
```

`tests/` 下 10 个文件，覆盖八层：

| 层 | 文件 | 覆盖内容 |
| --- | --- | --- |
| 解析 | `test_parsers.py` | 文件导入（GPX / CSV / OCR 规则兜底） |
| 意图 | `test_intent.py` | 目标检测、规则兜底判定、**LLM 分类（JSON 解析 / 垃圾输出回退 / 显式编排）**、coach 意图分流（「要点/技巧/怎么做」不被误判成查数据） |
| 编排图 | `test_graph.py` | **事件序列契约（前端/网关依赖）**、逐步派发与失败继续、`@sN` 依赖校验（补引 / 清无效引用）、评审重写只做一次、兜底模板分档 |
| 分析 | `test_analyze.py` | 心率区间 / 负荷 / 力量趋势 |
| 计划 | `test_plan_store.py` · `test_plan_guard.py` · `test_planner_prompt.py` | 流转与并发、写入点质量门（拦降级文本）、planner 产出类型（周报 vs 计划） |
| 技能 | `test_skills.py` | 三级渐进加载 / 触发词去重 / 主理 Agent 门控 |
| 存储 | `test_memory.py` | 双存储读改写 + 文件锁并发（多线程 append 零丢失） |
| HTTP | `test_http_auth.py` | 鉴权中间件 + 异常脱敏 |

LLM 调用不打真实 API（mock/打桩）。OCR 可选依赖见 `requirements-ocr.txt`。


## 当前已验证（端到端全通 ✅，最近复核 2026-09-13/14）

完整链路已实测跑通，三服务均 LISTENING（8001 / 8080 / 5173）：

**双路径实测（2026-09-13，真实 LLM，6/6）**
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

## 记忆持久化（已修复并实测 ✅）

- **前端聊天持久化**：`Chat.vue` 聊天记录写入 `localStorage`，刷新/重开页面历史仍在。
- **后端短期会话记忆**：`/chat` 路由补上 `memory.append_session`，每次对话落盘 `data/session.json`；
  `BaseAgent._llm` 自动把最近 20 条会话注入上下文，多轮追问有记忆。
- **训练记录展示**：`GET /sessions`（agent-service）返回最近训练；前端经 Vite 代理 `/agent/sessions` 拉取，
  在聊天页顶部展示「最近训练」卡片。**训练记录本体**持久化在 `data/sessions/*.json`。
- **长期画像（USER.md / MEMORY.md）**：由「记住 / 记下 …」意图触发 `memory_agent` 调用 `remember()` 写入，
  跨会话常驻并注入各 Agent 的 system prompt（真实 LLM 模式下自动解析落地；mock 模式仅提示、不写盘）。

## 诚实说明（尚未完成）
- Docker 部署仍不可用（缺 Dockerfile；需先补 `.dockerignore` 排除 .env 与 data/）
- 长期记忆 USER.md 仍需「记住/记下」触发 + 真实 key 才落盘
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

**只读展示（前端经 Vite `/agent` 代理直连 8001，不过 Spring Boot）**
```
GET /sessions?limit=N   → 最近训练（含心率区间/配速/负荷等结构化字段，供图表渲染）
GET /memory             → 长期记忆（USER 关于用户 / MEMORY 助理笔记）
GET /plan               → 计划库（activeId / pending 待确认 / plans 列表）
POST /plan/apply | /plan/switch | /plan/delete | /plan/generate | /plan/discard
```

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

## 演进路线

1. 阶段 0（已完成）：三服务代码 + agent-service 跑通
2. 阶段 1（已完成并实测验证）：Claude Code 式主-从多 Agent 编排 + SSE 链路看板 + 暂存-确认数据隔离
3. 阶段 2：向量库替代关键词重叠（RAG 语义记忆）
4. 阶段 3：MySQL 持久化训练记录
5. 阶段 4：微信/企业微信真实接入（复用现有 /agent/{name} 契约）
6. 阶段 5：子 Agent 产出自动化评测（LLM-as-Judge），把「语义质量」也纳入门控
