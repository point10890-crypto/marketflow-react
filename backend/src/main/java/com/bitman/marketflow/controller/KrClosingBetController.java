package com.bitman.marketflow.controller;

import com.bitman.marketflow.service.KrClosingBetService;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@RestController
@RequestMapping("/api/kr/jongga-v2")
public class KrClosingBetController {

    private final KrClosingBetService service;

    public KrClosingBetController(KrClosingBetService service) {
        this.service = service;
    }

    @GetMapping("/latest")
    public ResponseEntity<Map<String, Object>> getLatest() {
        return cached(service.getLatest());
    }

    @GetMapping("/dates")
    public ResponseEntity<List<String>> getDates() {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(service.getDates());
    }

    @GetMapping("/history/{dateStr}")
    public ResponseEntity<Map<String, Object>> getHistory(@PathVariable String dateStr) {
        Map<String, Object> data = service.getHistory(dateStr);
        if (data == null) {
            return ResponseEntity.notFound().build();
        }
        return cached(data);
    }

    @PostMapping("/analyze")
    public ResponseEntity<Map<String, Object>> analyze(@RequestBody Map<String, Object> body) {
        return ResponseEntity.ok(service.analyze(body));
    }

    @PostMapping("/run")
    public ResponseEntity<Map<String, Object>> run() {
        return ResponseEntity.ok(service.run());
    }

    private ResponseEntity<Map<String, Object>> cached(Map<String, Object> body) {
        return ResponseEntity.ok()
                .cacheControl(CacheControl.maxAge(30, TimeUnit.SECONDS).cachePublic())
                .body(body);
    }
}
