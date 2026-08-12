package com.sportagent.orchestrator;

import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

/**
 * 多 Agent 编排层（手写版，预留 LangGraph4j 演进接口）。
 *
 * 当前实现一条线性流水线：research -> coach -> writer，每一步的产物喂给下一步，
 * 最终由 writer 综合成周报。通过 emit 回调把每个节点的「开始 / 完成」事件推给前端（SSE），
 * 从而让多 Agent 的协作过程肉眼可见——这是直接响应「多 Agent 到底有没有发挥作用」的诉求。
 *
 * 后续可平滑替换为 LangGraph4j 状态图：保持 run(message, emit) 签名不变，
 * 内部改用 StateGraph 定义节点与边即可，前端完全无需改动。
 */
public class Orchestrator {

    private final RestTemplate rest;
    private static final String AGENT_BASE = "http://localhost:8001/agent/";

    public Orchestrator(RestTemplate rest) {
        this.rest = rest;
    }

    public void run(String userMessage, Consumer<Map<String, Object>> emit) {
        emit.accept(Map.of("type", "start"));

        // 1) research：搜集训练理论 / 当下建议要点
        emit.accept(stepEvent("agent_start", "research", 1, 3, null, false));
        String research = callAgent("research", userMessage);
        emit.accept(stepEvent("agent_done", "research", 1, 3, research, false));

        // 2) coach：基于研究资料做个性化训练分析
        emit.accept(stepEvent("agent_start", "coach", 2, 3, null, false));
        String coach = callAgent("coach",
                userMessage + "\n\n（参考研究资料）\n" + truncate(research, 1500));
        emit.accept(stepEvent("agent_done", "coach", 2, 3, coach, false));

        // 3) writer：综合研究 + 分析，产出训练周报
        emit.accept(stepEvent("agent_start", "writer", 3, 3, null, false));
        String report = callAgent("writer",
                "请根据以下信息生成一份个人训练周报（结构化、口语化、可直接发给用户）。\n\n"
                        + "用户需求：" + userMessage + "\n\n"
                        + "研究要点：\n" + truncate(research, 1200) + "\n\n"
                        + "训练分析：\n" + truncate(coach, 1200));
        emit.accept(stepEvent("agent_done", "writer", 3, 3, report, true));

        emit.accept(Map.of("type", "complete"));
    }

    private Map<String, Object> stepEvent(String type, String agent, int step, int total,
                                          String output, boolean isFinal) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("type", type);
        m.put("agent", agent);
        m.put("step", step);
        m.put("total", total);
        if (output != null) m.put("output", output);
        if (isFinal) m.put("final", true);
        return m;
    }

    private String callAgent(String name, String input) {
        try {
            Map<String, String> body = Map.of("input", input);
            Map<?, ?> resp = rest.postForObject(AGENT_BASE + name, body, Map.class);
            Object out = resp != null ? resp.get("output") : null;
            return out != null ? out.toString() : "";
        } catch (Exception e) {
            return "[调用 " + name + " 失败: " + e.getMessage() + "]";
        }
    }

    private String truncate(String s, int max) {
        if (s == null) return "";
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }
}
