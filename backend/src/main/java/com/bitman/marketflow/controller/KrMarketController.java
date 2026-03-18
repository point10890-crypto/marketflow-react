package com.bitman.marketflow.controller;

import com.bitman.marketflow.service.KrMarketService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/kr")
public class KrMarketController {

    private final KrMarketService service;

    public KrMarketController(KrMarketService service) {
        this.service = service;
    }

    @GetMapping("/market-gate")
    public ResponseEntity<Map<String, Object>> getMarketGate() {
        return cached(service.getMarketGate());
    }

    @GetMapping("/signals")
    public ResponseEntity<Map<String, Object>> getSignals() {
        return cached(service.getSignals());
    }

    @GetMapping("/backtest-summary")
    public ResponseEntity<Map<String, Object>> getBacktestSummary() {
        return cached(service.getBacktestSummary());
    }

    @GetMapping("/ai-analysis")
    public ResponseEntity<Map<String, Object>> getAIAnalysis() {
        return cached(service.getAIAnalysis());
    }

    @GetMapping("/vcp-stats")
    public ResponseEntity<Map<String, Object>> getVcpStats() {
        return cached(service.getVcpStats());
    }

    @GetMapping("/vcp-history")
    public ResponseEntity<Map<String, Object>> getVcpHistory(
            @RequestParam(defaultValue = "30") int days) {
        return cached(service.getVcpHistory(days));
    }

    @PostMapping("/realtime-prices")
    public ResponseEntity<Map<String, Object>> getRealtimePrices(
            @RequestBody Map<String, Object> body) {
        return cached(service.getRealtimePrices(body));
    }

    @GetMapping("/vcp-enhanced")
    public ResponseEntity<Map<String, Object>> getVCPEnhanced() {
        return cached(service.getVCPEnhanced());
    }

    @GetMapping("/vcp-dates")
    public ResponseEntity<List<String>> getVcpDates() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(service.getVcpDates("kr"));
    }

    @GetMapping("/vcp-report/{dateStr}")
    public ResponseEntity<?> getVcpReport(@PathVariable String dateStr) {
        Map<String, Object> data = service.getVcpReport("kr", dateStr);
        if (data == null) return ResponseEntity.notFound().build();
        return cached(data);
    }

    private ResponseEntity<Map<String, Object>> cached(Map<String, Object> body) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(body);
    }
}
