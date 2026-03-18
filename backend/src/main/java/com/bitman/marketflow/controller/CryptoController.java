package com.bitman.marketflow.controller;

import com.bitman.marketflow.service.CryptoService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/crypto")
public class CryptoController {

    private final CryptoService service;

    public CryptoController(CryptoService service) {
        this.service = service;
    }

    @GetMapping("/dominance")
    public ResponseEntity<Map<String, Object>> getDominance() {
        return cached(service.getDominance());
    }

    @GetMapping("/overview")
    public ResponseEntity<Map<String, Object>> getOverview() {
        return cached(service.getOverview());
    }

    @GetMapping("/market-gate")
    public ResponseEntity<Map<String, Object>> getMarketGate() {
        return cached(service.getMarketGate());
    }

    @GetMapping("/gate-history")
    public ResponseEntity<Map<String, Object>> getGateHistory() {
        return cached(service.getGateHistory());
    }

    @GetMapping("/briefing")
    public ResponseEntity<Map<String, Object>> getBriefing() {
        return cached(service.getBriefing());
    }

    @GetMapping("/vcp-signals")
    public ResponseEntity<Map<String, Object>> getVcpSignals(
            @RequestParam(defaultValue = "50") int limit) {
        return cached(service.getVcpSignals(limit));
    }

    @PostMapping("/run-scan")
    public ResponseEntity<Map<String, Object>> runScan() {
        return cached(service.runScan());
    }

    @GetMapping("/task-status")
    public ResponseEntity<Map<String, Object>> getTaskStatus() {
        return cached(service.getTaskStatus());
    }

    @PostMapping("/signal-analysis")
    public ResponseEntity<Map<String, Object>> signalAnalysis(
            @RequestBody Map<String, Object> body) {
        return ResponseEntity.ok(service.signalAnalysis(body));
    }

    @GetMapping("/prediction")
    public ResponseEntity<Map<String, Object>> getPrediction() {
        return cached(service.getPrediction());
    }

    @GetMapping("/prediction-history")
    public ResponseEntity<Map<String, Object>> getPredictionHistory() {
        return cached(service.getPredictionHistory());
    }

    @GetMapping("/risk")
    public ResponseEntity<Map<String, Object>> getRisk() {
        return cached(service.getRisk());
    }

    @GetMapping("/lead-lag")
    public ResponseEntity<Map<String, Object>> getLeadLag() {
        return cached(service.getLeadLag());
    }

    @GetMapping("/vcp-enhanced")
    public ResponseEntity<Map<String, Object>> getVCPEnhanced() {
        return cached(service.getVCPEnhanced());
    }

    @GetMapping("/backtest-summary")
    public ResponseEntity<Map<String, Object>> getBacktestSummary() {
        return cached(service.getBacktestSummary());
    }

    @GetMapping("/backtest-results")
    public ResponseEntity<Map<String, Object>> getBacktestResults() {
        return cached(service.getBacktestResults());
    }

    @GetMapping("/data-status")
    public ResponseEntity<Map<String, Object>> getDataStatus() {
        return cached(service.getDataStatus());
    }

    @PostMapping("/run-gate")
    public ResponseEntity<Map<String, Object>> runGate() {
        return ResponseEntity.ok(service.runGate());
    }

    @PostMapping("/run-prediction")
    public ResponseEntity<Map<String, Object>> runPrediction() {
        return ResponseEntity.ok(service.runPrediction());
    }

    @PostMapping("/run-risk")
    public ResponseEntity<Map<String, Object>> runRisk() {
        return ResponseEntity.ok(service.runRisk());
    }

    @PostMapping("/run-briefing")
    public ResponseEntity<Map<String, Object>> runBriefing() {
        return ResponseEntity.ok(service.runBriefing());
    }

    @PostMapping("/run-leadlag")
    public ResponseEntity<Map<String, Object>> runLeadLag() {
        return ResponseEntity.ok(service.runLeadLag());
    }

    @GetMapping("/vcp-dates")
    public ResponseEntity<List<String>> getVcpDates() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(service.getVcpDates("crypto"));
    }

    @GetMapping("/vcp-report/{dateStr}")
    public ResponseEntity<?> getVcpReport(@PathVariable String dateStr) {
        Map<String, Object> data = service.getVcpReport("crypto", dateStr);
        if (data == null) return ResponseEntity.notFound().build();
        return cached(data);
    }

    private ResponseEntity<Map<String, Object>> cached(Map<String, Object> body) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(body);
    }
}
