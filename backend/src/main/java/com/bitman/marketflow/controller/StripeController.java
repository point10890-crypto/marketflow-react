package com.bitman.marketflow.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import java.util.Map;

@RestController
@RequestMapping("/api/stripe")
public class StripeController {

    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    public StripeController(RestTemplate restTemplate, @Value("${app.flask.base-url}") String flaskBaseUrl) {
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
    }

    @PostMapping("/create-checkout")
    public ResponseEntity<?> createCheckout(@RequestBody Map<String, Object> body) {
        try {
            return restTemplate.postForEntity(flaskBaseUrl + "/api/stripe/create-checkout", body, Object.class);
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of("error", "Payment service unavailable"));
        }
    }

    @PostMapping("/portal")
    public ResponseEntity<?> portal(@RequestBody Map<String, Object> body) {
        try {
            return restTemplate.postForEntity(flaskBaseUrl + "/api/stripe/portal", body, Object.class);
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of("error", "Payment service unavailable"));
        }
    }
}
