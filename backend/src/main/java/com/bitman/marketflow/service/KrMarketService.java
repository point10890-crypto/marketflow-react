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
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;

@Service
public class KrMarketService {

    private static final Logger log = LoggerFactory.getLogger(KrMarketService.class);

    private final JsonFileReader jsonReader;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    private final String dataDir;

    public KrMarketService(
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

    // ── market-gate (JSON cache → Flask fallback) ─────────────────────────────

    @Cacheable(value = "krMarketGate", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getMarketGate() {
        Map<String, Object> cached = jsonReader.read("data/market_gate_cache.json");
        if (cached != null) {
            log.debug("KR market gate loaded from cache file");
            return cached;
        }
        return flaskFallback("/api/kr/market-gate",
                Map.of("status", "NEUTRAL", "score", 50, "label", "NEUTRAL",
                        "sectors", List.of(), "kospi_close", 0, "kospi_change_pct", 0,
                        "kosdaq_close", 0, "kosdaq_change_pct", 0));
    }

    // ── signals (Flask fallback — jongga_v2 live data) ────────────────────────

    @Cacheable(value = "krSignals", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getSignals() {
        return flaskFallback("/api/kr/signals",
                Map.of("signals", List.of(), "date", "", "filtered_count", 0));
    }

    // ── backtest-summary (Flask fallback — CSV/DB computation) ────────────────

    @Cacheable(value = "krBacktestSummary", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getBacktestSummary() {
        return flaskFallback("/api/kr/backtest-summary",
                Map.of("vcp", Map.of("status", "N/A", "count", 0, "win_rate", 0, "avg_return", 0),
                        "closing_bet", Map.of("status", "N/A", "count", 0, "win_rate", 0, "avg_return", 0)));
    }

    // ── ai-analysis (Flask fallback) ──────────────────────────────────
    @Cacheable(value = "krAIAnalysis", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getAIAnalysis() {
        return flaskFallback("/api/kr/ai-analysis",
                Map.of("analysis", "", "updated_at", ""));
    }

    // ── vcp-stats (Flask fallback) ────────────────────────────────────
    @Cacheable(value = "krVcpStats", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getVcpStats() {
        return flaskFallback("/api/kr/vcp-stats",
                Map.of("total_signals", 0, "win_rate", 0, "avg_return_pct", 0));
    }

    // ── vcp-history (Flask fallback — query param) ────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getVcpHistory(int days) {
        try {
            log.debug("KR vcp-history: proxying to Flask");
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + "/api/kr/vcp-history?days=" + days, Map.class);
            return result != null ? result : Map.of("signals", List.of());
        } catch (Exception e) {
            log.warn("Flask fallback failed for vcp-history: {}", e.getMessage());
            return Map.of("signals", List.of());
        }
    }

    // ── realtime-prices (Flask fallback — POST proxy) ─────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getRealtimePrices(Map<String, Object> body) {
        try {
            log.debug("KR realtime-prices: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/kr/realtime-prices", body, Map.class);
            return result != null ? result : Map.of("prices", Map.of());
        } catch (Exception e) {
            log.warn("Flask fallback failed for realtime-prices: {}", e.getMessage());
            return Map.of("prices", Map.of());
        }
    }

    // ── vcp-enhanced (JSON file → Flask fallback) ─────────────────────────────
    @SuppressWarnings("unchecked")
    public Map<String, Object> getVCPEnhanced() {
        File f = new File(dataDir, "vcp_kr_latest.json");
        if (f.exists()) {
            try {
                Map<String, Object> d = jsonReader.read(f.getAbsolutePath());
                if (d != null) return d;
            } catch (Exception e) { log.warn("vcp_kr_latest.json read failed: {}", e.getMessage()); }
        }
        return flaskFallback("/api/kr/vcp-enhanced", Map.of("signals", List.of()));
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
                    flaskBaseUrl + "/api/" + market + "/vcp-enhanced/history/" + dateStr, Map.class);
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
            log.debug("KR {}: proxying to Flask", path);
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + path, Map.class);
            return result != null ? result : defaultResponse;
        } catch (Exception e) {
            log.warn("Flask fallback failed for {}: {}", path, e.getMessage());
            return defaultResponse;
        }
    }
}
