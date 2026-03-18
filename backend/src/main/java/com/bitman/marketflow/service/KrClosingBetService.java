package com.bitman.marketflow.service;

import com.bitman.marketflow.entity.ScreenerResultEntity;
import com.bitman.marketflow.entity.SignalEntity;
import com.bitman.marketflow.repository.ScreenerResultRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.io.File;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
public class KrClosingBetService {

    private static final Logger log = LoggerFactory.getLogger(KrClosingBetService.class);

    private final ScreenerResultRepository repository;
    private final ObjectMapper mapper;
    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;
    private final String dataDir;

    public KrClosingBetService(
            ScreenerResultRepository repository,
            ObjectMapper mapper,
            RestTemplate restTemplate,
            @Value("${app.flask.base-url}") String flaskBaseUrl,
            @Value("${app.data.kr-data-dir}") String dataDir) {
        this.repository = repository;
        this.mapper = mapper;
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
        this.dataDir = dataDir;
    }

    // ── latest: jongga_v2_latest.json 우선, DB 폴백 ─────────────────────────

    @SuppressWarnings("unchecked")
    public Map<String, Object> getLatest() {
        // 1. Read jongga_v2_latest.json directly (always up-to-date)
        File latestFile = Paths.get(dataDir, "jongga_v2_latest.json").toFile();
        if (latestFile.exists()) {
            try {
                Map<String, Object> result = mapper.readValue(latestFile, new TypeReference<Map<String, Object>>() {});
                if (result != null && result.containsKey("signals")) {
                    return result;
                }
            } catch (Exception e) {
                log.warn("Failed to read jongga_v2_latest.json: {}", e.getMessage());
            }
        }
        // 2. Fallback: DB
        return repository.findLatest()
                .map(this::entityToMap)
                .orElse(Map.of("date", LocalDate.now().toString(),
                        "signals", List.of(),
                        "message", "No data available"));
    }

    // ── dates (DB 조회) ────────────────────────────────────────────────────────

    public List<String> getDates() {
        return repository.findAllDatesWithSignals().stream()
                .map(d -> d.format(DateTimeFormatter.ISO_LOCAL_DATE))
                .collect(Collectors.toList());
    }

    // ── history (DB 조회) ──────────────────────────────────────────────────────

    public Map<String, Object> getHistory(String dateStr) {
        String cleanDate = dateStr.replace("-", "");
        LocalDate date = LocalDate.parse(cleanDate, DateTimeFormatter.BASIC_ISO_DATE);
        return repository.findByDate(date)
                .map(this::entityToMap)
                .orElse(null); // null이면 Controller에서 404 처리
    }

    // ── analyze (Flask POST 프록시 — Python engine 의존) ────────────────────────

    @SuppressWarnings("unchecked")
    public Map<String, Object> analyze(Map<String, Object> body) {
        try {
            log.debug("KR jongga-v2/analyze: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/kr/jongga-v2/analyze", body, Map.class);
            return result != null ? result : Map.of("status", "failed", "message", "No response from Flask");
        } catch (Exception e) {
            log.warn("Flask proxy failed for jongga-v2/analyze: {}", e.getMessage());
            return Map.of("status", "error", "error", e.getMessage());
        }
    }

    // ── run (Flask POST 프록시 — Python engine 의존) ────────────────────────────

    @SuppressWarnings("unchecked")
    public Map<String, Object> run() {
        try {
            log.debug("KR jongga-v2/run: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/kr/jongga-v2/run", null, Map.class);
            return result != null ? result : Map.of("status", "error", "message", "No response from Flask");
        } catch (Exception e) {
            log.warn("Flask proxy failed for jongga-v2/run: {}", e.getMessage());
            return Map.of("status", "error", "error", e.getMessage());
        }
    }

    // ── Entity → Map 변환 (프론트엔드 JSON 포맷 유지) ──────────────────────────

    private Map<String, Object> entityToMap(ScreenerResultEntity entity) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("date", entity.getDate().toString());
        map.put("total_candidates", entity.getTotalCandidates());
        map.put("filtered_count", entity.getFilteredCount());
        if (entity.getProcessingTimeMs() != null) {
            map.put("processing_time_ms", entity.getProcessingTimeMs());
        }
        if (entity.getUpdatedAt() != null) {
            map.put("updated_at", entity.getUpdatedAt().toString());
        }

        // JSON CLOB → 원본 구조 복원
        map.put("by_grade", parseJson(entity.getByGradeJson()));
        map.put("by_market", parseJson(entity.getByMarketJson()));
        map.put("claude_picks", parseJson(entity.getAiPicksJson()));

        // signals
        List<Map<String, Object>> signals = entity.getSignals().stream()
                .map(this::signalToMap)
                .collect(Collectors.toList());
        map.put("signals", signals);

        return map;
    }

    private Map<String, Object> signalToMap(SignalEntity sig) {
        Map<String, Object> m = new LinkedHashMap<>();

        m.put("stock_code", sig.getStockCode());
        m.put("stock_name", sig.getStockName());
        m.put("market", sig.getMarket());
        m.put("sector", sig.getSector());
        m.put("grade", sig.getGrade());

        m.put("current_price", sig.getCurrentPrice());
        m.put("entry_price", sig.getEntryPrice());
        m.put("stop_price", sig.getStopPrice());
        m.put("target_price", sig.getTargetPrice());

        m.put("change_pct", sig.getChangePct());
        m.put("trading_value", sig.getTradingValue());
        m.put("volume_ratio", sig.getVolumeRatio());
        m.put("foreign_5d", sig.getForeign5d());
        m.put("inst_5d", sig.getInst5d());

        m.put("quantity", sig.getQuantity());
        m.put("position_size", sig.getPositionSize());
        m.put("r_value", sig.getRValue());
        m.put("r_multiplier", sig.getRMultiplier());

        // score (nested object)
        Map<String, Object> score = new LinkedHashMap<>();
        score.put("news", sig.getScoreNews());
        score.put("volume", sig.getScoreVolume());
        score.put("chart", sig.getScoreChart());
        score.put("candle", sig.getScoreCandle());
        score.put("consolidation", sig.getScoreConsolidation());
        score.put("supply", sig.getScoreSupply());
        score.put("disclosure", sig.getScoreDisclosure());
        score.put("analyst", sig.getScoreAnalyst());
        score.put("total", sig.getScoreTotal());
        score.put("llm_reason", sig.getScoreLlmReason());
        score.put("llm_source", sig.getScoreLlmSource());
        m.put("score", score);

        // checklist (nested object)
        Map<String, Object> cl = new LinkedHashMap<>();
        cl.put("has_news", sig.isCheckHasNews());
        cl.put("volume_sufficient", sig.isCheckVolumeSufficient());
        cl.put("is_new_high", sig.isCheckIsNewHigh());
        cl.put("is_breakout", sig.isCheckIsBreakout());
        cl.put("ma_aligned", sig.isCheckMaAligned());
        cl.put("good_candle", sig.isCheckGoodCandle());
        cl.put("has_consolidation", sig.isCheckHasConsolidation());
        cl.put("supply_positive", sig.isCheckSupplyPositive());
        cl.put("has_disclosure", sig.isCheckHasDisclosure());
        cl.put("negative_news", sig.isCheckNegativeNews());
        cl.put("upper_wick_long", sig.isCheckUpperWickLong());
        cl.put("volume_suspicious", sig.isCheckVolumeSuspicious());
        cl.put("news_sources", parseJson(sig.getCheckNewsSourcesJson()));
        cl.put("disclosure_types", parseJson(sig.getCheckDisclosureTypesJson()));
        m.put("checklist", cl);

        // news_items, themes (JSON CLOB → 원본 구조)
        m.put("news_items", parseJson(sig.getNewsItemsJson()));
        m.put("themes", parseJson(sig.getThemesJson()));

        return m;
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return mapper.readValue(json, new TypeReference<Object>() {});
        } catch (Exception e) {
            log.debug("Failed to parse JSON: {}", e.getMessage());
            return null;
        }
    }
}
