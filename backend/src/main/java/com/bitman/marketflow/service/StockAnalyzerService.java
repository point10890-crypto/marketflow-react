package com.bitman.marketflow.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;

@Service
public class StockAnalyzerService {

    private static final Logger log = LoggerFactory.getLogger(StockAnalyzerService.class);

    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    public StockAnalyzerService(
            RestTemplate restTemplate,
            @Value("${app.flask.base-url}") String flaskBaseUrl) {
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
    }

    // ── search (Flask GET proxy) ────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> search(String query, String market) {
        try {
            log.debug("stock-analyzer/search: proxying to Flask (q={})", query);
            String url = flaskBaseUrl + "/api/stock-analyzer/search?q=" + query;
            if (market != null && !market.isEmpty()) {
                url += "&market=" + market;
            }
            List<Map<String, Object>> result = restTemplate.getForObject(url, List.class);
            return result != null ? result : List.of();
        } catch (Exception e) {
            log.warn("Flask proxy failed for stock-analyzer/search: {}", e.getMessage());
            return List.of();
        }
    }

    // ── analyze (Flask POST proxy) ──────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    public Map<String, Object> analyze(Map<String, Object> body) {
        try {
            log.debug("stock-analyzer/analyze: proxying to Flask");
            Map<String, Object> result = restTemplate.postForObject(
                    flaskBaseUrl + "/api/stock-analyzer/analyze", body, Map.class);
            return result != null ? result : Map.of("error", "No response from Flask");
        } catch (Exception e) {
            log.warn("Flask proxy failed for stock-analyzer/analyze: {}", e.getMessage());
            return Map.of("error", e.getMessage());
        }
    }

    // ── export (Flask POST proxy — binary Excel response) ───────────────────────

    public ResponseEntity<byte[]> export(Map<String, Object> body) {
        try {
            log.debug("stock-analyzer/export: proxying to Flask (binary)");
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

            ResponseEntity<byte[]> response = restTemplate.exchange(
                    flaskBaseUrl + "/api/stock-analyzer/export",
                    HttpMethod.POST, request, byte[].class);

            // Forward Flask response headers (Content-Type, Content-Disposition)
            HttpHeaders responseHeaders = new HttpHeaders();
            if (response.getHeaders().getContentType() != null) {
                responseHeaders.setContentType(response.getHeaders().getContentType());
            }
            String disposition = response.getHeaders().getFirst("Content-Disposition");
            if (disposition != null) {
                responseHeaders.set("Content-Disposition", disposition);
            }

            return ResponseEntity.ok().headers(responseHeaders).body(response.getBody());
        } catch (Exception e) {
            log.warn("Flask proxy failed for stock-analyzer/export: {}", e.getMessage());
            return ResponseEntity.internalServerError().build();
        }
    }
}
