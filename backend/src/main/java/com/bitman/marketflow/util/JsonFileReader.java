package com.bitman.marketflow.util;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.File;
import java.nio.file.Paths;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class JsonFileReader {

    private static final Logger log = LoggerFactory.getLogger(JsonFileReader.class);

    private final ObjectMapper mapper;
    private final String baseDir;
    private final long ttlMs;

    private final ConcurrentHashMap<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public JsonFileReader(
            ObjectMapper mapper,
            @Value("${app.data.base-dir}") String baseDir,
            @Value("${app.cache.ttl-seconds:30}") int ttlSeconds) {
        this.mapper = mapper;
        this.baseDir = baseDir;
        this.ttlMs = ttlSeconds * 1000L;
    }

    public Map<String, Object> read(String relativePath) {
        return loadWithCache(relativePath, Paths.get(baseDir, relativePath).toFile());
    }

    public Map<String, Object> readFromDir(String dir, String filename) {
        String key = dir + "/" + filename;
        return loadWithCache(key, Paths.get(baseDir, dir, filename).toFile());
    }

    /**
     * ConcurrentHashMap.compute()로 원자적 캐시 읽기/쓰기.
     * 동일 키에 대한 동시 접근 시 하나만 파일을 읽고 나머지는 캐시 결과 반환.
     */
    private Map<String, Object> loadWithCache(String key, File file) {
        long now = System.currentTimeMillis();

        CacheEntry entry = cache.get(key);
        if (entry != null && (now - entry.timestamp) < ttlMs) {
            return entry.data;
        }

        if (!file.exists()) {
            log.debug("File not found: {}", file);
            return null;
        }

        try {
            Map<String, Object> data = mapper.readValue(file, new TypeReference<>() {});
            cache.put(key, new CacheEntry(data, System.currentTimeMillis()));
            return data;
        } catch (Exception e) {
            log.error("Failed to read JSON {}: {}", file, e.getMessage());
            return null;
        }
    }

    private record CacheEntry(Map<String, Object> data, long timestamp) {}
}
