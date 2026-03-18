package com.bitman.marketflow.service;

import com.bitman.marketflow.entity.ScreenerResultEntity;
import com.bitman.marketflow.entity.SignalEntity;
import com.bitman.marketflow.repository.ScreenerResultRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.io.File;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class DataImportService {

    private static final Logger log = LoggerFactory.getLogger(DataImportService.class);
    private static final Pattern DATE_PATTERN = Pattern.compile("jongga_v2_results_(\\d{8})\\.json");

    private final ScreenerResultRepository repository;
    private final ObjectMapper mapper;
    private final String dataDir;

    public DataImportService(
            ScreenerResultRepository repository,
            ObjectMapper mapper,
            @Value("${app.data.kr-data-dir}") String dataDir) {
        this.repository = repository;
        this.mapper = mapper;
        this.dataDir = dataDir;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void onStartup() {
        log.info("=== DataImport: scanning {} for JSON files ===", dataDir);
        importAllJsonFiles();
    }

    @Scheduled(fixedDelay = 60_000, initialDelay = 120_000)
    public void syncNewFiles() {
        importAllJsonFiles();
    }

    /**
     * 각 파일을 개별 트랜잭션으로 임포트.
     * repository.save()는 SimpleJpaRepository의 @Transactional로 자체 커밋.
     * 하나의 파일 실패가 다른 파일 임포트에 영향을 주지 않음.
     */
    public void importAllJsonFiles() {
        int imported = 0;
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(
                Paths.get(dataDir), "jongga_v2_results_*.json")) {
            for (Path p : stream) {
                if (Files.size(p) < 500) continue;

                Matcher m = DATE_PATTERN.matcher(p.getFileName().toString());
                if (!m.matches()) continue;

                String dateStr = m.group(1);
                LocalDate date = LocalDate.parse(dateStr, DateTimeFormatter.BASIC_ISO_DATE);

                if (repository.existsByDate(date)) continue;

                try {
                    Map<String, Object> json = mapper.readValue(p.toFile(),
                            new TypeReference<>() {});
                    importOneResult(json, date);
                    imported++;
                } catch (DataIntegrityViolationException e) {
                    log.debug("Date {} already imported by concurrent process", date);
                } catch (Exception e) {
                    log.warn("Failed to import {}: {}", p.getFileName(), e.getMessage());
                }
            }

            importLatestFile();

        } catch (Exception e) {
            log.warn("Failed to scan data directory: {}", e.getMessage());
        }

        if (imported > 0) {
            log.info("DataImport: {} new result(s) imported, total={}", imported, repository.count());
        }
    }

    private void importLatestFile() {
        File latestFile = Paths.get(dataDir, "jongga_v2_latest.json").toFile();
        if (!latestFile.exists()) return;

        try {
            Map<String, Object> json = mapper.readValue(latestFile, new TypeReference<>() {});
            String dateStr = (String) json.get("date");
            if (dateStr == null) return;

            LocalDate date = LocalDate.parse(dateStr);
            if (repository.existsByDate(date)) return;

            importOneResult(json, date);
            log.info("DataImport: imported latest file for date={}", date);
        } catch (DataIntegrityViolationException e) {
            log.debug("Latest file date already imported by concurrent process");
        } catch (Exception e) {
            log.debug("Latest file import skipped: {}", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private void importOneResult(Map<String, Object> json, LocalDate date) {
        ScreenerResultEntity entity = new ScreenerResultEntity();
        entity.setDate(date);
        entity.setTotalCandidates(toInt(json.get("total_candidates")));
        entity.setFilteredCount(toInt(json.get("filtered_count")));
        entity.setProcessingTimeMs(toLong(json.get("processing_time_ms")));

        Object updatedAtObj = json.get("updated_at");
        if (updatedAtObj instanceof String updatedAt) {
            try {
                entity.setUpdatedAt(LocalDateTime.parse(updatedAt));
            } catch (Exception ignored) {}
        }

        entity.setByGradeJson(toJsonString(json.get("by_grade")));
        entity.setByMarketJson(toJsonString(json.get("by_market")));
        entity.setAiPicksJson(toJsonString(json.get("claude_picks")));

        Object signalsObj = json.get("signals");
        if (signalsObj instanceof List<?> rawSignals) {
            for (Object raw : rawSignals) {
                if (raw instanceof Map<?, ?> rawMap) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> s = (Map<String, Object>) rawMap;
                    entity.addSignal(mapSignal(s));
                }
            }
        }

        repository.save(entity);
    }

    @SuppressWarnings("unchecked")
    private SignalEntity mapSignal(Map<String, Object> s) {
        SignalEntity sig = new SignalEntity();

        sig.setStockCode((String) s.get("stock_code"));
        sig.setStockName((String) s.get("stock_name"));
        sig.setMarket((String) s.get("market"));
        sig.setSector((String) s.get("sector"));
        sig.setGrade((String) s.get("grade"));

        sig.setCurrentPrice(toInt(s.get("current_price")));
        sig.setEntryPrice(toInt(s.get("entry_price")));
        sig.setStopPrice(toInt(s.get("stop_price")));
        sig.setTargetPrice(toInt(s.get("target_price")));

        sig.setChangePct(toDouble(s.get("change_pct")));
        sig.setTradingValue(toLong(s.get("trading_value")));
        sig.setVolumeRatio(toDouble(s.get("volume_ratio")));
        sig.setForeign5d(toInt(s.get("foreign_5d")));
        sig.setInst5d(toInt(s.get("inst_5d")));

        sig.setQuantity(toInt(s.get("quantity")));
        sig.setPositionSize(toLong(s.get("position_size")));
        sig.setRValue(toDouble(s.get("r_value")));
        sig.setRMultiplier(toDouble(s.get("r_multiplier")));

        // Score
        Object scoreObj = s.get("score");
        if (scoreObj instanceof Map<?, ?> score) {
            sig.setScoreNews(toInt(score.get("news")));
            sig.setScoreVolume(toInt(score.get("volume")));
            sig.setScoreChart(toInt(score.get("chart")));
            sig.setScoreCandle(toInt(score.get("candle")));
            sig.setScoreConsolidation(toInt(score.get("consolidation")));
            sig.setScoreSupply(toInt(score.get("supply")));
            sig.setScoreDisclosure(toInt(score.get("disclosure")));
            sig.setScoreAnalyst(toInt(score.get("analyst")));
            sig.setScoreTotal(toInt(score.get("total")));
            sig.setScoreLlmReason((String) score.get("llm_reason"));
            sig.setScoreLlmSource((String) score.get("llm_source"));
        }

        // Checklist
        Object clObj = s.get("checklist");
        if (clObj instanceof Map<?, ?> cl) {
            sig.setCheckHasNews(toBool(cl.get("has_news")));
            sig.setCheckVolumeSufficient(toBool(cl.get("volume_sufficient")));
            sig.setCheckIsNewHigh(toBool(cl.get("is_new_high")));
            sig.setCheckIsBreakout(toBool(cl.get("is_breakout")));
            sig.setCheckMaAligned(toBool(cl.get("ma_aligned")));
            sig.setCheckGoodCandle(toBool(cl.get("good_candle")));
            sig.setCheckHasConsolidation(toBool(cl.get("has_consolidation")));
            sig.setCheckSupplyPositive(toBool(cl.get("supply_positive")));
            sig.setCheckHasDisclosure(toBool(cl.get("has_disclosure")));
            sig.setCheckNegativeNews(toBool(cl.get("negative_news")));
            sig.setCheckUpperWickLong(toBool(cl.get("upper_wick_long")));
            sig.setCheckVolumeSuspicious(toBool(cl.get("volume_suspicious")));
            sig.setCheckNewsSourcesJson(toJsonString(cl.get("news_sources")));
            sig.setCheckDisclosureTypesJson(toJsonString(cl.get("disclosure_types")));
        }

        sig.setNewsItemsJson(toJsonString(s.get("news_items")));
        sig.setThemesJson(toJsonString(s.get("themes")));

        return sig;
    }

    // ── Type conversion helpers ─────────────────────────────────────────────

    private int toInt(Object v) {
        if (v instanceof Number n) return n.intValue();
        return 0;
    }

    private Long toLong(Object v) {
        if (v instanceof Number n) return n.longValue();
        return null;
    }

    private Double toDouble(Object v) {
        if (v instanceof Number n) return n.doubleValue();
        return null;
    }

    private boolean toBool(Object v) {
        if (v instanceof Boolean b) return b;
        return false;
    }

    private String toJsonString(Object v) {
        if (v == null) return null;
        try {
            return mapper.writeValueAsString(v);
        } catch (Exception e) {
            return null;
        }
    }
}
