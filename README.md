# sport-agent-fullstack

个人体育训练助理的**全栈多智能体**版本。在原有 Python 零依赖 MVP（`sport-agent-mvp`）基础上，
升级为产品级混合栈：**Spring Boot 做网关/编排层，Python(FastAPI) 做 Agent 能力微服务，Vue 做前端**。

> 设计原则：现有 Python Agent 逻辑（coach / posture / research / writer / memory / scheduler / general）
> **零改动迁移**进 `agent-service/`，Java 只做「大脑」（路由 + 编排 + 网关）。

## 项目亮点（为什么值得讲）

1. **多 Agent 编排可视化**——直接回应「多 Agent 到底有没有发挥作用」。
   `research → coach → writer` 流水线由 Java 编排层串行驱动，每一步产物喂给下一步，
   整个协作过程通过 **SSE 实时推送到前端看板**（AgentChainBoard），三个 Agent 的
   pending / running / done 状态与各自产出对用户**肉眼可见**，而不是黑盒一次性吐结果。
2. **零改动迁移**——Python Agent 逻辑原样复用进微服务，Java 只接管路由与编排，
   既保住已有能力，又把「编排大脑」换成可工程化的栈。
3. **本地隐私优先**——训练截图走**本地 OCR**，图片永不离开本机，解析后结构化落库。
4. **可演进架构**——编排逻辑封装在 `Orchestrator.java`，**手写实现并预留 LangGraph4j 状态图接口**
   （保持 `run(message, emit)` 签名不变，前端零改动即可平滑换引擎，把 LangGraph 当「可插拔执行器」）。
5. **优雅降级**——无 LLM key 时自动 mock，三服务依旧跑通，便于离线演示与面试讲解。

## 技术栈（混合栈）

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite |
| 网关 / 编排 | Spring Boot 3 + 手写 Orchestrator（SSE 流式编排 research→coach→writer，预留 LangGraph4j 演进接口） |
| Agent 能力层 | Python + FastAPI 微服务（复用 MVP 的 src 包，零改动） |
| 记忆 | 双存储 USER.md / MEMORY.md（冻结快照注入）+ Skill 三级渐进加载 |
| LLM | DeepSeek（无 key 自动 mock 降级） |

## 目录结构

```
sport-agent-fullstack/
├── backend/            # Spring Boot (Java) —— 网关/编排层
│   ├── pom.xml
│   └── src/main/java/com/sportagent/
│       ├── SportAgentApplication.java
│       ├── controller/ChatController.java   # /api/chat /api/import-image /api/orchestrate(SSE) /api/health
│       └── orchestrator/Orchestrator.java   # 多 Agent 流水线 research→coach→writer
├── agent-service/      # Python Agent 微服务（零改动复用 MVP 的 src）
│   ├── app.py          # FastAPI: /chat /agent/{name} /route /health /import-image
│   ├── requirements.txt
│   ├── .env            # 含 LLM_API_KEY（已被根目录 .gitignore 排除，切勿提交）
│   ├── data/           # 记忆与训练记录（自动生成）
│   └── src/            # 原 MVP 的 src 包
├── frontend/           # Vue 3
│   ├── package.json / vite.config.ts
│   └── src/
│       ├── views/Chat.vue        # 聊天 + 图片拖拽/粘贴上传 + 连接灯 + AgentChainBoard 看板
│       └── api/client.ts         # chat / health / importImage / orchestrate(EventSource)
├── start-all.bat       # 一键启动三服务（各自独立窗口，需先 mvn 编译）
├── docker-compose.yml  # 三服务编排（见下方「Docker 部署」说明，当前需补 Dockerfile）
├── .gitignore          # 排除 .env 密钥 / 构建产物 / 运行时数据
├── build.log           # 本地编译日志（mvn 输出，可删）
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

## 当前已验证（端到端全通 ✅）

完整链路已实测跑通（2026-08-12，三服务均 LISTENING：8001 / 8080 / 5173）：
- ✅ **前端 → 后端 → Python Agent**：`localhost:5173/api/chat` → 8080 → 8001，
  "今天天气适合跑步吗" 正确路由到 `research` Agent并由真实 LLM 返回；
  "我昨天跑步5公里" 路由到 `coach` 返回训练建议。
- ✅ agent-service：`/health`、`/route`、`/chat`、`/agent/{name}` 全通，零改动复用 MVP 逻辑。
- ✅ backend：`/api/health`、`/api/chat`、`/api/import-image` 透传正常。
- ✅ **多 Agent 编排 SSE 链路（已编译部署并实测验证）**：`GET /api/orchestrate` 触发
  research→coach→writer 流水线，SSE 实时推送节点状态到前端看板。实测抓到的事件流：
  `start` → `agent_start:research` → `agent_done:research`（research 真实产出） →
  `agent_start:coach` → `agent_done:coach`（coach 真实产出） → `agent_start:writer` →
  `agent_done:writer(final)`。三个 Agent 串行执行、产物互相传递、看板实时刷新，链路闭环。
- ✅ **图片导入链路**：前端拖拽/点击/粘贴截图 → Spring Boot `/api/import-image` → agent-service `/import-image` → 本地 OCR + LLM 解析 → 训练记录落库。已用含中文的训练截图实测（`saved:true`，`type=run, distance_km=5.2`），**比 MVP 仅解析不落库更完整**。
- ✅ **教练概念问答（已修复）**：原意图分类器把含 `z1~z5`/`区间` 的消息一律判为「分析数据」并硬塞训练记录，导致「Z3 是什么」答非所问；现已补 `system_prompt` 并将概念问题路由到 LLM 对话，能真正解释心率区间等运动科学概念（实测：「Z3 和 Z4 是什么意思」返回含 bpm 区间与生理机制的解释，而非数据 dump）。

> 注：agent-service 的 `data/` 是全新副本（来自 MVP 拷贝），暂无历史训练记录，
> 所以 coach 会说"还没有跑步记录"——这是正常的，录入后即可跨会话记住。

## 当前范围（多 Agent 协作已落地 ✅）

按你的要求先搭基础全栈（同步透传），随后已补上 **B 阶段：多 Agent 编排流水线 + SSE 实时看板**，并已编译部署验证：
- 后端 `GET /api/orchestrate` 用 `SseEmitter` 跑 research→coach→writer 流水线，每步产物传给下一步，writer 综合成周报；
- 前端「生成周报（多 Agent）」按钮触发，AgentChainBoard 看板实时显示三个 Agent 的 pending/running/done 与各自产出；
- 编排逻辑封装在 `Orchestrator.java`，**手写实现并预留 LangGraph4j 状态图演进接口**（保持 `run(message, emit)` 签名不变，前端零改动即可换引擎）。

## 记忆持久化（已修复并实测 ✅）

此前「每次打开没记忆」是三层缺失，现已补齐（2026-08-13）：

- **前端聊天持久化**：`Chat.vue` 聊天记录写入 `localStorage`，刷新/重开页面历史仍在（不再是纯内存、一刷新就空）。
- **后端短期会话记忆**：`/chat` 路由补上 `memory.append_session`，每次对话落盘 `data/session.json`；
  `BaseAgent._llm` 自动把最近 20 条会话注入上下文，多轮追问有记忆。已实测：`session.json` 生成且含对话内容。
- **训练记录展示**：新增 `GET /sessions`（agent-service）返回最近训练；前端经 Vite 代理 `/agent/sessions` 拉取，
  在聊天页顶部展示「最近训练」卡片。**训练记录本体**一直持久化在 `data/sessions/*.json`（图片导入即落库），此前只是前端不展示。
- **长期画像（USER.md / MEMORY.md）**：由「记住 / 记下 …」意图触发 `memory_agent` 调用 `remember()` 写入，
  跨会话常驻并注入各 Agent 的 system prompt（真实 LLM 模式下自动解析落地；mock 模式仅提示、不写盘）。

> 注：前端只读的训练记录走 Vite 代理 `/agent` 直连 agent-service(8001)，主对话仍走 Spring Boot 网关 `/api`，
> 避免为展示型小功能重编译网关。

## 更新日志（迭代脉络）

> 全栈版（Vue3 + Spring Boot 3 + Python FastAPI）搭好后，迭代聚焦「把空壳能力真正落地 + 修 bug」。核心三层栈不变。

### 技术机制新增
- **SSE 实时推送**（Spring `SseEmitter` + 前端 `EventSource`）—— 多 Agent 编排过程可视化看板
- **前端 `localStorage` 持久化** —— 聊天记录刷新/重开不丢（此前纯内存、一刷新就空）
- **真实 LLM 打通**（DeepSeek `deepseek-v4-flash`，OpenAI 兼容接口）—— coach 真正能用大模型，告别 mock 模板
- **构建环境标准化** —— 补装 JDK17 + Maven（原机仅 Java 8，Spring Boot 跑不了）

### 模块优化
- `agent-service/coach_agent.py`：① 补 `system_prompt`（原为空，LLM 只拿到零散消息）② **修意图分类器**——"是什么/什么意思/区别"概念问题改走 LLM 对话，不再硬塞训练记录（解决"回答不出来/不够智能"）
- `agent-service/app.py`：① `/chat` 接 `append_session`（短期会话记忆落盘 `session.json`）② 新增 `GET /sessions`（训练记录可读）
- `backend/Orchestrator.java` + `ChatController.java`：`research→coach→writer` 串行编排 + `GET /api/orchestrate` SSE（重编部署，实测从 404 到全通）
- `frontend/Chat.vue`：图片上传（拖拽/点击/Ctrl+V）、连接状态灯、localStorage、最近训练卡片、AgentChainBoard 看板
- `frontend/client.ts`：`orchestrate()`（EventSource）、`getSessions()`
- `frontend/vite.config.ts`：加 `/agent` 代理直连 8001
- `.gitignore`：排除 `.env` 密钥 / 构建产物 / 运行时数据

### 诚实说明（尚未完成）
- Docker 部署仍不可用（缺 Dockerfile）
- LangGraph4j 未真正接入（手写 Orchestrator 顶替，接口预留）
- 长期记忆 USER.md 仍需「记住/记下」触发 + 真实 key 才落盘

## 接口契约

```
前端 → POST /api/chat {message} → Spring Boot → POST http://localhost:8001/chat {message}
                                                              ↓
                                            {agent, output, metadata} → 原路返回前端
```

前端 → POST /api/import-image (multipart 图片) → Spring Boot → POST http://localhost:8001/import-image {image:base64, mime}
                                                              ↓
                              OCR 本地读字（不上传图片）→ LLM 解析 → _import_save 落库 → {ok, saved, data} 回前端

agent-service 还提供：
- `POST /agent/{name}` 按名调用单个 Agent（供编排层串流水线）
- `POST /route` 仅做意图路由，返回 agent 名（供编排层先问再调）

多 Agent 编排 SSE 链路：
```
前端 → GET /api/orchestrate?message=... → Spring Boot(SseEmitter)
        → 串行调 http://localhost:8001/agent/{research,coach,writer}（每步产物喂下一步）
        → 每步 emit SSE 事件（agent_start / agent_done）
        → 前端 EventSource 订阅 → AgentChainBoard 实时刷新 research/coach/writer 状态与产出
        → writer 最终周报以 [writer] 消息进入聊天区
```

## Docker 部署（当前不可用，需补 Dockerfile）

`docker-compose.yml` 已写好三服务编排（依赖 `depends_on` + 端口映射），但各服务目录下**尚未提供 `Dockerfile`**，
因此 `docker compose up` 暂时跑不起来。开发阶段请按上方「快速开始」分别启动。
补齐 `agent-service/Dockerfile`、`backend/Dockerfile`、`frontend/Dockerfile` 后即可切换为容器部署。

## 演进路线

1. 阶段 0（已完成）：三服务代码 + agent-service 跑通
2. 阶段 1（已完成并实测验证）：多 Agent 编排流水线 + SSE 链路看板（手写 Orchestrator，预留 LangGraph4j）
3. 阶段 2：向量库替代关键词重叠（RAG 语义记忆）
4. 阶段 3：MySQL 持久化训练记录
5. 阶段 4：微信/企业微信真实接入（复用现有 /agent/{name} 契约）
