package com.sportagent.controller;

import com.sportagent.orchestrator.Orchestrator;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 网关层：接收前端请求，转发到 Python agent-service。
 *
 * - /api/chat          同步透传：/api/chat -> agent-service /chat（单 Agent 对话）
 * - /api/import-image  训练截图透传（multipart -> base64），由 agent-service 做本地 OCR
 * - /api/commit        确认暂存记录入库
 * - /api/orchestrate   SSE 端点：多 Agent 编排，Python Supervisor 的 SSE 事件流原样透传
 */
@RestController
@RequestMapping("/api")
public class ChatController {

    /**
     * 编排专用线程池：SSE 编排任务是长阻塞 IO（最长 300s），不能丢进
     * CompletableFuture 默认的 ForkJoinPool.commonPool —— 几个并发编排
     * 就会占满公共池，拖垮 JVM 里所有其他 parallel 流/异步任务。
     * 有界队列 + 拒绝时同步降级，保护网关自身不被编排请求拖死。
     */
    private static final AtomicInteger ORCH_THREAD_SEQ = new AtomicInteger();

    private static final ExecutorService ORCHESTRATION_POOL = new ThreadPoolExecutor(
            2, 8, 60L, TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(32),
            r -> {
                Thread t = new Thread(r, "orchestrate-" + ORCH_THREAD_SEQ.incrementAndGet());
                t.setDaemon(true);
                return t;
            },
            new ThreadPoolExecutor.CallerRunsPolicy());

    private final RestTemplate rest;
    private final String agentBaseUrl;
    private final String agentToken;

    public ChatController(
            @Value("${agent.service.base-url:http://127.0.0.1:8001}") String baseUrl,
            @Value("${agent.service.token:}") String token) {
        this.agentBaseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        this.agentToken = token == null ? "" : token.trim();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5000);
        factory.setReadTimeout(90000);
        this.rest = new RestTemplate(factory);
        // 所有对 agent-service 的调用统一带上 X-Agent-Token（token 为空则不带，
        // 与 Python 侧「留空 = 关闭鉴权」的约定对应）
        if (!agentToken.isEmpty()) {
            this.rest.getInterceptors().add(authInterceptor());
        }
    }

    private ClientHttpRequestInterceptor authInterceptor() {
        return (request, body, execution) -> {
            request.getHeaders().set("X-Agent-Token", agentToken);
            return execution.execute(request, body);
        };
    }

    /** 统一兜底：agent-service 不可用/超时时给前端可读的 502 语义，不抛裸异常。 */
    private Map<String, Object> callAgent(String path, Object payload) {
        try {
            return rest.postForObject(agentBaseUrl + path, payload, Map.class);
        } catch (Exception e) {
            return Map.of("ok", false, "error", "agent-service 不可用：" + e.getClass().getSimpleName());
        }
    }

    @PostMapping("/chat")
    public Map<String, Object> chat(@RequestBody Map<String, String> body) {
        return callAgent("/chat", body);
    }

    @PostMapping("/import-image")
    public Map<String, Object> importImage(@RequestParam("file") MultipartFile file) {
        try {
            byte[] bytes = file.getBytes();
            String b64 = Base64.getEncoder().encodeToString(bytes);
            // getContentType() 可能为 null（客户端未指定），Map.of 不接受 null 值会 NPE
            String mime = file.getContentType() == null ? "image/png" : file.getContentType();
            Map<String, String> payload = Map.of("image", b64, "mime", mime);
            return callAgent("/import-image", payload);
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
            return Map.of("ok", false, "error", msg);
        }
    }

    /**
     * 确认暂存记录入库：前端编排看板点「确认入库」→ 透传 Python /commit（落暂存区记录）。
     */
    @PostMapping("/commit")
    public Map<String, Object> commit(@RequestBody(required = false) Map<String, Object> body) {
        if (body == null) {
            body = Map.of();
        }
        return callAgent("/commit", body);
    }

    /**
     * 多 Agent 主从编排（SSE 实时推状态）。
     * 前端使用 EventSource(GET) 订阅；Orchestrator 薄转发 Python Supervisor 的 SSE 事件流，
     * 主 Agent 拆解→派发子 Agent→回收→综合 的每一步状态原样透传。
     */
    @GetMapping(value = "/orchestrate", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter orchestrate(@RequestParam("message") String message) {
        // 300s：容纳编排层的单节点重试（每节点最多 20s×3 + 退避）
        SseEmitter emitter = new SseEmitter(300000L);
        // Orchestrator 自带独立 HTTP 连接（紧超时 + 重试），不复用透传用的 90s 客户端
        Orchestrator orch = new Orchestrator(agentBaseUrl, agentToken);
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
        }, ORCHESTRATION_POOL);
        return emitter;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "ok", "service", "spring-boot");
    }
}
