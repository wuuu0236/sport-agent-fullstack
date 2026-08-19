package com.sportagent.orchestrator;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.function.Consumer;

/**
 * 多 Agent 编排层（薄转发版）。
 *
 * 真正的多 Agent 机制在 Python agent-service 的 SupervisorAgent（主-从分发）：
 * 主 Agent 用 LLM 拆解任务 → 显式派发给子 Agent（recorder/analyst/searcher/
 * clinician/expert/planner/...）→ 回收摘要 → 综合成最终回答。
 *
 * 本类只做一件事：把前端的编排请求转发给 /supervise（SSE 事件流），
 * 把 Python 逐事件推送的 start/plan/agent_start/agent_done/agent_error/
 * complete/pending_commit 原样透传给前端。前端零改动——事件格式与旧流水线一致。
 *
 * 容错由 Python 侧承担（LLM 拆解失败回退模板计划；子 Agent 失败跳过并如实注明；
 * 综合失败降级拼接子 Agent 产出）。本类只负责流式透传与连接兜底。
 */
public class Orchestrator {

    private static final String SUPERVISE_URL = "http://localhost:8001/supervise";

    private static final int CONNECT_TIMEOUT_MS = 5_000;
    // 覆盖整个编排时长（多 Agent 串行 + 各子 Agent 一次 LLM 调用）
    private static final int READ_TIMEOUT_MS = 300_000;

    private final ObjectMapper mapper = new ObjectMapper();

    public Orchestrator() {
    }

    public void run(String userMessage, Consumer<Map<String, Object>> emit) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(SUPERVISE_URL + "?stream=1");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);

            String body = "{\"message\":" + mapper.writeValueAsString(userMessage) + "}";
            conn.getOutputStream().write(body.getBytes(StandardCharsets.UTF_8));
            conn.getOutputStream().flush();

            // 逐事件透传：Python 的 SSE 帧以空行分隔，data: <json>
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8));
            StringBuilder frame = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) {
                    if (frame.length() > 0) {
                        forward(frame.toString().trim(), emit);
                        frame.setLength(0);
                    }
                } else {
                    frame.append(line).append("\n");
                }
            }
            reader.close();
        } catch (Exception e) {
            emit.accept(Map.of("type", "error", "message", e.getMessage()));
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /** 解析单帧 SSE（data: <json>），原样转发给前端。 */
    private void forward(String frame, Consumer<Map<String, Object>> emit) {
        if (!frame.startsWith("data:")) {
            return;
        }
        String json = frame.substring(5).trim();
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> ev = mapper.readValue(json, Map.class);
            emit.accept(ev);
        } catch (Exception ignored) {
            // 坏帧丢弃，不影响整体流程
        }
    }
}
