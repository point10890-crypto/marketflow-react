package com.bitman.marketflow.controller;

import com.bitman.marketflow.service.UsMarketService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/us")
public class UsMarketController {

    private final UsMarketService service;

    public UsMarketController(UsMarketService service) {
        this.service = service;
    }

    @GetMapping("/market-briefing")
    public ResponseEntity<Map<String, Object>> getMarketBriefing() {
        return cached(service.getMarketBriefing());
    }

    @GetMapping("/portfolio")
    public ResponseEntity<Map<String, Object>> getPortfolio() {
        return cached(service.getPortfolio());
    }

    @GetMapping("/market-gate")
    public ResponseEntity<Map<String, Object>> getMarketGate() {
        return cached(service.getMarketGate());
    }

    @GetMapping("/decision-signal")
    public ResponseEntity<Map<String, Object>> getDecisionSignal() {
        return cached(service.getDecisionSignal());
    }

    @GetMapping("/market-regime")
    public ResponseEntity<Map<String, Object>> getMarketRegime() {
        return cached(service.getMarketRegime());
    }

    @GetMapping("/index-prediction")
    public ResponseEntity<Map<String, Object>> getIndexPrediction() {
        return cached(service.getIndexPrediction());
    }

    @GetMapping("/risk-alerts")
    public ResponseEntity<Map<String, Object>> getRiskAlerts() {
        return cached(service.getRiskAlerts());
    }

    @GetMapping("/sector-rotation")
    public ResponseEntity<Map<String, Object>> getSectorRotation() {
        return cached(service.getSectorRotation());
    }

    @GetMapping("/cumulative-performance")
    public ResponseEntity<Map<String, Object>> getCumulativePerformance() {
        return cached(service.getCumulativePerformance());
    }

    @GetMapping("/super-performance")
    public ResponseEntity<Map<String, Object>> getSuperPerformance() {
        return cached(service.getSuperPerformance());
    }

    @GetMapping("/smart-money")
    public ResponseEntity<Map<String, Object>> getSmartMoney() {
        return cached(service.getSmartMoney());
    }

    @GetMapping("/smart-money/{ticker}/detail")
    public ResponseEntity<Map<String, Object>> getSmartMoneyDetail(@PathVariable String ticker) {
        return cached(service.getSmartMoneyDetail(ticker));
    }

    @GetMapping("/earnings-impact")
    public ResponseEntity<Map<String, Object>> getEarningsImpact() {
        return cached(service.getEarningsImpact());
    }

    @GetMapping("/backtest")
    public ResponseEntity<Map<String, Object>> getBacktest() {
        return cached(service.getBacktest());
    }

    @GetMapping("/top-picks-report")
    public ResponseEntity<Map<String, Object>> getTopPicksReport() {
        return cached(service.getTopPicksReport());
    }

    @GetMapping("/etf-flows")
    public ResponseEntity<Map<String, Object>> getEtfFlows() {
        return cached(service.getEtfFlows());
    }

    @GetMapping("/vcp-enhanced")
    public ResponseEntity<Map<String, Object>> getVCPEnhanced() {
        return cached(service.getVCPEnhanced());
    }

    @GetMapping("/ai-summary/{ticker}")
    public ResponseEntity<Map<String, Object>> getAiSummary(@PathVariable String ticker) {
        return cached(service.getAiSummary(ticker));
    }

    @GetMapping("/heatmap-data")
    public ResponseEntity<Map<String, Object>> getHeatmapData() {
        return cached(service.getHeatmapData());
    }

    @GetMapping("/news-analysis")
    public ResponseEntity<Map<String, Object>> getNewsAnalysis() {
        return cached(service.getNewsAnalysis());
    }

    @GetMapping("/macro-analysis")
    public ResponseEntity<Map<String, Object>> getMacroAnalysis() {
        return cached(service.getMacroAnalysis());
    }

    @GetMapping("/vcp-dates")
    public ResponseEntity<List<String>> getVcpDates() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(service.getVcpDates("us"));
    }

    @GetMapping("/vcp-report/{dateStr}")
    public ResponseEntity<?> getVcpReport(@PathVariable String dateStr) {
        Map<String, Object> data = service.getVcpReport("us", dateStr);
        if (data == null) return ResponseEntity.notFound().build();
        return cached(data);
    }

    private ResponseEntity<Map<String, Object>> cached(Map<String, Object> body) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(body);
    }
}
