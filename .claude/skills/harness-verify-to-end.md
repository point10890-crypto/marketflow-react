---
name: harness-verify-to-end
description: "Harness Verify 단계 — 사용자에게 보고하기 전 100% 라이브 검증. 한 endpoint 라도 실패하면 추가 fix. 절대 떠넘기지 않음."
user_invocable: false
auto_trigger: true
---

# Harness — Verify 단계 끝까지 책임

> **사용자 명시 규칙 (2026-05-14 19:30 KST):**
> "끝까지 검증 까지 해서 마무리 하라니까. 뭐하나 제대로 끝내질 못해"
>
> 이 스킬은 그 이후 모든 작업에 자동 적용.

---

## 절대 규칙

### 1. "배포 끝났습니다 — 확인해주세요" 금지

❌ **잘못된 패턴 (반복하지 말 것):**
```
1. 코드 수정 + 빌드
2. 배포
3. "Ctrl+Shift+R 새로고침해서 확인하세요"
4. 사용자가 "안 됐다" 보고
5. 다시 fix
```

✅ **올바른 패턴:**
```
1. 코드 수정 + 빌드 + 배포
2. 본인이 직접 curl 로 라이브 검증
3. 모든 endpoint 통과 확인
4. RSS / 응답시간 / 캐시 hit 검증
5. **그 다음에** 사용자에게 결과 보고
```

### 2. 검증 항목 (생략 금지)

production deploy 후 최소 다음 5가지 확인:

| 항목 | 명령 | 통과 기준 |
|---|---|---|
| healthz | `curl /healthz` | HTTP 200, < 1s |
| 사용자 화면이 호출하는 정확한 URL | 화면의 timeout URL 그대로 호출 | HTTP 200, CF 100s 안 |
| Cache hit (2nd call) | 같은 URL 즉시 재호출 | < 2s (또는 < 1s) |
| RSS | `Get-Process` | < 3GB 안정 |
| 데이터 샘플 | response head -c 500 | 실제 데이터 들어있나 |

### 3. 한 endpoint 라도 실패하면

- ❌ 사용자에게 "확인해주세요" 떠넘기지 않음
- ✅ 즉시 원인 진단 + 추가 fix
- ✅ 재배포 + 재검증 (loop)
- ✅ 모두 통과 후 보고

---

## Verify 명령 (Phase G 패턴)

```bash
AUTH="Authorization: Bearer 3:1781219291:0e324300d1e528dd932d4c19ddec0792"
API="https://marketflow-api.bit-man.net/api/admin/mirofish"

# 사용자가 보는 화면의 모든 카드 URL 직접 호출
for label in \
  "graphrag/scan-history?days=30&limit=50&min_alpha=0" \
  "outcomes/board?days=30&limit=15" \
  "graphrag/scan-history-performance?days=60" \
  "auto-runner/status" \
  "pipeline/today"; do
  curl -sS -m 95 -o /tmp/v.json \
    -w "  [%{http_code}] %{time_total}s | $label (size %{size_download})\n" \
    -H "$AUTH" "$API/$label"
done

# 캐시 hit 확인 (2nd round, 모두 < 2s)
echo "=== Warm cache ==="
for label in ...; do
  curl -sS -m 10 -o /dev/null \
    -w "  [%{http_code}] %{time_total}s | $label\n" \
    -H "$AUTH" "$API/$label"
done

# RSS 확인
PID=$(ssh dynas@192.168.55.103 'cmd /c "netstat -ano | findstr :5001 | findstr LISTENING"' | tail -1 | awk '{print $NF}')
ssh dynas@192.168.55.103 "powershell -Command \"Get-Process -Id $PID | Select-Object @{N='RSS_MB';E={[math]::Round(\$_.WorkingSet64/1MB,1)}}, @{N='Uptime';E={(Get-Date) - \$_.StartTime}}\""
```

---

## 실패 패턴별 대응

| 증상 | 원인 후보 | Fix |
|---|---|---|
| HTTP 502 | Flask 다운 / hang | taskkill /F /PID + schtasks /Run, 60s polling wait |
| HTTP 000 timeout 95s | Backend hang (lock deadlock 또는 메모리 누수) | scan_history 패턴: `_cached()` 의 builder() 를 lock 밖으로 |
| HTTP 200 인데 frontend 에서 "API timeout" | fetchAPI 기본 10-15s timeout | fetchAuthAPI(`endpoint`, undefined, 60000) |
| Cache miss 매번 | TTL 너무 짧음 / cache 미적용 | TTL 10분 + per-key cache |
| RSS > 3 GB | 메모리 누수 워커 | watchdog RSS 임계 강제종료 + 워커 OFF (WORKER_*_ENABLED=0) |

---

## Watchdog 자가 검증

`scripts/flask_watchdog.ps1` 가 5분 주기로 호출:
- TCP 5001 LISTEN 체크
- /healthz HTTP 200 체크
- **RSS > 3000 MB 강제 종료** (2026-05-14 추가)
- Restart 후 60s polling boot wait (8s/30s 보다 안정)
- 실패 시 `[ALERT] Flask watchdog FAILED` 텔레그램 알람

---

## 검증 종료 조건 (이게 충족돼야 사용자 보고)

- [ ] healthz 200 < 1s
- [ ] 사용자 화면의 모든 endpoint HTTP 200
- [ ] 응답시간 모두 CF 100s 한계 안
- [ ] 2nd call (warm cache) 모두 < 2s
- [ ] 실제 응답 데이터 존재 (size > 100 bytes)
- [ ] RSS < 3 GB 안정
- [ ] 5분 후 RSS 증가율 < 100 MB/분

위 7개 모두 통과 → 사용자 보고. 한 개라도 실패 → 추가 fix → 재검증.

---

## 메타 원칙

> **"확인해주세요" 는 사용자의 일이 아니라 내 일이다.**
> 사용자에게 보고할 때는 이미 통과 확인된 상태여야 한다.
