package com.bitman.marketflow.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.File;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestController
public class HealthController {

    @Value("${app.data.kr-data-dir}")
    private String dataDir;

    @Value("${app.data.us-output-dir}")
    private String usOutputDir;

    @GetMapping("/api/health")
    public Map<String, Object> health() {
        return Map.of(
                "status", "ok",
                "service", "spring-boot",
                "timestamp", LocalDateTime.now().toString()
        );
    }

    /**
     * 파일 수정 시간 기반 버전 체크 엔드포인트
     * useSmartRefresh 훅이 15초마다 polling하여 데이터 변경 감지
     */
    @GetMapping("/api/data-version")
    public Map<String, Object> dataVersion() {
        Map<String, Long> versions = new HashMap<>();

        // KR 데이터 파일 감시
        String[] krFiles = {
            "jongga_v2_latest.json",
            "kr_market_gate.json",
            "kr_signals.json",
            "kr_vcp_enhanced.json"
        };
        for (String fname : krFiles) {
            File f = Paths.get(dataDir, fname).toFile();
            versions.put(fname, f.exists() ? f.lastModified() : 0L);
        }

        // US 데이터 파일 감시
        String[] usFiles = {
            "briefing.json",
            "market_data.json",
            "top_picks.json",
            "sector_heatmap.json",
            "prediction.json"
        };
        for (String fname : usFiles) {
            File f = Paths.get(usOutputDir, fname).toFile();
            versions.put(fname, f.exists() ? f.lastModified() : 0L);
        }

        return Map.of(
                "versions", versions,
                "timestamp", System.currentTimeMillis()
        );
    }
}
