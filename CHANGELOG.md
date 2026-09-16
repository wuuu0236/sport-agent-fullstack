# 更新日志（迭代脉络）

> 本文件由 README 拆出（2026-09-15）：README 只保留项目介绍 / 功能 / 架构 / 快速开始等当前状态，
> 按时间的迭代记录统一放这里。

### 2026-09-16 教练人格分层 + 知识层自进化通道（方案 P1-3）
把谭成义的 prompt 显式拆成「代码里的人格层」与「`skills/` 里的知识层」，**并修掉两处让这条通道静默失效的断点**。测试 168 → **182 passed**。

**一、人格分层：把「不可自进化」变成结构保证而不是口头约定**
- 原 `CoachAgent.system_prompt` 是一个 734 字的单体字符串，人格骨架和知识混在一处、没有边界。现抽出 `CoachAgent.PERSONA_CORE`（身份 / 核心原则 / 动作铁律 / 表达风格 / 边界声明），`system_prompt` 指向同一对象，**单一真源、不复制字符串**。
- 为什么这样就能防跑偏：`存技能` 与 `patch 技能` 的落盘目标只有 `skills/`，**没有任何代码路径能写回 `PERSONA_CORE`**。改动只能来自人工改代码，因而会出现在 diff 里、能被 review 拦住。用测试钉死（`test_persona_core_immutable_by_patch`：patch 技能前后逐字节比对）。
- 补一条反向约束（`test_persona_core_does_not_contain_skill_sop`）：人格层里不允许出现任何技能正文——防止将来有人「图省事」把知识写回人格层，那样分层就白做了。

**二、修掉两处静默失效（探针实测出来的，方案文档没提）**
- **① 结构化路径完全拿不到知识层**。`coach.handle()` 里记录/分析之后的「补一句个性化建议」是**直连 `llm.chat`** 的（自带一段硬编码的迷你人格），绕过基类 → 既没技能注入、也没记忆注入。而「心跳/配速类问句」经 `_classify` 判为 `analyze_run`，走的正是这条结构化路径。结果就是：**`patch 技能 coach_hr_zones` 对心率类回答的实际影响近乎为零**——方案文档设想的那条链路在主路径上不成立。现改为 `_tip()` 走同一个装配：知识层（命中技能正文）随补建议一起注入。
  - 实测（真实 LLM）：`存技能：心率 …必须附标记 [HR-KB-OK]` → 问「我的心率区间是多少」→ 分析结果后的 💡 行**确实带上了该标记**；对照组「深蹲进步了吗」（触发词不含「心率」）**不带**——证明注入是按触发词门控的，不是无脑全塞。
- **② 技能目录缓存永不失效**。`base._get_catalogue()` 只在首次调用时拼一次并永久复用，`_invalidate_catalogue()` 定义了却**没有任何调用点** → `存技能` 之后新技能永远不出现在 Tier 1 目录里，LLM 根本不知道自己「有」这个技能可调用。现改为 `skill_loader` 维护**注册表版本号**（每次重建 `_CACHE` 自增），基类缓存跟随版本号失效——避免 base ↔ skill_loader 反向依赖（不搞回调）。
  - 端到端实测：`存技能：练后拉伸 …` → 立刻问「练后拉伸要注意什么」→ `used_skills=["练后拉伸"]`，回答里出现用户自定义的标记；再 `patch 技能 练后拉伸：…` → 下一次回答里出现的是**补丁后的**标记。整条「存技能 / patch → 下次对话即生效」在真实服务上跑通。

**三、能力边界（如实记录，别过度承诺）**
- 体力活是**确定性代码**：《我的心率区间是多少》这类问句由 `_classify` 判为 `analyze_run`，区间分布、TRIMP 都由 `sport_data.py` 的 `ZONES` 算出，**不经过技能**。所以 patch 技能改的是**判读口径/解释**，**不是数值边界**——数值边界属可计算契约，要改得改代码。这是设计取舍，不是缺口。
- `_tip()` 的职责说明只是**指向人格层的短指针**，不再复制一份人格描述（原实现里那句「你是谭成义（铁馆老炮教练）。…」是第二份人格定义，日久必与 `PERSONA_CORE` 漂移）。

**四、验证**
- 新增 `tests/test_coach_persona.py` 14 条（人格层不可写 / 知识层双路径注入 / 目录热更新 / coach 吸收 clinician 白名单不回归）。
- **测试有效性用「回退到旧行为」验证过**：临时把目录缓存改回永久复用、把 `_tip` 的技能注入摘掉 → 对应两条用例确实变红（`新蒸馏的技能没进目录`、`知识层没进「补一句建议」的 system prompt`），恢复后 182 全绿。只增不减。
- 实机（真实 DeepSeek）：`/health` ok；「今天怎么练胸」5.4s 直答、「我的心率区间是多少」2.3s 且 `used_skills=["coach_hr_zones"]`、「帮我生成周报」14.1s 编排；验证用的临时技能与会话记录已清理（会话表 50 → 28 行，只删本次测试产生的 22 行）。

### 2026-09-16 记忆迁 SQLite + 中文混合召回（方案 P1-2，阶段一/二/三）
存储层从「双 Markdown 文件 + 手写锁」迁到 SQLite 唯一真源，**并顺带修掉一个此前没人发现的功能性缺陷：中文按需召回实际恒为 0 命中**。测试 147 → **168 passed**。

**一、存储迁 SQLite（阶段一）**
- 唯一真源 `data/memory.db`（SQLite + **WAL**）：条目表 `entries` + FTS5 索引表 `entries_fts` + 会话表 `session_messages` + `meta`。并发保护交给 WAL（`busy_timeout` 先设、`journal_mode` 后设——反过来在多线程首次并发建库时那句 pragma 没有等待余量，会直接抛 `database is locked`），**手写 `threading.Lock` 与 `file_lock` 全部拿掉**。
- `USER.md` / `MEMORY.md` 退化为「写入后同步的**只读人读视图**」，不再被任何代码读取（有测试钉住：手动改视图文件不影响读取结果）。
- **一次性迁移**（幂等，靠 `meta` 标记）：自动导入旧 `USER.md`(7 条) / `MEMORY.md` / `session.json`(50 条)。不做会话迁移的话重启后「最近对话」会变空——那是**用户可见的回归**，所以一并迁了。原文件保持不动（实测 `USER.md` 474 字节、mtime 未变）。
- **绕开 memory 模块直读文件的 3 处调用点全部收敛**：`coach_agent._user_max_hr()` 与 `analyst_agent.user_max_hr()` 各自 `USER_FILE.read_text()` + 正则抓最大心率（重复实现），改为共用 `memory.baseline_max_hr()`；`skill_loader._recent_session()` 从读 `session.json` 改为 `memory.session_turns()`。**这 3 处不改的话迁完就读僵尸文件了。**

**二、中文召回重写（阶段一核心，实测驱动的设计）**
- **旧实现为什么是坏的**：`re.compile(r"[\w\u4e00-\u9fff]+")` 里 `\w` **本身就匹配 CJK**（该字符类里的 `\u4e00-\u9fff` 是冗余的），所以 `findall("膝盖疼还能深蹲吗")` 得到的是**整句一个 token**；再拿整句去做 `t in entry` 子串判断，永不命中。独立复核：5 条中文记忆 × **14 个真实中文问句 = 0/14**；且生产路径调用点传进来的是合成 prompt（`用户需求：…\n\n待评审内容：…`），连「整句子串」这条退路也用不上 → `if mem_hits:` 恒假，`<memory-context>` 块**从不注入**，「按需召回 Top5」形同虚设。
- **试过的方案与实测数据**（同一语料 14 条 / 12 个真实问句）：
  | 方案 | 有召回问句数 | 失败原因 |
  | --- | --- | --- |
  | 旧实现（正则重叠） | 0/12 | 整句一个 token |
  | jieba + token 全 AND | 2/12 | 用户问句里的「区间/是多少」不在记忆里，AND 直接掐死 |
  | jieba 词 + OR + bm25 | 7/12 | `卧推`/`练胸`/`深蹲` 被 jieba 切成单字，过滤后查询为空 |
  | **jieba 词 ∪ bigram + OR + bm25（采用）** | **11/12** | 仅剩同义词字面不重合（膝盖↔膝关节），只有向量能救 |
- **最终设计**：FTS5 两列 `words` / `bigrams` + 分列权重 `bm25(entries_fts, 2.0, 0.5)`（词级命中权重是 bigram 的两倍，否则「注意」「什么」这类泛词会盖过信号）；索引列存**切好的 token**，不存原文。
- **中文 FTS5 的两个坑（实测，方案文档没提）**：① 内置 `unicode61` 对中文**全 0 命中**——整句被当成一个 token；② `trigram` 分词器**只支持 ≥3 字符**，中文最高频的 2 字词（膝盖/心率/卧推/增肌）全部失效，加引号、加 `*` 都不行。结论：中文 FTS5 必须自己喂切好的 token。
- **召回 query 来源也修了**：`BaseAgent._llm` 原先拿 `user_msg` 去检索，而它是编排层拼出来的指令文本（含大量与用户无关的噪声）；改为优先用 `ctx["task"]`（原始用户任务）。
- 真实 7 条画像上的对照：**旧 1/8 → 新 8/8**（旧实现唯一命中的是字面连续子串「减脂」）。

**三、向量融合与近重复合并（阶段二/三，可选增强）**
- 新增 `EMBED_API_KEY` / `EMBED_BASE_URL`（默认硅基流动）/ `EMBED_MODEL`（默认 `BAAI/bge-m3`）；`llm.embed_many()` 批量取向量，**任何失败都返回 `[None]*n` 而不是抛异常**——向量召回是可选增强，降级路径必须和成功路径一样好走。未配 key 是**默认正常状态**（DeepSeek 不提供 embedding 接口），纯关键词召回照常工作。
- 配了 key：召回按 `0.5×关键词得分 + 0.5×余弦相似度` 融合；写入时对相似度 > `SIM_MERGE`(0.9) 的已有条目**更新而非新增**（防重复膨胀）。
- **必须有的补齐步骤**：`EMBED_API_KEY` 是后配的，之前写入的条目 `embedding` 为 NULL，不补齐的话近重复合并对这些历史条目**永远不生效**（功能形同虚设）。加了 `_backfill_embeddings()`，用批量接口一次算完并用 `_BACKFILL_LIMIT`(50) 封顶。

**踩坑记录（两个都是测试才暴露的）**
1. **在 `with _db()` 事务提交前调 `self.load()`**：`load()` 会**另开一条连接**（读不到未提交数据），所以合并分支「内容写进去了、快照还是旧的」。修法是把结果记到标志位、**退出 `with` 之后**再 load。
2. **假 embedding 太粗**：测试里未命中关键词的文本全落到同一个兜底维度 → 余弦恒为 1.0 → 「不相似」的用例被判成近重复而误报。改用 `crc32` 散列到正交维度（不用内置 `hash`，它有进程级随机化，测试会间歇性飘）。

**新增测试 21 条**：`tests/test_memory_search.py`（新增 17）钉住「整句不许当 token」「短词靠 bigram 兜住」「同语料有召回问句数 ≥8」「不相关问句宁可返回空」「无 key / 接口挂掉都不许抛异常」「近重复合并 vs 正常新增」「合并后索引指向新内容」；`test_memory.py`（+4）覆盖三类迁移的导入与幂等、只读视图不参与读取、整套替换后索引重建。`test_memory.py` 的夹具加 `MEMORY_DB` 与 `_initialized` 重置（建表是一次性动作，不重置新库拿不到 schema）。

**实机验证（真实 LLM）**：`/health` 正常；`/memory` 返回 7 条画像（迁移无损）；coach 直答「我该怎么练胸」5.7s，答案里用到了记忆中的**最大心率 190 / 静息 55**；编排「帮我生成周报」14.9s。另外用打桩 `llm.chat` 截获 system prompt，确认 `recall_mode="recall"` 的子 Agent **确实拼进了 `<memory-context>`**（这是旧实现从没做到的事）。

**顺带发现（本轮未处理）**：记忆注入只在走 `BaseAgent._llm` 的分支生效——`clinician` 的康复知识库分支与 `coach`/`clinician` 那句「补一句建议」的 tip 调用都**直连 `llm.chat`**、绕过基类，因此这些分支拿不到按需召回的记忆。这是既有架构模式（确定性 Agent 不走基类），不是本次引入的；改动会影响这些 Agent 的行为，留给你定。

### 2026-09-16 评审三层加固（方案 P1-1）
评审原先只有**一次 LLM 调用**，有两个结构性弱点：① 空产出、降级文案、短得没法交付这类机械缺陷也要花一次调用来发现；② 没有确定性基线，同一条产出「过不过」完全取决于模型当时的状态。现在把「能硬判的」交给代码，LLM 只处理「需要理解的」。测试 127 → **147 passed**（+20）。

- **第一层 · 规则检查（`src/review_rules.py`，新增，纯代码不花 token）**：
  - `blocking` 只在**机械性缺陷**上成立——空产出 / 哨兵文案（`（模型本次未生成内容）`）/ 降级文案 / 短于 80 字。命中即判不过，**直接短路，不再调 LLM 评审**，失败原因可复现、可写进测试；
  - `hints`（疑似缺段落、带度量单位的数字在上游材料里找不到出处）**永远不 blocking**，只作为「已知疑点」拼进评审提示让模型判。理由是踩过坑：历史上评审误报把正确产出判死过一次，所以凡有疑义的规则一律只提示、不裁决。数字核对也只收「记录型」单位（km / bpm / 配速 / TRIMP），不收 8 周 / 4 组 / 80kg 这类计划参数——计划类产出天然满篇数字，一律当编造会把好产出判死。
- **第二层 · 结构化清单（`reviewer_agent.py` 重写）**：system_prompt 从「审查数据真实性/安全/完整性/幻觉」这种开放式描述，改成**五维逐项清单**（数据准确性 / 用户适配 / 可操作性 / 无编造 / 完整性），每项必须给出 `[OK] 维度：理由` 或 `[NG] 维度：问题 + 怎么改`，避免开放式评价退化成「看起来还行」；并要求逐条回应传进来的规则检查疑点（属实就保留，核对无误就写「已核对，非编造」）。
- **第三层 · 换模型评审 + 意见传递**：
  - 新增 `REVIEW_MODEL` / `REVIEW_BASE_URL` / `REVIEW_API_KEY`（`config.review_llm`），评审可走**另一套模型/供应商**，消除同模型自评的盲区共享、自我偏好、推理路径重合三类偏差。未配置回退同模型，并在 `agent_done` 事件的 `reviewer_model` 字段如实标注实际用的是哪个——不让人误以为换了。同批修掉 `base.py` 空回复重试不带 override 的问题：那会让配了 `REVIEW_MODEL` 的场景在重试时悄悄退回默认模型，把「换模型评审」无声降级成自评。
  - **非 planner 步骤的评审意见不再丢弃**：原先 `ISSUES` 只有「被评节点是 planner」才触发重写，其余情况意见记完就丢，用户拿到一份「已知有问题」的产出却毫不知情。现在这类意见进 `review_issues` 通道——LLM 综合路径写进提示词由主 Agent 修正或标注，直出路径（单步 / planner 产出直接采用）则以 `⚠️ 评审提示（本轮未修复，请谨慎参考）` 附在产出后面。
- **踩坑记录（LangGraph 状态通道）**：`review_issues` 一开始忘了写进 `OrchestrationState`，**LangGraph 按 TypedDict 字段建通道，没声明的键会被静默丢弃**——节点明明 `return` 了值，`synthesize` 却永远读到空，测试才暴露出来。已加注释锁死，勿删。
- **新增测试 20 条**：`tests/test_review_rules.py`（13）钉住规则层判据边界——只有空/哨兵/降级/过短判 blocking，缺段落与数字无出处只提示、blocking 时短路不猜 hints、`format_issues` 输出必须能被评审闸门识别为「不过」；`tests/test_graph.py` 补 7 条锁三层接线（规则短路时 LLM 评审零调用、规则放行才走 LLM、planner 的意见靠重写消化不透传、意见进综合提示词、直出路径附注）。
  - 顺带修了测试夹具：打桩产出从 8 个字改成一段完整周报——否则会被新的规则层判「过短」，用例就测不到第二、三层的接线了。


### 2026-09-16 编排层迁移 LangGraph StateGraph + LLM 意图分类（P0 三项）
按《技术选型与优化方案》实施 P0。**编排层不再是手写主循环**——`src/graph.py` 的 StateGraph 与 `src/intent.py` 的意图分类，测试 104 → **127 passed**。

- **编排图（`src/graph.py`，新增）**：`plan → validate → dispatch ⇄ dispatch → review →(rewrite)→ synthesize`，条件边表达分支。`dispatch` 自循环一次跑一步（与迁移前 for 循环语义一致），跑完才进评审。**事件序列逐字不变**（start / plan / agent_start / agent_done / agent_error / complete / pending_commit），因此 Java 网关与前端看板零改动。
  - **与方案的一处有意偏差**：分类节点没放进图里，留在入口（`app.py` 调 `intent.classify`）。因为 `/chat` 的单 Agent 路径前面还有记忆意图、目标变更、计划生成三个旁路，且要吃 `req.context`——把 direct 分支搬进图等于把这套逻辑实现两遍，两处必然漂移。图只负责「多 Agent 协作」这一段。
  - `src/orchestrator.py` 从 341 行降到 39 行，只保留门面：`SupervisorAgent.run(task, emit)` 与 `used_skills` 对外契约不变（三个入口 + `test_skills.py` 都不用改）。
- **LLM 意图分类（`src/intent.py`，新增）**：原来只有「周报 / 总结+时间范围 / 数据驱动计划」三类魔法词才升级编排，典型复杂任务被 coach 硬答。现在由一次轻量 LLM 调用输出 `{type, reason, suggested_agents}`；**规则函数保留为兜底**（mock 模式 / 调用失败 / JSON 解析失败 / 产出非法类型），所以「无 key 也能跑通」这条约束不变，`app._needs_orchestration` 也保留为规则别名（意图回归测试入口）。安全取向：分类失败一律保守回退——宁可少拆一次，也不把普通问答升级成 20 秒编排。
- **拆解去偏 + 依赖校验（P0-3）**：`_PLAN_PROMPT` 删掉「需要资料派 searcher、需要分析派 analyst、出计划派 planner」的固定管线暗示，改为按任务类型举例（伤病 → clinician+expert+planner；跨期对比 → 两次 analyst 各取一期 + 综合）；`_plan()` 里「命中健身域关键词就返回单步」的短路删掉（它会让 LLM 拆解永不执行）；`_fallback_plan()` 按伤病/汇报/计划分档，不再一律硬编码 searcher→analyst→planner。**新增 `validate_steps()`**：指向不存在步骤的 `@s9` 引用清除、该用上游产出却没写引用时自动补 `@s1`——修掉「LLM 漏引 → planner 拿不到上游产出 → 生成看起来完整实际缺料的报告，且丢失是静默的」这个缝隙。
- **新增测试 23 条**：`tests/test_graph.py`（16）覆盖事件序列契约、逐步派发、失败继续、暂存附注、评审重写只做一次、非 planner 不重写、依赖校验四态、兜底模板分档；`tests/test_intent.py` 的 `TestClassify`（7）覆盖 mock 回退、显式编排、JSON 解析、markdown 包裹、垃圾输出回退、调用异常回退、规则别名仍在。首次运行暴露了一个测试卫生问题：评审节点会真的打 LLM（38s + 触发真实重写导致断言不确定）→ 加 autouse 夹具把 `get_agent` 打桩，降到 0.4s。

**实机验证（真实 LLM，`/chat` 自动分流，8/8 符合预期）**

| 用例 | 迁移前 | 迁移后 |
| --- | --- | --- |
| 膝盖疼，分析是不是深蹲姿势问题，给康复方案 | coach 一人硬答 | ✅ 编排 `clinician + expert + planner`（33.8s，13 事件） |
| 对比上个月和这个月的跑步数据 | coach 一人硬答 | ✅ 编排 `analyst + analyst + writer`（17.2s，11 事件；产出还如实指出「两期数据完全相同」） |
| 备战半马，查最新方法，结合我的水平排8周计划 | coach 一人硬答 | ✅ 编排 `searcher + analyst + planner`（33.4s） |
| 帮我生成周报 | 编排但产出错 | ✅ 编排 `analyst + planner`，产出为周报骨架（22.3s） |
| 怎么练胸 / 总结一下卧推要点 / 卧推要点 | 单 Agent | ✅ 仍单 Agent coach（4.7~5.3s，未被误升级） |
| 周报一般包含什么内容 | 单 Agent | ✅ 仍单 Agent（5.6s） |

> 两个已知问题如实记录（本轮未动）：① `searcher` 返回的检索结果质量差（实测两次都是搜索引擎首页 / 词义漂移内容），planner 只能「不引用垃圾来源」并如实说明——属方案 P1-2 范畴；② 编排路径耗时 17~34s，因为拆解 + 多步 + 评审都是串行 LLM 调用。

**依赖与启动方式变更（重要）**：agent-service 不再是「零依赖」，改用项目专属 venv（`agent-service/.venv`，已 gitignore）装 `langgraph 1.2.11` + `langgraph-checkpoint-sqlite 3.1.1`（后者为 P2 的 checkpointer/interrupt 预留）。`start-all.bat` 的 agent-service 行改指向 `.venv\Scripts\python.exe`；README 快速开始同步。

**方案里未做的部分（P1/P2）**：教练人格自进化通道、暂存区迁到 interrupt——留给后续（**评审三层加固、SQLite FTS5 + 混合召回均已完成，见上方 2026-09-16 两节**）。另外方案文档写「现有 90 个 pytest 用例」，实际当时已是 104。

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

