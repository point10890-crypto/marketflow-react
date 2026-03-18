package com.bitman.marketflow.service;

import com.bitman.marketflow.util.JsonFileReader;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

@Service
public class CryptoService {

    private static final Logger log = LoggerFactory.getLogger(CryptoService.class);
    private static final String CRYPTO_OUTPUT = "data/crypto";

    private final JsonFileReader jsonReader;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;
    private final String dataDir;

    public CryptoService(
            JsonFileReader jsonReader,
            ObjectMapper objectMapper,
            RestTemplate restTemplate,
            @Value("${app.flask.base-url}") String flaskBaseUrl,
            @Value("${app.data.kr-data-dir}") String dataDir) {
        this.jsonReader = jsonReader;
        this.objectMapper = objectMapper;
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
        this.dataDir = dataDir;
    }

    // ── dominance (JSON cache → Flask fallback) ───────────────────────────────

    @Cacheable(value = "cryptoDominance", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getDominance() {
        Map<String, Object> cached = jsonReader.read("data/crypto_dominance_cache.json");
        if (cached != null) {
            log.debug("Crypto dominance loaded from cache file");
            return cached;
        }
        return flaskFallback("/api/crypto/dominance",
                Map.of("btc_price", 0, "eth_price", 0, "btc_rsi", 50,
                        "btc_30d_change", 0, "sentiment", "NEUTRAL"));
    }

    // ── overview (snapshot → Flask fallback) ──────────────────────────────────

    @Cacheable(value = "cryptoOverview", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getOverview() {
        // 스냅샷 파일 우선 (Flask가 생성한 overview_snapshot.json)
        Map<String, Object> snapshot = jsonReader.readFromDir(
                "crypto-analytics/crypto_market/output", "overview_snapshot.json");
        if (snapshot != null && !snapshot.isEmpty()) {
            log.debug("Crypto overview loaded from snapshot file");
            return snapshot;
        }
        return flaskFallback("/api/crypto/overview",
                Map.of("cryptos", List.of(), "timestamp", ""));
    }

    // ── market-gate (JSON cache → Flask fallback) ─────────────────────────────

    @Cacheable(value = "cryptoMarketGate", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getMarketGate() {
        Map<String, Object> cached = jsonReader.readFromDir(CRYPTO_OUTPUT, "market_gate.json");
        if (cached != null) {
            log.debug("Crypto market gate loaded from cache file");
            return cached;
        }
        return flaskFallback("/api/crypto/market-gate",
                Map.of("gate", "YELLOW", "score", 50, "status", "NEUTRAL", "reasons", List.of()));
    }

    // ── gate-history (JSON file read → Flask fallback) ────────────────────────

    @Cacheable(value = "cryptoGateHistory", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getGateHistory() {
        Map<String, Object> cached = jsonReader.readFromDir(CRYPTO_OUTPUT, "gate_history.json");
        if (cached != null) {
            log.debug("Crypto gate history loaded from cache file");
            return cached;
        }
        return flaskFallback("/api/crypto/gate-history",
                Map.of("history", List.of()));
    }

    // ── briefing (JSON cache → Flask fallback) ────────────────────────────────

    @Cacheable(value = "cryptoBriefing", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getBriefing() {
        Map<String, Object> cached = jsonReader.readFromDir(CRYPTO_OUTPUT, "briefing.json");
        if (cached != null) {
            log.debug("Crypto briefing loaded from cache file");
            return cached;
        }
        return flaskFallback("/api/crypto/briefing",
                Map.of("market_summary", Map.of(), "fear_greed", Map.of("score", 0, "level", "N/A"),
                        "major_coins", Map.of(), "timestamp", ""));
    }

    // ── vcp-signals (Flask fallback — with query param) ───────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getVcpSignals(int limit) {
        try {
            log.debug("Crypto vcp-signals: proxying to Flask");
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + "/api/crypto/vcp-signals?limit=" + limit, Map.class);
            return result != null ? result : Map.of("signals", List.of(), "count", 0);
        } catch (Exception e) {
            log.warn("Flask fallback failed for vcp-signals: {}", e.getMessage());
            return Map.of("signals", List.of(), "count", 0);
        }
    }

    // ── run-scan (Flask fallback — POST proxy) ────────────────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> runScan() {
        try {
            log.debug("Crypto run-scan: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/run-scan", null, Map.class);
            return result != null ? result : Map.of("status", "error", "message", "Failed to trigger scan");
        } catch (Exception e) {
            log.warn("Flask fallback failed for run-scan: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    // ── task-status (Flask fallback) ──────────────────────────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getTaskStatus() {
        return flaskFallback("/api/crypto/task-status",
                Map.of("tasks", Map.of()));
    }

    // ── signal-analysis (Flask POST proxy — OpenAI GPT call) ──────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> signalAnalysis(Map<String, Object> body) {
        try {
            log.debug("Crypto signal-analysis: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/signal-analysis", body, Map.class);
            return result != null ? result : Map.of("error", "No response from Flask");
        } catch (Exception e) {
            log.warn("Flask proxy failed for signal-analysis: {}", e.getMessage());
            return Map.of("error", e.getMessage());
        }
    }

    // ── New endpoints (Flask fallback) ────────────────────────────────────────

    public Map<String, Object> getPrediction() { return flaskFallback("/api/crypto/prediction", Map.of()); }
    public Map<String, Object> getPredictionHistory() { return flaskFallback("/api/crypto/prediction-history", Map.of("history", List.of())); }
    public Map<String, Object> getRisk() { return flaskFallback("/api/crypto/risk", Map.of()); }
    public Map<String, Object> getLeadLag() { return flaskFallback("/api/crypto/lead-lag", Map.of()); }
    public Map<String, Object> getVCPEnhanced() { return flaskFallback("/api/crypto/vcp-enhanced", Map.of("signals", List.of())); }
    public Map<String, Object> getBacktestSummary() { return flaskFallback("/api/crypto/backtest-summary", Map.of()); }
    public Map<String, Object> getBacktestResults() { return flaskFallback("/api/crypto/backtest-results", Map.of()); }
    public Map<String, Object> getDataStatus() { return flaskFallback("/api/crypto/data-status", Map.of()); }

    @SuppressWarnings("unchecked")
    public Map<String, Object> runGate() {
        try {
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/gate-scan", null, Map.class);
            return result != null ? result : Map.of("status", "error");
        } catch (Exception e) {
            log.warn("Flask proxy failed for run-gate: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> runPrediction() {
        try {
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/run-prediction", null, Map.class);
            return result != null ? result : Map.of("status", "error");
        } catch (Exception e) {
            log.warn("Flask proxy failed for run-prediction: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> runRisk() {
        try {
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/run-risk", null, Map.class);
            return result != null ? result : Map.of("status", "error");
        } catch (Exception e) {
            log.warn("Flask proxy failed for run-risk: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> runBriefing() {
        try {
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/run-briefing", null, Map.class);
            return result != null ? result : Map.of("status", "error");
        } catch (Exception e) {
            log.warn("Flask proxy failed for run-briefing: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> runLeadLag() {
        try {
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/crypto/run-leadlag", null, Map.class);
            return result != null ? result : Map.of("status", "error");
        } catch (Exception e) {
            log.warn("Flask proxy failed for run-leadlag: {}", e.getMessage());
            return Map.of("status", "error", "message", e.getMessage());
        }
    }

    // ── vcp-dates ──────────────────────────────────────────────────────────────
    @SuppressWarnings("unchecked")
    public List<String> getVcpDates(String market) {
        String prefix = "vcp_" + market + "_";
        File dir = new File(dataDir);
        File[] files = dir.listFiles((d, n) -> n.startsWith(prefix) && n.endsWith(".json") && !n.contains("latest"));
        if (files != null && files.length > 0) {
            List<String> dates = new ArrayList<>();
            for (File f : files) {
                String raw = f.getName().replace(prefix, "").replace(".json", "");
                if (raw.length() == 8) dates.add(raw.substring(0,4) + "-" + raw.substring(4,6) + "-" + raw.substring(6,8));
            }
            dates.sort(Collections.reverseOrder());
            return dates;
        }
        // Flask fallback (cloud 환경)
        try {
            List<String> result = restTemplate.getForObject(
                    flaskBaseUrl + "/api/" + market + "/vcp-enhanced/dates", List.class);
            return result != null ? result : Collections.emptyList();
        } catch (Exception e) {
            log.warn("Flask fallback failed for vcp-dates ({}): {}", market, e.getMessage());
            return Collections.emptyList();
        }
    }

    // ── vcp-report/{date} ──────────────────────────────────────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getVcpReport(String market, String dateStr) {
        String clean = dateStr.replace("-", "");
        File f = new File(dataDir, "vcp_" + market + "_" + clean + ".json");
        if (f.exists()) {
            try {
                return objectMapper.readValue(f, new TypeReference<>() {});
            } catch (Exception e) {
                log.warn("vcp_{} report {} read failed: {}", market, dateStr, e.getMessage());
            }
        }
        // Flask fallback (cloud 환경)
        try {
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + "/api/crypto/vcp-enhanced/history/" + dateStr, Map.class);
            return result;
        } catch (Exception e) {
            log.warn("Flask fallback failed for vcp-report ({}/{}): {}", market, dateStr, e.getMessage());
            return null;
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> flaskFallback(String path, Map<String, Object> defaultResponse) {
        try {
            log.debug("Crypto {}: proxying to Flask", path);
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + path, Map.class);
            return result != null ? result : defaultResponse;
        } catch (Exception e) {
            log.warn("Flask fallback failed for {}: {}", path, e.getMessage());
            return defaultResponse;
        }
    }
}
