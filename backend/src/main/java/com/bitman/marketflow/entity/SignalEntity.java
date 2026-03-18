package com.bitman.marketflow.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "signals", indexes = {
        @Index(name = "idx_signal_grade", columnList = "grade"),
        @Index(name = "idx_signal_stock_code", columnList = "stockCode")
})
public class SignalEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "result_id", nullable = false)
    private ScreenerResultEntity result;

    // ── 종목 기본 정보 ──
    private String stockCode;
    private String stockName;
    private String market;
    private String sector;
    private String grade;

    // ── 가격 ──
    private Integer currentPrice;
    private Integer entryPrice;
    private Integer stopPrice;
    private Integer targetPrice;

    // ── 지표 ──
    private Double changePct;
    private Long tradingValue;
    private Double volumeRatio;
    private Integer foreign5d;
    private Integer inst5d;

    // ── 포지션 사이징 ──
    private Integer quantity;
    private Long positionSize;
    private Double rValue;
    private Double rMultiplier;

    // ── Score (17점 만점) ──
    private int scoreNews;
    private int scoreVolume;
    private int scoreChart;
    private int scoreCandle;
    private int scoreConsolidation;
    private int scoreSupply;
    private int scoreDisclosure;
    private int scoreAnalyst;
    private int scoreTotal;

    @Column(columnDefinition = "CLOB")
    private String scoreLlmReason;
    private String scoreLlmSource;

    // ── Checklist ──
    private boolean checkHasNews;
    private boolean checkVolumeSufficient;
    private boolean checkIsNewHigh;
    private boolean checkIsBreakout;
    private boolean checkMaAligned;
    private boolean checkGoodCandle;
    private boolean checkHasConsolidation;
    private boolean checkSupplyPositive;
    private boolean checkHasDisclosure;
    private boolean checkNegativeNews;
    private boolean checkUpperWickLong;
    private boolean checkVolumeSuspicious;

    @Column(columnDefinition = "CLOB")
    private String checkNewsSourcesJson;

    @Column(columnDefinition = "CLOB")
    private String checkDisclosureTypesJson;

    // ── 뉴스 & 테마 (JSON CLOB) ──
    @Column(columnDefinition = "CLOB")
    private String newsItemsJson;

    @Column(columnDefinition = "CLOB")
    private String themesJson;

    // ── Getters / Setters ───────────────────────────────────────────────────

    public Long getId() { return id; }

    public ScreenerResultEntity getResult() { return result; }
    public void setResult(ScreenerResultEntity result) { this.result = result; }

    public String getStockCode() { return stockCode; }
    public void setStockCode(String stockCode) { this.stockCode = stockCode; }

    public String getStockName() { return stockName; }
    public void setStockName(String stockName) { this.stockName = stockName; }

    public String getMarket() { return market; }
    public void setMarket(String market) { this.market = market; }

    public String getSector() { return sector; }
    public void setSector(String sector) { this.sector = sector; }

    public String getGrade() { return grade; }
    public void setGrade(String grade) { this.grade = grade; }

    public Integer getCurrentPrice() { return currentPrice; }
    public void setCurrentPrice(Integer currentPrice) { this.currentPrice = currentPrice; }

    public Integer getEntryPrice() { return entryPrice; }
    public void setEntryPrice(Integer entryPrice) { this.entryPrice = entryPrice; }

    public Integer getStopPrice() { return stopPrice; }
    public void setStopPrice(Integer stopPrice) { this.stopPrice = stopPrice; }

    public Integer getTargetPrice() { return targetPrice; }
    public void setTargetPrice(Integer targetPrice) { this.targetPrice = targetPrice; }

    public Double getChangePct() { return changePct; }
    public void setChangePct(Double changePct) { this.changePct = changePct; }

    public Long getTradingValue() { return tradingValue; }
    public void setTradingValue(Long tradingValue) { this.tradingValue = tradingValue; }

    public Double getVolumeRatio() { return volumeRatio; }
    public void setVolumeRatio(Double volumeRatio) { this.volumeRatio = volumeRatio; }

    public Integer getForeign5d() { return foreign5d; }
    public void setForeign5d(Integer foreign5d) { this.foreign5d = foreign5d; }

    public Integer getInst5d() { return inst5d; }
    public void setInst5d(Integer inst5d) { this.inst5d = inst5d; }

    public Integer getQuantity() { return quantity; }
    public void setQuantity(Integer quantity) { this.quantity = quantity; }

    public Long getPositionSize() { return positionSize; }
    public void setPositionSize(Long positionSize) { this.positionSize = positionSize; }

    public Double getRValue() { return rValue; }
    public void setRValue(Double rValue) { this.rValue = rValue; }

    public Double getRMultiplier() { return rMultiplier; }
    public void setRMultiplier(Double rMultiplier) { this.rMultiplier = rMultiplier; }

    // Score getters/setters
    public int getScoreNews() { return scoreNews; }
    public void setScoreNews(int v) { this.scoreNews = v; }
    public int getScoreVolume() { return scoreVolume; }
    public void setScoreVolume(int v) { this.scoreVolume = v; }
    public int getScoreChart() { return scoreChart; }
    public void setScoreChart(int v) { this.scoreChart = v; }
    public int getScoreCandle() { return scoreCandle; }
    public void setScoreCandle(int v) { this.scoreCandle = v; }
    public int getScoreConsolidation() { return scoreConsolidation; }
    public void setScoreConsolidation(int v) { this.scoreConsolidation = v; }
    public int getScoreSupply() { return scoreSupply; }
    public void setScoreSupply(int v) { this.scoreSupply = v; }
    public int getScoreDisclosure() { return scoreDisclosure; }
    public void setScoreDisclosure(int v) { this.scoreDisclosure = v; }
    public int getScoreAnalyst() { return scoreAnalyst; }
    public void setScoreAnalyst(int v) { this.scoreAnalyst = v; }
    public int getScoreTotal() { return scoreTotal; }
    public void setScoreTotal(int v) { this.scoreTotal = v; }
    public String getScoreLlmReason() { return scoreLlmReason; }
    public void setScoreLlmReason(String v) { this.scoreLlmReason = v; }
    public String getScoreLlmSource() { return scoreLlmSource; }
    public void setScoreLlmSource(String v) { this.scoreLlmSource = v; }

    // Checklist getters/setters
    public boolean isCheckHasNews() { return checkHasNews; }
    public void setCheckHasNews(boolean v) { this.checkHasNews = v; }
    public boolean isCheckVolumeSufficient() { return checkVolumeSufficient; }
    public void setCheckVolumeSufficient(boolean v) { this.checkVolumeSufficient = v; }
    public boolean isCheckIsNewHigh() { return checkIsNewHigh; }
    public void setCheckIsNewHigh(boolean v) { this.checkIsNewHigh = v; }
    public boolean isCheckIsBreakout() { return checkIsBreakout; }
    public void setCheckIsBreakout(boolean v) { this.checkIsBreakout = v; }
    public boolean isCheckMaAligned() { return checkMaAligned; }
    public void setCheckMaAligned(boolean v) { this.checkMaAligned = v; }
    public boolean isCheckGoodCandle() { return checkGoodCandle; }
    public void setCheckGoodCandle(boolean v) { this.checkGoodCandle = v; }
    public boolean isCheckHasConsolidation() { return checkHasConsolidation; }
    public void setCheckHasConsolidation(boolean v) { this.checkHasConsolidation = v; }
    public boolean isCheckSupplyPositive() { return checkSupplyPositive; }
    public void setCheckSupplyPositive(boolean v) { this.checkSupplyPositive = v; }
    public boolean isCheckHasDisclosure() { return checkHasDisclosure; }
    public void setCheckHasDisclosure(boolean v) { this.checkHasDisclosure = v; }
    public boolean isCheckNegativeNews() { return checkNegativeNews; }
    public void setCheckNegativeNews(boolean v) { this.checkNegativeNews = v; }
    public boolean isCheckUpperWickLong() { return checkUpperWickLong; }
    public void setCheckUpperWickLong(boolean v) { this.checkUpperWickLong = v; }
    public boolean isCheckVolumeSuspicious() { return checkVolumeSuspicious; }
    public void setCheckVolumeSuspicious(boolean v) { this.checkVolumeSuspicious = v; }
    public String getCheckNewsSourcesJson() { return checkNewsSourcesJson; }
    public void setCheckNewsSourcesJson(String v) { this.checkNewsSourcesJson = v; }
    public String getCheckDisclosureTypesJson() { return checkDisclosureTypesJson; }
    public void setCheckDisclosureTypesJson(String v) { this.checkDisclosureTypesJson = v; }

    public String getNewsItemsJson() { return newsItemsJson; }
    public void setNewsItemsJson(String v) { this.newsItemsJson = v; }
    public String getThemesJson() { return themesJson; }
    public void setThemesJson(String v) { this.themesJson = v; }
}
