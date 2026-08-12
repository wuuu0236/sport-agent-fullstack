"""sport-agent-service: 把现有 Python Agent 能力暴露为 HTTP 微服务。

复用 sport-agent-mvp 的 src 包（coach / posture / research / writer / memory / scheduler / general），
零改动迁移。Spring Boot 编排层通过本服务调度各 Agent。

端点：
  GET  /health           健康检查（返回 mock 状态与模型名）
  POST /chat             {message, context?} -> {agent, output, metadata}   内部路由+处理（一站式）
  POST /agent/{name}     {input,  context?} -> {agent, output, metadata}   按名调用（供编排层串流水线）
  POST /route            {message}          -> {agent}                      仅路由，供编排层先问再调
  GET  /sessions         {limit?}           -> {sessions:[{type,date,summary}]}  最近训练记录（供前端展示）
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import base64

from src import config, memory
from src.supervisor import route
from src.agents import get_agent
from src.skill_loader import match_skills
from src.server import image_import, _import_save
from src.sport_data import SportStore

_store = SportStore()


app = FastAPI(title="sport-agent-service", version="0.1.0")


class ChatReq(BaseModel):
    message: str
    context: dict = None


class AgentReq(BaseModel):
    input: str
    context: dict = None


class RouteReq(BaseModel):
    message: str


class ImportReq(BaseModel):
    image: str           # base64 编码的图片
    mime: str = "image/png"


@app.get("/health")
def health():
    return {"status": "ok", "mock": config.CONFIG.mock_mode, "model": config.CONFIG.LLM_MODEL}


@app.post("/chat")
def chat(req: ChatReq):
    # 短期会话记忆落盘：用户消息先 append，助理回复后再 append。
    # BaseAgent._llm 会自动把最近 N 条 session_turns 注入上下文，多轮追问才有记忆。
    memory.append_session("user", req.message)
    name = route(req.message)
    agent = get_agent(name)
    skills = match_skills(req.message)
    ctx = {"skills": skills}
    if req.context:
        ctx.update(req.context)
    try:
        out = agent.handle(req.message, ctx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent[{name}] failed: {e}")
    memory.append_session("assistant", out)
    return {
        "agent": name,
        "output": out,
        "metadata": {"used_skills": [s.get("name") for s in skills]},
    }


@app.post("/agent/{name}")
def agent_call(name: str, req: AgentReq):
    agent = get_agent(name)
    skills = match_skills(req.input)
    ctx = {"skills": skills}
    if req.context:
        ctx.update(req.context)
    try:
        out = agent.handle(req.input, ctx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent[{name}] failed: {e}")
    return {
        "agent": name,
        "output": out,
        "metadata": {"used_skills": [s.get("name") for s in skills]},
    }


@app.post("/route")
def route_only(req: RouteReq):
    return {"agent": route(req.message)}


@app.get("/sessions")
def list_sessions(limit: int = 12):
    """最近训练记录（供前端『最近训练』展示）。"""
    recs = _store.all()
    recs.sort(key=lambda r: r.get("date") or "", reverse=True)
    out = []
    for r in recs[:limit]:
        if r.get("type") == "run":
            s = f"跑步 {r.get('distance_km')}km / {r.get('duration_min')}分"
            if r.get("avg_hr"):
                s += f" / 平均心率{r.get('avg_hr')}"
        elif r.get("type") == "strength":
            exs = "、".join(
                f"{e.get('name')}{e.get('sets')}×{e.get('reps')}×{e.get('weight_kg')}kg"
                for e in r.get("exercises", [])
            )
            s = f"力量：{exs}"
        else:
            s = str(r.get("type", ""))
        out.append({"type": r.get("type"), "date": r.get("date"), "summary": s})
    return {"sessions": out}


@app.post("/import-image")
def import_image(req: ImportReq):
    """训练截图导入：本地 OCR → 文字 → LLM 解析 → 落库。

    比 MVP 的 /import_image 多一步：解析成功后真正写入训练记录（_import_save），
    所以用户在「你记得我什么」里能看到这次导入。截图不外传，仅 OCR 文本送 LLM。
    """
    res = image_import(req.image, req.mime)
    if res.get("ok") and res.get("data"):
        try:
            _import_save({"data": res["data"]})
            res["saved"] = True
        except Exception as e:  # noqa: BLE001
            res["saved"] = False
            res["save_error"] = str(e)
    return res
