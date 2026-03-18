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

import java.util.*;
import java.util.ArrayList;
import java.util.Collections;

@Service
public class UsMarketService {

    private static final Logger log = LoggerFactory.getLogger(UsMarketService.class);
    private static final String US_OUTPUT = "us_market/output";

    private final JsonFileReader jsonReader;
    private final ObjectMapper objectMapper;
    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    private final String dataDir;

    public UsMarketService(
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

    // ── market-briefing (JSON file merge) ──────────────────────────────────────

    @Cacheable(value = "usMarketBriefing", key = "'latest'")
    public Map<String, Object> getMarketBriefing() {
        Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "market_briefing.json");
        if (data == null) data = new HashMap<>();
        else data = new HashMap<>(data);

        enrichAiAnalysis(data);
        enrichVix(data);
        enrichFearGreed(data);
        enrichSmartMoney(data);

        if (data.isEmpty()) {
            data.put("ai_analysis", Map.of("content", "", "citations", List.of()));
            data.put("vix", Map.of());
            data.put("fear_greed", Map.of());
        }
        return data;
    }

    // ── portfolio (snapshot → Flask fallback) ───────────────────────────────────

    @Cacheable(value = "usPortfolio", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getPortfolio() {
        // 스냅샷 파일 우선 (Flask가 생성한 portfolio_snapshot.json)
        Map<String, Object> snapshot = jsonReader.readFromDir(US_OUTPUT, "portfolio_snapshot.json");
        if (snapshot != null && !snapshot.isEmpty()) {
            log.debug("US portfolio loaded from snapshot file");
            return snapshot;
        }
        return flaskFallback("/api/us/portfolio",
                Map.of("market_indices", List.of(), "timestamp", ""));
    }

    // ── market-gate (Flask fallback — yfinance + market_gate module) ────────────

    @Cacheable(value = "usMarketGate", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getMarketGate() {
        return flaskFallback("/api/us/market-gate",
                Map.of("gate", "NEUTRAL", "score", 50, "status", "NEUTRAL", "sectors", List.of()));
    }

    // ── decision-signal (snapshot → Flask fallback) ─────────────────────────────

    @Cacheable(value = "usDecisionSignal", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getDecisionSignal() {
        // 스냅샷 파일 우선 (Flask가 생성한 decision_signal_snapshot.json)
        Map<String, Object> snapshot = jsonReader.readFromDir(US_OUTPUT, "decision_signal_snapshot.json");
        if (snapshot != null && !snapshot.isEmpty()) {
            log.debug("US decision-signal loaded from snapshot file");
            return snapshot;
        }
        return flaskFallback("/api/us/decision-signal",
                Map.of("action", "HOLD", "score", 50, "components", Map.of()));
    }

    // ── market-regime (JSON file read) ──────────────────────────────────────────

    @Cacheable(value = "usMarketRegime", key = "'latest'")
    public Map<String, Object> getMarketRegime() {
        Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "regime_config.json");
        return data != null ? data : Map.of("regime", "unknown", "confidence", 0);
    }

    // ── index-prediction (JSON file read) ───────────────────────────────────────

    @Cacheable(value = "usIndexPrediction", key = "'latest'")
    public Map<String, Object> getIndexPrediction() {
        Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "index_prediction.json");
        return data != null ? data : Map.of("predictions", Map.of());
    }

    // ── risk-alerts (JSON file read) ────────────────────────────────────────────

    @Cacheable(value = "usRiskAlerts", key = "'latest'")
    public Map<String, Object> getRiskAlerts() {
        Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "risk_alerts.json");
        return data != null ? data : Map.of("alerts", List.of(), "portfolio_summary", Map.of());
    }

    // ── sector-rotation (JSON file read) ────────────────────────────────────────

    @Cacheable(value = "usSectorRotation", key = "'latest'")
    public Map<String, Object> getSectorRotation() {
        Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "sector_rotation.json");
        return data != null ? data : Map.of("rotation_signals", Map.of());
    }

    // ── cumulative-performance (Flask fallback — yfinance + CSV) ────────────────

    @Cacheable(value = "usCumulativePerformance", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getCumulativePerformance() {
        return flaskFallback("/api/us/cumulative-performance",
                Map.of("summary", Map.of(), "chart_data", List.of()));
    }

    // ── super-performance (Flask fallback — VCP screener) ─────────────────────

    @Cacheable(value = "usSuperPerformance", key = "'latest'")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getSuperPerformance() {
        return flaskFallback("/api/us/super-performance",
                Map.of("stocks", List.of(), "source", ""));
    }

    // ── New endpoints (Flask fallback) ──────────────────────────────────────────

    public Map<String, Object> getSmartMoney() {
        try {
            Map<String, Object> snapshot = jsonReader.readFromDir(US_OUTPUT, "smart_money_snapshot.json");
            if (snapshot != null && !snapshot.isEmpty()) return snapshot;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/smart-money", Map.of("picks", List.of()));
    }

    public Map<String, Object> getSmartMoneyDetail(String ticker) {
        return flaskFallback("/api/us/smart-money/" + ticker + "/detail", Map.of());
    }

    public Map<String, Object> getEarningsImpact() {
        return flaskFallback("/api/us/earnings-impact", Map.of("sector_profiles", Map.of(), "upcoming_earnings", List.of()));
    }

    public Map<String, Object> getBacktest() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "backtest_results.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/backtest", Map.of());
    }

    public Map<String, Object> getTopPicksReport() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "final_top10_report.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/top-picks-report", Map.of());
    }

    public Map<String, Object> getEtfFlows() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "etf_flows.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/etf-flows", Map.of());
    }

    public Map<String, Object> getVCPEnhanced() {
        return flaskFallback("/api/us/vcp-enhanced", Map.of("signals", List.of()));
    }

    public Map<String, Object> getAiSummary(String ticker) {
        return flaskFallback("/api/us/ai-summary/" + ticker, Map.of());
    }

    public Map<String, Object> getHeatmapData() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "sector_heatmap.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/heatmap-data", Map.of("series", List.of()));
    }

    public Map<String, Object> getNewsAnalysis() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "news_analysis.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/news-analysis", Map.of());
    }

    public Map<String, Object> getMacroAnalysis() {
        try {
            Map<String, Object> data = jsonReader.readFromDir(US_OUTPUT, "macro_analysis.json");
            if (data != null && !data.isEmpty()) return data;
        } catch (Exception ignored) {}
        return flaskFallback("/api/us/macro-analysis", Map.of());
    }

    // ── vcp-dates ──────────────────────────────────────────────────────────────
    @SuppressWarnings("unchecked")
    public List<String> getVcpDates(String market) {
        String prefix = "vcp_" + market + "_";
        java.io.File dir = new java.io.File(dataDir);
        java.io.File[] files = dir.listFiles((d, n) -> n.startsWith(prefix) && n.endsWith(".json") && !n.contains("latest"));
        if (files != null && files.length > 0) {
            List<String> dates = new ArrayList<>();
            for (java.io.File f : files) {
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
        java.io.File f = new java.io.File(dataDir, "vcp_" + market + "_" + clean + ".json");
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

    // ── Private helpers ─────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> flaskFallback(String path, Map<String, Object> defaultResponse) {
        try {
            Map<String, Object> result = restTemplate.getForObject(
                    flaskBaseUrl + path, Map.class);
            return result != null ? result : defaultResponse;
        } catch (Exception e) {
            log.warn("Flask fallback failed for {}: {}", path, e.getMessage());
            return defaultResponse;
        }
    }

    @SuppressWarnings("unchecked")
    private void enrichAiAnalysis(Map<String, Object> data) {
        Map<String, Object> ai = (Map<String, Object>) data.getOrDefault("ai_analysis", Map.of());
        Object content = ai.get("content");
        if (content == null || content.toString().isEmpty()) {
            Map<String, Object> briefing = jsonReader.readFromDir(US_OUTPUT, "briefing.json");
            if (briefing != null) {
                data.put("ai_analysis", Map.of(
                        "content", briefing.getOrDefault("content", ""),
                        "citations", briefing.getOrDefault("citations", List.of())
                ));
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void enrichVix(Map<String, Object> data) {
        Map<String, Object> vix = (Map<String, Object>) data.get("vix");
        if (vix == null || vix.get("value") == null) {
            Map<String, Object> marketData = jsonReader.readFromDir(US_OUTPUT, "market_data.json");
            if (marketData != null) {
                Map<String, Object> volatility = (Map<String, Object>) marketData.getOrDefault("volatility", Map.of());
                Map<String, Object> vixData = (Map<String, Object>) volatility.getOrDefault("^VIX", Map.of());
                double val = toDouble(vixData.get("current"), 0);
                double change = toDouble(vixData.get("change_pct"), 0);
                String level = val < 15 ? "Low" : (val > 25 ? "High" : "Neutral");
                String color = val < 15 ? "#4CAF50" : (val > 25 ? "#F44336" : "#FFC107");
                data.put("vix", Map.of("value", val, "change", change, "level", level, "color", color));
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void enrichFearGreed(Map<String, Object> data) {
        Object fgObj = data.get("fear_greed");
        if (fgObj instanceof Map) {
            Map<String, Object> fg = new HashMap<>((Map<String, Object>) fgObj);
            if (!fg.containsKey("color")) {
                int score = toInt(fg.get("score"), 50);
                fg.put("color", score >= 60 ? "green" : (score <= 40 ? "red" : "yellow"));
                data.put("fear_greed", fg);
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void enrichSmartMoney(Map<String, Object> data) {
        Map<String, Object> sm = (Map<String, Object>) data.get("smart_money");
        if (sm == null) sm = new HashMap<>();
        else sm = new HashMap<>(sm);

        if (!sm.containsKey("top_picks")) {
            Map<String, Object> tp = jsonReader.readFromDir(US_OUTPUT, "top_picks.json");
            if (tp != null) {
                Object picksObj = tp.getOrDefault("top_picks", tp.get("picks"));
                if (picksObj instanceof List<?> picks) {
                    List<Map<String, Object>> mappedPicks = new ArrayList<>();
                    for (Object p : picks) {
                        if (p instanceof Map) {
                            Map<String, Object> pick = new HashMap<>((Map<String, Object>) p);
                            if (pick.containsKey("composite_score") && !pick.containsKey("final_score")) {
                                pick.put("final_score", pick.remove("composite_score"));
                            }
                            if (pick.containsKey("signal") && !pick.containsKey("ai_recommendation")) {
                                pick.put("ai_recommendation", pick.remove("signal"));
                            }
                            mappedPicks.add(pick);
                        }
                    }
                    sm.put("top_picks", Map.of("picks", mappedPicks));
                    data.put("smart_money", sm);
                }
            }
        }
    }

    private static double toDouble(Object val, double defaultVal) {
        if (val == null) return defaultVal;
        if (val instanceof Number n) return n.doubleValue();
        try { return Double.parseDouble(val.toString()); } catch (Exception e) { return defaultVal; }
    }

    private static int toInt(Object val, int defaultVal) {
        if (val == null) return defaultVal;
        if (val instanceof Number n) return n.intValue();
        try { return Integer.parseInt(val.toString()); } catch (Exception e) { return defaultVal; }
    }
}
