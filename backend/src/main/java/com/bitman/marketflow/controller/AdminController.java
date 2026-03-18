package com.bitman.marketflow.controller;

import com.bitman.marketflow.entity.UserEntity;
import com.bitman.marketflow.repository.UserRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.util.*;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/admin")
public class AdminController {

    private final UserRepository userRepository;
    private final RestTemplate restTemplate;
    private final String flaskBaseUrl;

    public AdminController(UserRepository userRepository, RestTemplate restTemplate,
                           @Value("${app.flask.base-url}") String flaskBaseUrl) {
        this.userRepository = userRepository;
        this.restTemplate = restTemplate;
        this.flaskBaseUrl = flaskBaseUrl;
    }

    @GetMapping("/dashboard")
    public ResponseEntity<?> getDashboard() {
        Map<String, Object> result = new HashMap<>();
        List<UserEntity> users = userRepository.findAll();
        result.put("total_users", users.size());
        result.put("pro_users", users.stream().filter(u -> "PRO".equals(u.getTier())).count());
        result.put("admin_users", users.stream().filter(u -> "ADMIN".equals(u.getRole())).count());
        result.put("recent_users", users.stream()
                .sorted((a, b) -> b.getCreatedAt().compareTo(a.getCreatedAt()))
                .limit(5)
                .map(this::userToMap)
                .collect(Collectors.toList()));
        return ResponseEntity.ok(result);
    }

    @GetMapping("/users")
    public ResponseEntity<?> getUsers() {
        List<Map<String, Object>> users = userRepository.findAllByOrderByCreatedAtDesc()
                .stream().map(this::userToMap).collect(Collectors.toList());
        return ResponseEntity.ok(Map.of("users", users));
    }

    @GetMapping("/users/{id}")
    public ResponseEntity<?> getUser(@PathVariable Long id) {
        return userRepository.findById(id)
                .map(u -> ResponseEntity.ok(userToMap(u)))
                .orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/users/{id}/role")
    public ResponseEntity<?> updateRole(@PathVariable Long id, @RequestBody Map<String, String> body) {
        return userRepository.findById(id).map(user -> {
            user.setRole(body.getOrDefault("role", user.getRole()));
            userRepository.save(user);
            return ResponseEntity.ok(userToMap(user));
        }).orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/users/{id}/tier")
    public ResponseEntity<?> updateTier(@PathVariable Long id, @RequestBody Map<String, String> body) {
        return userRepository.findById(id).map(user -> {
            user.setTier(body.getOrDefault("tier", user.getTier()));
            userRepository.save(user);
            return ResponseEntity.ok(userToMap(user));
        }).orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/users/{id}/status")
    public ResponseEntity<?> updateStatus(@PathVariable Long id, @RequestBody Map<String, String> body) {
        return userRepository.findById(id).map(user -> {
            user.setSubscriptionStatus(body.getOrDefault("status", user.getSubscriptionStatus()));
            userRepository.save(user);
            return ResponseEntity.ok(userToMap(user));
        }).orElse(ResponseEntity.notFound().build());
    }

    @DeleteMapping("/users/{id}")
    public ResponseEntity<?> deleteUser(@PathVariable Long id) {
        if (!userRepository.existsById(id)) return ResponseEntity.notFound().build();
        userRepository.deleteById(id);
        return ResponseEntity.ok(Map.of("deleted", true));
    }

    @GetMapping("/subscriptions")
    public ResponseEntity<?> getSubscriptions() {
        // Proxy to Flask for subscription management
        try {
            return restTemplate.getForEntity(flaskBaseUrl + "/api/admin/subscriptions", Object.class);
        } catch (Exception e) {
            // Fallback: return from our DB
            List<Map<String, Object>> pending = userRepository.findAll().stream()
                    .filter(u -> "PENDING".equals(u.getSubscriptionStatus()))
                    .map(this::userToMap)
                    .collect(Collectors.toList());
            return ResponseEntity.ok(Map.of("subscriptions", pending));
        }
    }

    @PutMapping("/subscriptions/{id}/approve")
    public ResponseEntity<?> approveSubscription(@PathVariable Long id) {
        return userRepository.findById(id).map(user -> {
            user.setSubscriptionStatus("APPROVED");
            user.setTier("PRO");
            user.setApprovedAt(java.time.LocalDateTime.now());
            userRepository.save(user);
            return ResponseEntity.ok(Map.of("approved", true));
        }).orElse(ResponseEntity.notFound().build());
    }

    @PutMapping("/subscriptions/{id}/reject")
    public ResponseEntity<?> rejectSubscription(@PathVariable Long id) {
        return userRepository.findById(id).map(user -> {
            user.setSubscriptionStatus("REJECTED");
            userRepository.save(user);
            return ResponseEntity.ok(Map.of("rejected", true));
        }).orElse(ResponseEntity.notFound().build());
    }

    private Map<String, Object> userToMap(UserEntity user) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", user.getId());
        map.put("email", user.getEmail());
        map.put("name", user.getName());
        map.put("role", user.getRole());
        map.put("tier", user.getTier());
        map.put("subscriptionStatus", user.getSubscriptionStatus());
        map.put("createdAt", user.getCreatedAt());
        map.put("approvedAt", user.getApprovedAt());
        return map;
    }
}
