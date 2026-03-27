package com.bitman.marketflow.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.File;
import java.nio.file.Paths;
import java.text.DecimalFormat;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@RestController
@RequestMapping("/api/system")
public class SystemController {

    @Value("${app.data.kr-data-dir}")
    private String krDataDir;

    @Value("${app.data.us-output-dir}")
    private String usOutputDir;

    @Value("${app.flask.base-url:http://localhost:5001}")
    private String flaskBaseUrl;

    private static final DateTimeFormatter FMT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.of("Asia/Seoul"));

    // ── 파일 목록 정의 — 단일 경로: kr=data/, us=us_market/output/ ────────────────

    private static final List<Map<String, String>> FILE_DEFS = List.of(
        Map.of("name", "AI Jongga V2",          "dir", "kr",  "file", "jongga_v2_latest.json",             "menu", "/dashboard/kr/closing-bet"),
        Map.of("name", "KR Market Gate",         "dir", "kr",  "file", "market_gate_cache.json",            "menu", "/dashboard/kr"),
        Map.of("name", "KR VCP Enhanced",        "dir", "kr",  "file", "vcp_kr_latest.json",               "menu", "/dashboard/vcp-enhanced"),
        Map.of("name", "KR AI Analysis",         "dir", "kr",  "file", "kr_ai_analysis.json",              "menu", "/dashboard/kr"),
        Map.of("name", "Daily Prices",           "dir", "kr",  "file", "daily_prices.csv",                 "menu", "/dashboard/kr"),
        Map.of("name", "Institutional Trend",    "dir", "kr",  "file", "all_institutional_trend_data.csv", "menu", "/dashboard/kr"),
        Map.of("name", "VCP US",                 "dir", "kr",  "file", "vcp_us_latest.json",               "menu", "/dashboard/vcp-enhanced"),
        Map.of("name", "VCP Crypto",             "dir", "kr",  "file", "vcp_crypto_latest.json",           "menu", "/dashboard/vcp-enhanced"),
        Map.of("name", "AI Briefing",            "dir", "us",  "file", "briefing.json",                    "menu", "/dashboard/us"),
        Map.of("name", "Market Data",            "dir", "us",  "file", "market_data.json",                 "menu", "/dashboard/us"),
        Map.of("name", "Top Picks",              "dir", "us",  "file", "top_picks.json",                   "menu", "/dashboard/us"),
        Map.of("name", "Index Prediction",       "dir", "us",  "file", "index_prediction.json",            "menu", "/dashboard/us"),
        Map.of("name", "Sector Heatmap",         "dir", "us",  "file", "sector_heatmap.json",              "menu", "/dashboard/us"),
        Map.of("name", "Earnings Impact",        "dir", "us",  "file", "earnings_impact.json",             "menu", "/dashboard/us"),
        Map.of("name", "Decision Signal",        "dir", "us",  "file", "decision_signal_snapshot.json",    "menu", "/dashboard/us"),
        Map.of("name", "Cumulative Perf",        "dir", "us",  "file", "cumulative_perf_snapshot.json",    "menu", "/dashboard/us"),
        Map.of("name", "Crypto Dominance",       "dir", "kr",  "file", "crypto_dominance_cache.json",      "menu", "/dashboard/crypto"),
        Map.of("name", "Historical Signals",     "dir", "kr",  "file", "historical_signals.csv",           "menu", "/dashboard/vcp-enhanced")
    );

    // ── GET /api/system/data-status ─────────────────────────────────────────────

    @GetMapping("/data-status")
    public Map<String, Object> dataStatus() {
        List<Map<String, Object>> files = new ArrayList<>();

        for (Map<String, String> def : FILE_DEFS) {
            String dirKey = def.get("dir");
            String dir = switch (dirKey) {
                case "us"  -> usOutputDir;
                default    -> krDataDir;  // "kr"
            };
            File f = Paths.get(dir, def.get("file")).toFile();

            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("name", def.get("name"));
            entry.put("path", def.get("file"));
            entry.put("exists", f.exists());
            entry.put("lastModified", f.exists()
                    ? FMT.format(Instant.ofEpochMilli(f.lastModified()))
                    : null);
            entry.put("size", f.exists() ? formatSize(f.length()) : "0 B");
            entry.put("link", def.get("menu"));
            entry.put("menu", def.get("menu"));

            // rowCount for CSV
            if (f.exists() && def.get("file").endsWith(".csv")) {
                try {
                    long lines = java.nio.file.Files.lines(f.toPath()).count();
                    entry.put("rowCount", (int) Math.max(0, lines - 1)); // 헤더 제외
                } catch (Exception ignored) {}
            }

            files.add(entry);
        }

        long totalFiles = files.stream().filter(f -> Boolean.TRUE.equals(f.get("exists"))).count();
        String lastUpdate = files.stream()
                .filter(f -> f.get("lastModified") != null)
                .map(f -> (String) f.get("lastModified"))
                .max(Comparator.naturalOrder())
                .orElse(null);

        return Map.of(
                "files", files,
                "total_files", totalFiles,
                "last_update", lastUpdate != null ? lastUpdate : "N/A",
                "timestamp", FMT.format(Instant.now())
        );
    }

    // ── SSE: /api/system/update-data-stream ─────────────────────────────────────

    @GetMapping(value = "/update-data-stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter updateDataStream() {
        SseEmitter emitter = new SseEmitter(120_000L);
        ExecutorService exec = Executors.newSingleThreadExecutor();
        exec.execute(() -> {
            try {
                emitter.send(SseEmitter.event().data("Starting full data update via Flask scheduler..."));
                // Flask trigger
                try {
                    java.net.http.HttpClient client = java.net.http.HttpClient.newHttpClient();
                    java.net.http.HttpRequest req = java.net.http.HttpRequest.newBuilder()
                            .uri(java.net.URI.create(flaskBaseUrl + "/api/system/trigger-update"))
                            .POST(java.net.http.HttpRequest.BodyPublishers.noBody())
                            .build();
                    java.net.http.HttpResponse<String> resp = client.send(req,
                            java.net.http.HttpResponse.BodyHandlers.ofString());
                    emitter.send(SseEmitter.event().data("Flask trigger: " + resp.statusCode()));
                } catch (Exception e) {
                    emitter.send(SseEmitter.event().data("[WARN] Flask trigger failed: " + e.getMessage()));
                    emitter.send(SseEmitter.event().data("Tip: Run scheduler manually via terminal."));
                }
                emitter.send(SseEmitter.event().data("--- Update Complete ---"));
                emitter.send(SseEmitter.event().name("end").data("done"));
                emitter.complete();
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
        });
        exec.shutdown();
        return emitter;
    }

    // ── SSE: /api/system/update-single?type=xxx ─────────────────────────────────

    @GetMapping(value = "/update-single", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter updateSingle(@RequestParam String type) {
        SseEmitter emitter = new SseEmitter(120_000L);
        ExecutorService exec = Executors.newSingleThreadExecutor();
        exec.execute(() -> {
            try {
                emitter.send(SseEmitter.event().data("Starting update: " + type));
                try {
                    java.net.http.HttpClient client = java.net.http.HttpClient.newHttpClient();
                    String body = "{\"type\":\"" + type + "\"}";
                    java.net.http.HttpRequest req = java.net.http.HttpRequest.newBuilder()
                            .uri(java.net.URI.create(flaskBaseUrl + "/api/system/update-single"))
                            .header("Content-Type", "application/json")
                            .POST(java.net.http.HttpRequest.BodyPublishers.ofString(body))
                            .build();
                    java.net.http.HttpResponse<String> resp = client.send(req,
                            java.net.http.HttpResponse.BodyHandlers.ofString());
                    emitter.send(SseEmitter.event().data("Flask response (" + resp.statusCode() + "): " + resp.body().substring(0, Math.min(200, resp.body().length()))));
                } catch (Exception e) {
                    emitter.send(SseEmitter.event().data("[WARN] Flask call failed: " + e.getMessage()));
                }
                emitter.send(SseEmitter.event().data("--- Update Complete ---"));
                emitter.send(SseEmitter.event().name("end").data("done"));
                emitter.complete();
            } catch (Exception e) {
                emitter.completeWithError(e);
            }
        });
        exec.shutdown();
        return emitter;
    }

    // ── helpers ──────────────────────────────────────────────────────────────────

    private String formatSize(long bytes) {
        if (bytes < 1024) return bytes + " B";
        if (bytes < 1024 * 1024) return new DecimalFormat("0.0").format(bytes / 1024.0) + " KB";
        return new DecimalFormat("0.0").format(bytes / (1024.0 * 1024)) + " MB";
    }
}
