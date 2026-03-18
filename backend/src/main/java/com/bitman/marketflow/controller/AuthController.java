package com.bitman.marketflow.controller;

import com.bitman.marketflow.entity.UserEntity;
import com.bitman.marketflow.repository.UserRepository;
import com.bitman.marketflow.util.JwtUtil;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final UserRepository userRepository;
    private final JwtUtil jwtUtil;
    private final PasswordEncoder passwordEncoder;

    public AuthController(UserRepository userRepository, JwtUtil jwtUtil, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.jwtUtil = jwtUtil;
        this.passwordEncoder = passwordEncoder;
    }

    @PostMapping("/register")
    public ResponseEntity<?> register(@RequestBody Map<String, String> body) {
        String email = body.get("email");
        String password = body.get("password");
        String name = body.getOrDefault("name", email.split("@")[0]);

        if (email == null || password == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "Email and password required"));
        }
        if (userRepository.existsByEmail(email)) {
            return ResponseEntity.badRequest().body(Map.of("error", "Email already registered"));
        }

        UserEntity user = new UserEntity();
        user.setEmail(email);
        user.setPasswordHash(passwordEncoder.encode(password));
        user.setName(name);
        userRepository.save(user);

        String token = jwtUtil.generateToken(user);
        return ResponseEntity.ok(Map.of(
                "token", token,
                "user", userToMap(user)
        ));
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@RequestBody Map<String, String> body) {
        String email = body.get("email");
        String password = body.get("password");

        Optional<UserEntity> userOpt = userRepository.findByEmail(email);
        if (userOpt.isEmpty() || !passwordEncoder.matches(password, userOpt.get().getPasswordHash())) {
            return ResponseEntity.status(401).body(Map.of("error", "Invalid credentials"));
        }

        UserEntity user = userOpt.get();
        String token = jwtUtil.generateToken(user);
        return ResponseEntity.ok(Map.of(
                "token", token,
                "user", userToMap(user)
        ));
    }

    @GetMapping("/me")
    public ResponseEntity<?> me(@AuthenticationPrincipal String email) {
        if (email == null) return ResponseEntity.status(401).body(Map.of("error", "Unauthorized"));
        return userRepository.findByEmail(email)
                .map(user -> ResponseEntity.ok(userToMap(user)))
                .orElse(ResponseEntity.status(404).body(null));
    }

    @PutMapping("/profile")
    public ResponseEntity<?> updateProfile(@AuthenticationPrincipal String email,
                                           @RequestBody Map<String, String> body) {
        if (email == null) return ResponseEntity.status(401).body(Map.of("error", "Unauthorized"));
        return userRepository.findByEmail(email).map(user -> {
            if (body.containsKey("name")) user.setName(body.get("name"));
            userRepository.save(user);
            return ResponseEntity.ok(userToMap(user));
        }).orElse(ResponseEntity.notFound().build());
    }

    private Map<String, Object> userToMap(UserEntity user) {
        Map<String, Object> map = new HashMap<>();
        map.put("id", user.getId());
        map.put("email", user.getEmail());
        map.put("name", user.getName());
        map.put("role", user.getRole());
        map.put("tier", user.getTier());
        map.put("subscriptionStatus", user.getSubscriptionStatus());
        map.put("createdAt", user.getCreatedAt());
        return map;
    }
}
