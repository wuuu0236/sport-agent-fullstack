# sport-agent-fullstack

个人体育训练助理的**全栈多智能体**版本。在原有 Python 零依赖 MVP（`sport-agent-mvp`）基础上，
升级为产品级混合栈：**Spring Boot 做网关层，Python(FastAPI) 做 Agent 能力微服务（含主-从多 Agent 编排），Vue 做前端**。

> 设计核心：**分级响应**——健身域问题统一由谭成义人格教练单 Agent 直答（多数请求单次调用完成），
> 复杂任务（周报等）才升级多 Agent 编排：主 Agent（Supervisor）把任务拆解后显式派发给
> 各子 Agent 隔离执行，只回收摘要。**「拆解是模型的判断，派发/验收是代码的门控」**，
> 杜绝模型答跑偏还把结果硬塞给用户。

## 项目亮点（为什么值得讲）

1. **Claude Code 式主-从多 Agent 协作（分级触发）**——健身域问题统一由谭成义人格教练单 Agent 直答；
   复杂任务才升级编排：主 Agent 用 LLM 把任务拆成结构化子任务（强 JSON schema，≤6 步、子 Agent 白名单校验），
   逐节点**代码门控派发**，只回收产出摘要（截断防超长），最后由主 Agent 亲自综合收口。
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
  ↓ Python 主 Agent :8001 —— SupervisorAgent.run(task, emit)
      start → _plan(LLM 拆解→JSON steps；失败→代码模板兜底)
           → 逐节点: agent_start → _dispatch(替换@s1→调子Agent→空/哨兵判失败) → agent_done|agent_error
           → _synthesize(单步直接用；最后成功步是 planner 用其产出；否则主 Agent 亲自 LLM 综合)
           → complete(output, final) → 若有暂存 → pending_commit(count, records)
  ↓ 子 Agent 独立执行 —— 上下文剥离（无技能注入 / 无对话历史 / 记忆按需召回 Top5；
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
- 编排触发：仅周报等复杂任务升级编排（`_needs_orchestration`），日常请求不进主循环。

## 技术栈（混合栈）

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite（AgentChainBoard 动态看板 + SSE EventSource） |
| 网关 | Spring Boot 3（薄转发：/api/chat、/api/import-image、/api/orchestrate、/api/commit） |
| Agent 能力层 | Python + FastAPI 微服务：SupervisorAgent 主循环 + 10 个专业子 Agent |
| 记忆 | 双存储 USER.md / MEMORY.md（冻结快照注入）+ Skill 三级渐进加载 + session 短期记忆 |
| 数据引擎 | SportStore 确定性计算：周聚合 / 周环比（缺口如实标注）/ 日负荷 / ACWR 急慢性负荷比（伤病风险） |
| LLM | DeepSeek `deepseek-v4-flash`（OpenAI 兼容接口，无 key 自动 mock 降级） |

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
│   ├── app.py          # FastAPI: /chat /supervise(JSON+SSE) /commit /import-image /plan* /memory /sessions /agent/{name} /health
│   ├── requirements.txt / requirements-dev.txt / requirements-ocr.txt
│   ├── .env            # 含 LLM_API_KEY（已被根目录 .gitignore 排除，切勿提交）
│   ├── data/           # 记忆与训练记录（自动生成）
│   ├── tests/          # pytest：解析 / 意图 / 分析 / 存储 / HTTP 鉴权
│   ├── skills/         # 4 个可插拔教练技能（SKILL.md，按触发词动态挂载）
│   ├── _dump_prompt.py # 诊断工具：打印任意输入真正发给 LLM 的完整提示词（4 层拼装结果，排障/自查用）
│   └── src/
│       ├── orchestrator.py      # SupervisorAgent：_plan(LLM拆解)/_dispatch(代码门控派发)/_synthesize(主Agent收口)
│       ├── supervisor.py        # 单 Agent 关键词路由（健身域统一归 coach 直答）
│       ├── sport_data.py        # SportStore：暂存队列 _STAGED + 周聚合/环比/日负荷/ACWR 确定性计算
│       ├── plan_store.py        # 计划库：pending 两段确认 / 切换 / 删除
│       ├── skill_loader.py      # Skill 三级渐进加载 + 蒸馏 / patch
│       ├── memory.py            # 双存储记忆（文件锁并发保护）
│       └── agents/              # 10 个专业子 Agent + 注册表 agent_catalog
│           ├── recorder_agent.py / analyst_agent.py / searcher_agent.py
│           ├── clinician_agent.py / expert_agent.py / planner_agent.py
│           ├── memory_agent.py / scheduler_agent.py / writer_agent.py / general_agent.py
│           ├── reviewer_agent.py   # 评审：PASS / ISSUES 协议
│           └── base.py         # BaseAgent._llm：空串注入哨兵兜底文案（供门控识别）
├── frontend/           # Vue 3
│   ├── package.json / vite.config.ts
│   └── src/
│       ├── views/Chat.vue        # 聊天 + 图片上传 + 连接灯 + 动态 AgentChainBoard（plan 预填链条 / pending_commit 确认按钮）
│       └── api/client.ts         # chat / health / importImage / orchestrate(EventSource) / commitRecords
├── start-all.bat       # 一键启动三服务（各自独立窗口；启动前清空代理变量，防 TLS 被本机代理掐断）
├── _token_check.py     # 诊断工具：子 Agent 上下文体量对照（全量记忆+20轮历史 vs 按需召回+关历史，打桩不触网）
├── docker-compose.yml  # 三服务编排（见下方「Docker 部署」说明，当前需补 Dockerfile）
├── .gitignore          # 排除 .env 密钥 / 构建产物 / 运行时数据
└── 架构方案.md         # 完整架构、接口契约、演进路线
```

## 快速开始（开发模式，三服务分别启动）

> 前置：JDK 17+、Maven 3.9+、Node 22+、Python 3.13
>
> 本机已就绪路径（供参考）：JDK17 `C:/Users/24162/tools/jdk17/jdk-17.0.20+8`、
> Maven `C:/Users/24162/tools/maven/apache-maven-3.9.9`、Node/Python 用 WorkBuddy 托管运行时。

**1. agent-service（端口 8001）**
```bash
cd agent-service
pip install -r requirements.txt
python -m uvicorn app:app --port 8001 --host 127.0.0.1
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
浏览器打开 **http://localhost:5173** （注意用 `localhost` 而非 `127.0.0.1`：
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

## 安全（2026-09 加固）

- **服务鉴权**：`agent-service/.env` 里 `AGENT_AUTH_TOKEN` 非空时，除 `/health` 外所有接口要求
  请求头 `X-Agent-Token` 匹配（FastAPI 中间件）。防三类威胁：浏览器恶意网页打本机接口、
  DNS rebinding、容器化后裸奔局域网。留空 = 关闭（纯本机开发默认）。
- **启用方法（三处同步）**：`agent-service/.env`、`backend/src/main/resources/application.properties`
  的 `agent.service.token`、`frontend/vite.config.ts` 的 `X-Agent-Token`。Spring 侧改完需
  `mvn clean package -DskipTests` 重新打包。
- **CORS**：旧版 `src/server.py`（休眠的 stdlib HTTP 入口）从 `*` 收紧为仅回显本机 Origin，并走同一 token 校验。
- **异常脱敏**：Agent 内部异常只记服务端日志，客户端拿通用文案；旧版 `.env` 上传限制等回归见更新日志。

## 测试（61 个用例，`pytest tests/` 全绿）

```bash
cd agent-service
python -m pip install -r requirements-dev.txt   # pytest + httpx
python -m pytest tests/ -q
```

覆盖五层：文件导入解析（GPX/CSV/OCR 规则兜底）、意图管线（目标检测回归）、
分析层（心率区间/负荷/力量趋势）、plan_store 流转与并发、HTTP 层（鉴权中间件 + 异常脱敏）。
LLM 调用不打真实 API（mock/打桩）。OCR 可选依赖见 `requirements-ocr.txt`。

## 当前已验证（端到端全通 ✅，2026-08-19）

完整链路已实测跑通，三服务均 LISTENING（8001 / 8080 / 5173）：

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

## 更新日志（迭代脉络）

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

### 诚实说明（尚未完成）
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
