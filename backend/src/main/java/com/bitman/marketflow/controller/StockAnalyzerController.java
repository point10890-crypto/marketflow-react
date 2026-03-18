package com.bitman.marketflow.controller;

import com.bitman.marketflow.service.StockAnalyzerService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/stock-analyzer")
public class StockAnalyzerController {

    private final StockAnalyzerService service;

    public StockAnalyzerController(StockAnalyzerService service) {
        this.service = service;
    }

    @GetMapping("/search")
    public ResponseEntity<List<Map<String, Object>>> search(
            @RequestParam(defaultValue = "") String q,
            @RequestParam(defaultValue = "all") String market) {
        return ResponseEntity.ok(service.search(q, market));
    }

    @PostMapping("/analyze")
    public ResponseEntity<Map<String, Object>> analyze(@RequestBody Map<String, Object> body) {
        return ResponseEntity.ok(service.analyze(body));
    }

    @PostMapping("/export")
    public ResponseEntity<byte[]> export(@RequestBody Map<String, Object> body) {
        return service.export(body);
    }
}
