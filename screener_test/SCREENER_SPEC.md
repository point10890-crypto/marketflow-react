# 주도주 조건검색식 시스템 스펙 (v1.0)
## 검증 완료: 2026-03-23

---

## 1. KIS API 엔드포인트 (검증 완료)

### 인증
| 항목 | 값 |
|------|-----|
| 모의투자 도메인 | `https://openapivts.koreainvestment.com:29443` |
| 실전투자 도메인 | `https://openapi.koreainvestment.com:9443` |
| 토큰 발급 | `POST /oauth2/tokenP` |
| 토큰 유효기간 | 24시간 |
| Rate Limit | 실전 초당 20건, 모의 초당 5건 |

### 순위 API (3개 — 병렬 호출)

#### 1-1. 거래량순위 (거래금액순)
```
GET /uapi/domestic-stock/v1/quotations/volume-rank
tr_id: FHPST01710000

필수 파라미터:
  FID_COND_MRKT_DIV_CODE: "J"       (KRX)
  FID_COND_SCR_DIV_CODE:  "20171"
  FID_INPUT_ISCD:          "0000"    (전체)
  FID_DIV_CLS_CODE:        "0"      (전체)
  FID_BLNG_CLS_CODE:       "3"      (거래금액순)
  FID_TRGT_CLS_CODE:       "000000"
  FID_TRGT_EXLS_CLS_CODE:  "0000000000"
  FID_INPUT_PRICE_1:        ""
  FID_INPUT_PRICE_2:        ""
  FID_VOL_CNT:              ""
  FID_INPUT_DATE_1:         ""

응답 주요 필드:
  mksc_shrn_iscd  — 종목코드 (6자리)
  hts_kor_isnm    — 종목명
  stck_prpr       — 현재가
  prdy_ctrt       — 전일 대비 등락률(%)
  acml_tr_pbmn    — 누적 거래대금
  acml_vol        — 누적 거래량
  prdy_vol        — 전일 거래량
  bstp_cls_code   — 업종코드
```

#### 1-2. 거래량순위 (거래증가율순)
```
동일 엔드포인트, FID_BLNG_CLS_CODE: "1" (거래증가율)
```

#### 1-3. 등락률 순위
```
GET /uapi/domestic-stock/v1/ranking/fluctuation
tr_id: FHPST01700000

필수 파라미터:
  fid_cond_mrkt_div_code:  "J"
  fid_cond_scr_div_code:   "20170"
  fid_input_iscd:           "0000"
  fid_rank_sort_cls_code:   "0"     (등락률순)
  fid_input_cnt_1:          "30"
  fid_prc_cls_code:         "0"
  fid_input_price_1:        "0"
  fid_input_price_2:        "1000000"
  fid_vol_cnt:              "10000"
  fid_trgt_cls_code:        "0"
  fid_trgt_exls_cls_code:   "0"
  fid_div_cls_code:         "0"
  fid_rsfl_rate1:           "0"     (0% 이상)
  fid_rsfl_rate2:           "30"    (30% 이하)

응답 주요 필드:
  mksc_shrn_iscd / stck_shrn_iscd — 종목코드
  hts_kor_isnm    — 종목명
  stck_prpr       — 현재가
  prdy_ctrt       — 등락률(%)
  acml_vol        — 누적 거래량
  acml_tr_pbmn    — 누적 거래대금
```

### 투자자 매매 API (개별 종목)
```
GET /uapi/domestic-stock/v1/quotations/inquire-investor
tr_id: FHKST01010900

필수 파라미터:
  FID_COND_MRKT_DIV_CODE: "J"
  FID_INPUT_ISCD:          "종목코드"

응답 주요 필드 (배열, 최근 5일):
  stck_bsop_date  — 날짜
  frgn_ntby_qty   — 외인 순매수량
  orgn_ntby_qty   — 기관 순매수량
```

### 종목별 투자자매매동향 (일별 상세)
```
GET /uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily
tr_id: (확인 필요)

필수 파라미터:
  fid_cond_mrkt_div_code: "J"
  fid_input_iscd:          "종목코드"
  fid_input_date_1:        "YYYYMMDD"
  fid_org_adj_prc:         ""
  fid_etc_cls_code:        ""
```

---

## 2. 작동 메커니즘

### 전체 플로우
```
[사전 준비] 08:50 KST
  └─ 토큰 발급 (24시간 유효, 1회)

[장중 폴링] 09:00~15:30 KST (3초 간격)
  │
  ├─ Step 1: 순위 API 3건 병렬 호출 (~300ms)
  │   ├─ 거래대금순위 (거래금액순)  → Top 30
  │   ├─ 등락률순위 (상승률순)      → Top 30
  │   └─ 거래량순위 (거래증가율순)  → Top 30
  │
  ├─ Step 2: 후보 합집합 구성 + ETF/ETN 필터링
  │   └─ 최대 ~50종목 (중복 제거)
  │
  ├─ Step 3: 예비 점수로 상위 15종목 선별
  │   └─ 거래대금(30점) + 등락률(25점) 예비 합산
  │
  ├─ Step 4: 상위 15종목 투자자 매매 조회 (~1.5초, 병렬화 시)
  │   └─ 외인/기관 당일 순매수량
  │
  ├─ Step 5: 5항목 100점 만점 채점
  │   ├─ 거래대금 집중도  (30점)
  │   ├─ 등락률 모멘텀    (25점)
  │   ├─ 스마트머니 수급   (25점)
  │   ├─ 거래량 급증률    (10점)
  │   └─ 섹터 동반상승    (10점)
  │
  ├─ Step 6: 시간대별 가중치 적용
  │   └─ 장 초반 ×1.2, 표준 ×1.0, 마감 임박 ×0.8
  │
  └─ Step 7: 등급 분류 + 결과 반환
      ├─ S등급: 80~100점 (확실한 주도주)
      ├─ A등급: 60~79점  (강한 후보)
      ├─ B등급: 40~59점  (관심 종목)
      └─ C등급: <40점    (제외)

[장 마감] 15:30 KST
  └─ 폴링 중단, 최종 결과 저장
```

### 데이터 흐름 (앱 통합 시)
```
KIS API (REST)
    ↓ 3초 폴링
Flask 백엔드 (/api/kr/screener/leading)
    ↓ JSON 응답
    ↓ 메모리 캐시 (3초 TTL)
Next.js/Vite 프론트엔드
    ↓ useAutoRefresh (3초)
대시보드 UI (주도주 테이블)
```

---

## 3. 채점 기준 (100점 만점)

### 3-1. 거래대금 집중도 (30점)
| 거래대금 | 점수 |
|---------|------|
| ≥ 500억 | 30 |
| ≥ 200억 | 25 |
| ≥ 100억 | 20 |
| ≥ 50억  | 15 |
| ≥ 20억  | 10 |
| < 20억  | 0 (탈락) |

### 3-2. 등락률 모멘텀 (25점)
| 등락률 | 점수 |
|--------|------|
| ≥ +15% | 25 |
| ≥ +10% | 22 |
| ≥ +7%  | 18 |
| ≥ +5%  | 14 |
| ≥ +3%  | 10 |
| ≥ +1%  | 5 |
| < +1%  | 0 |

### 3-3. 스마트머니 수급 (25점)
| 조건 | 점수 |
|------|------|
| 외인+기관 동시 순매수 | 25 |
| 외인 대량 순매수 (>1000주) | 18 |
| 기관 대량 순매수 (>1000주) | 15 |
| 외인 또는 기관 소량 순매수 | 8 |
| 둘 다 순매도 | 0 |

### 3-4. 거래량 급증률 (10점)
| 전일 동시간 대비 | 점수 |
|-----------------|------|
| ≥ 500% | 10 |
| ≥ 300% | 8 |
| ≥ 200% | 6 |
| ≥ 100% | 3 |
| < 100% | 0 |

### 3-5. 섹터 동반상승 (10점)
| 동일 업종 +3% 종목 수 | 점수 |
|---------------------|------|
| ≥ 3종목 | 10 |
| ≥ 2종목 | 7 |
| ≥ 1종목 | 3 |
| 단독 상승 | 0 |

### 시간대별 가중치
| 시간 (KST) | 가중치 | 이유 |
|------------|--------|------|
| 09:00~09:30 | ×1.2 | 장 초반 모멘텀 |
| 09:30~10:30 | ×1.0 | 표준 |
| 10:30~11:30 | ×1.1 | 버틴 종목 = 강한 주도주 |
| 13:00~14:00 | ×1.15 | 오후 재상승 |
| 14:00~15:20 | ×0.8 | 마감 임박 |

---

## 4. 필터링 규칙

### ETF/ETN 제외 키워드
KODEX, TIGER, KBSTAR, KOSEF, ARIRANG, HANARO, SOL, ACE, RISE,
PLUS, BNK, ETN, 인버스, 레버리지, 선물, 2X, 3X, KINDEX, TIMEFOLIO, WOORI

### 최소 진입 조건
- 거래대금 ≥ 20억 (이하 자동 탈락)
- 등락률 ≥ +1% (하락 종목 제외)

---

## 5. 앱 통합 엔드포인트 설계

### Flask 엔드포인트
```
GET /api/kr/screener/leading
응답:
{
  "timestamp": "2026-03-24T09:30:00",
  "market_status": "open",     // open / closed / pre_market
  "time_weight": 1.2,
  "total_candidates": 36,
  "results": [
    {
      "rank": 1,
      "grade": "S",
      "code": "003280",
      "name": "흥아해운",
      "price": 3625,
      "change_pct": 19.6,
      "trading_value": 723100000000,
      "trading_value_eok": 7231,
      "volume": 189234567,
      "score": {
        "total": 85,
        "trading_value": 30,
        "momentum": 25,
        "smart_money": 20,
        "volume_surge": 10,
        "sector": 0
      },
      "investor": {
        "foreign_net": -2071114,
        "inst_net": -14279
      },
      "volume_ratio": 523.4,
      "sector_rising_count": 0
    }
  ],
  "by_grade": {"S": 1, "A": 3, "B": 5},
  "api_calls": 18,
  "elapsed_ms": 2100
}
```

### Spring Boot 엔드포인트 (프록시)
```
GET /api/kr/screener/leading → Flask:5001 프록시
캐시: Caffeine 3초 TTL
```

### 프론트엔드
```
페이지: /dashboard/kr/screener
API:   krAPI.getLeadingStocks()
갱신:  useAutoRefresh(3000) — 장중만 활성
```

---

## 6. 성능 측정 결과 (2026-03-23 실측)

| 항목 | 순차 | 병렬 예상 |
|------|------|----------|
| 토큰 발급 | 381ms | 사전 발급 (0ms) |
| 순위 API 3건 | 898ms | ~300ms |
| 투자자 15건 | 5,554ms | ~1,500ms |
| 필터링+채점 | <1ms | <1ms |
| **전체** | **6,812ms** | **~2,000ms** |
| API 호출 수 | 18건 | 18건 |
| Rate Limit 사용 | 초당 ~3건 | 초당 ~9건 (한도 45%) |

---

## 7. 환경변수

```
KIS_APP_KEY=PSNr...       # 앱 키
KIS_APP_SECRET=IQNn...    # 앱 시크릿
KIS_CANO=43918141         # 계좌번호
KIS_PAPER=true            # 모의투자 모드 (true/false)
```

---

## 8. 구현 우선순위

### Phase 1: 백엔드 엔진 (Flask)
- [ ] kis_screener.py 모듈 (app/services/)
- [ ] /api/kr/screener/leading 엔드포인트
- [ ] 토큰 자동 갱신 (24시간)
- [ ] 장중/장외 자동 감지
- [ ] asyncio 병렬 호출

### Phase 2: 프론트엔드 UI
- [ ] /dashboard/kr/screener 페이지
- [ ] 실시간 갱신 (3초)
- [ ] 등급별 필터 + 정렬
- [ ] 종목 클릭 → 상세 분석

### Phase 3: 알림 연동
- [ ] S등급 발생 시 벨 알림 + 텔레그램
- [ ] 스케줄러 연동 (장중 자동 실행)
