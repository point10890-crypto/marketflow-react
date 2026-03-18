package com.bitman.marketflow.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import java.util.Map;

@RestController
@RequestMapping("/api/kr/chatbot")
public class KrChatbotController {

    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    public KrChatbotController(RestTemplate restTemplate, @Value("${app.flask.base-url}") String flaskBaseUrl) {
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
    }

    @PostMapping
    public ResponseEntity<?> chat(@RequestBody Map<String, Object> body) {
        try {
            return restTemplate.postForEntity(flaskBaseUrl + "/api/kr/chatbot", body, Object.class);
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("error", "Chatbot unavailable"));
        }
    }

    @GetMapping("/welcome")
    public ResponseEntity<?> welcome() {
        try {
            return restTemplate.getForEntity(flaskBaseUrl + "/api/kr/chatbot/welcome", Object.class);
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("message", "안녕하세요! MarketFlow AI입니다."));
        }
    }

    @GetMapping("/status")
    public ResponseEntity<?> status() {
        try {
            return restTemplate.getForEntity(flaskBaseUrl + "/api/kr/chatbot/status", Object.class);
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("status", "unavailable"));
        }
    }
}
