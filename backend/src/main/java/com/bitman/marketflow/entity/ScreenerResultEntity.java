package com.bitman.marketflow.entity;

import jakarta.persistence.*;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "screener_results", indexes = {
        @Index(name = "idx_screener_date", columnList = "date", unique = true)
})
public class ScreenerResultEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private LocalDate date;

    private int totalCandidates;
    private int filteredCount;
    private Long processingTimeMs;
    private LocalDateTime updatedAt;

    @Column(columnDefinition = "CLOB")
    private String byGradeJson;

    @Column(columnDefinition = "CLOB")
    private String byMarketJson;

    @Column(columnDefinition = "CLOB")
    private String aiPicksJson;

    @OneToMany(mappedBy = "result", cascade = CascadeType.ALL, orphanRemoval = true)
    @OrderBy("id ASC")
    private List<SignalEntity> signals = new ArrayList<>();

    // ── Getters / Setters ───────────────────────────────────────────────────

    public Long getId() { return id; }

    public LocalDate getDate() { return date; }
    public void setDate(LocalDate date) { this.date = date; }

    public int getTotalCandidates() { return totalCandidates; }
    public void setTotalCandidates(int totalCandidates) { this.totalCandidates = totalCandidates; }

    public int getFilteredCount() { return filteredCount; }
    public void setFilteredCount(int filteredCount) { this.filteredCount = filteredCount; }

    public Long getProcessingTimeMs() { return processingTimeMs; }
    public void setProcessingTimeMs(Long processingTimeMs) { this.processingTimeMs = processingTimeMs; }

    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }

    public String getByGradeJson() { return byGradeJson; }
    public void setByGradeJson(String byGradeJson) { this.byGradeJson = byGradeJson; }

    public String getByMarketJson() { return byMarketJson; }
    public void setByMarketJson(String byMarketJson) { this.byMarketJson = byMarketJson; }

    public String getAiPicksJson() { return aiPicksJson; }
    public void setAiPicksJson(String aiPicksJson) { this.aiPicksJson = aiPicksJson; }

    public List<SignalEntity> getSignals() { return signals; }
    public void setSignals(List<SignalEntity> signals) { this.signals = signals; }

    public void addSignal(SignalEntity signal) {
        signals.add(signal);
        signal.setResult(this);
    }
}
