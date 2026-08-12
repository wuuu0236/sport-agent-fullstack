package com.sportagent.controller;

import com.sportagent.orchestrator.Orchestrator;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * 网关层：接收前端请求，转发到 Python agent-service。
 *
 * - /api/chat          同步透传：/api/chat -> http://localhost:8001/chat（单 Agent 对话）
 * - /api/import-image  训练截图透传（multipart -> base64），由 agent-service 做本地 OCR 落库
 * - /api/orchestrate   SSE 端点：多 Agent 编排流水线（research -> coach -> writer），
 *                      每一步状态通过 SSE 实时推回前端看板。预留改用 LangGraph4j 的接口。
 */
@RestController
@RequestMapping("/api")
public class ChatController {

    private final RestTemplate rest;
    private static final String AGENT_URL = "http://localhost:8001/chat";
    private static final String AGENT_IMPORT_URL = "http://localhost:8001/import-image";

    public ChatController() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(90000);
        this.rest = new RestTemplate(factory);
    }

    @PostMapping("/chat")
    public Map<String, Object> chat(@RequestBody Map<String, String> body) {
        return rest.postForObject(AGENT_URL, body, Map.class);
    }

    @PostMapping("/import-image")
    public Map<String, Object> importImage(@RequestParam("file") MultipartFile file) {
        try {
            byte[] bytes = file.getBytes();
            String b64 = Base64.getEncoder().encodeToString(bytes);
            Map<String, String> payload = Map.of("image", b64, "mime", file.getContentType());
            return rest.postForObject(AGENT_IMPORT_URL, payload, Map.class);
        } catch (Exception e) {
            return Map.of("ok", false, "error", e.getMessage());
        }
    }

    /**
     * 多 Agent 编排流水线（SSE 实时推状态）。
     * 前端使用 EventSource(GET) 订阅；每个 Agent 串行执行，产物互相传递，writer 综合成周报。
     */
    @GetMapping(value = "/orchestrate", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter orchestrate(@RequestParam("message") String message) {
        SseEmitter emitter = new SseEmitter(180000L);
        Orchestrator orch = new Orchestrator(rest);
        CompletableFuture.runAsync(() -> {
            try {
                orch.run(message, ev -> {
                    try {
                        emitter.send(SseEmitter.event().data(ev));
                    } catch (IOException ex) {
                        throw new RuntimeException(ex);
                    }
                });
            } catch (Exception ex) {
                try {
                    emitter.send(SseEmitter.event()
                            .data(Map.of("type", "error", "message", ex.getMessage())));
                } catch (IOException ignored) {
                    // 连接可能已经断开，忽略
                }
            } finally {
                emitter.complete();
            }
        });
        return emitter;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok", "service", "spring-boot");
    }
}
