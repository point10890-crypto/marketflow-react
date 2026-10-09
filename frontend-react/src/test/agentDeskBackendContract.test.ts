import { describe, expect, it } from 'vitest';
import { validateAgentDesk } from '@/lib/agentDeskApi';
import type { OpportunityEngine } from '@/lib/opportunityEngine';

// Public output captured from test_alpha_lab_desk_evidence.bundle ->
// publish_bundle -> service._with_agent_desk with synthetic deterministic
// backend test sources, never production source data.
const backendSnapshot = {
  "desk": {
    "schema_version": 1,
    "policy_version": "evidence-account-v1",
    "generated_at": "2026-10-08T02:00:00Z",
    "order_allowed": false,
    "roles": [
      {
        "id": "regime",
        "title": "시장 국면",
        "status": "unavailable",
        "detail": "현재 후보 3개 중 0개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "fx_liquidity",
        "title": "환율·유동성",
        "status": "passed",
        "detail": "현재 후보 3개 중 3개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "flow",
        "title": "외국인 수급",
        "status": "passed",
        "detail": "현재 후보 3개 중 3개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "disclosure",
        "title": "공시·재무",
        "status": "passed",
        "detail": "현재 후보 3개 중 3개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "sector",
        "title": "업종",
        "status": "unavailable",
        "detail": "현재 후보 3개 중 0개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "event",
        "title": "일정·이벤트",
        "status": "unavailable",
        "detail": "현재 후보 3개 중 0개의 유효한 출처 계약을 확인했습니다."
      },
      {
        "id": "micro",
        "title": "시세·진입 조건",
        "status": "passed",
        "detail": "현재 후보 3개 중 3개의 저장된 시세 관측을 확인했습니다. 독립 검증 출처로 세지 않습니다."
      },
      {
        "id": "sentiment",
        "title": "뉴스·심리",
        "status": "unavailable",
        "detail": "뉴스·사회 관심은 보조 정보이며 단독 방향 또는 계좌 계획을 승인하지 않습니다."
      },
      {
        "id": "auditor",
        "title": "출처 감사",
        "status": "passed",
        "detail": "방향·위험 주장마다 S/A 등급 독립 원본 2개와 공개·확보 시각, 만료, 환율·수급을 검사합니다."
      },
      {
        "id": "leader",
        "title": "판단 조정",
        "status": "held",
        "detail": "기존 연구 TOP3를 유지합니다. CIO 수동 검토와 계좌 계획은 별도로 필요합니다."
      },
      {
        "id": "risk_guard",
        "title": "계좌 위험",
        "status": "held",
        "detail": "확인된 계좌·보유 종목과 현금·테마·손실 한도로 요청별 계산이 필요합니다."
      },
      {
        "id": "review",
        "title": "성과 검토",
        "status": "held",
        "detail": "M0: 사전 선언한 별도 OOS와 확률 보정 검증 전입니다. 기존 탐색 순위를 인증하지 않습니다."
      }
    ],
    "candidates": [
      {
        "opportunity_id": "c63db60c87f2900e7e58f725e7d145dff27305cfebfe9ac00a5357ee1ac557b7",
        "symbol": "000001",
        "name": "종목000001",
        "state": "Watch",
        "audit": {
          "status": "passed",
          "reasons": [],
          "independent_sources": 2
        },
        "probability": {
          "kind": "unavailable",
          "bull": null,
          "base": null,
          "bear": null,
          "reason": "사전 선언한 별도 OOS와 확률 보정 검증이 없습니다. 과거 승률은 미래 확률이 아닙니다."
        },
        "invalidation": {
          "price_below": 92,
          "price_above": 102,
          "valid_until": "2026-10-08T02:06:00Z",
          "detail": "진입 상한·손절·진입 창이 무효화 기준입니다. 갭 손실은 계획 손실보다 커질 수 있습니다."
        },
        "missing": [
          "regime",
          "sector",
          "event",
          "sentiment",
          "calibrated_probability"
        ]
      },
      {
        "opportunity_id": "0859a5c2af9d4254ba7d73e3ff1ac36235ab1abf60949e555bde69beb5260ef1",
        "symbol": "000003",
        "name": "종목000003",
        "state": "Watch",
        "audit": {
          "status": "passed",
          "reasons": [],
          "independent_sources": 2
        },
        "probability": {
          "kind": "unavailable",
          "bull": null,
          "base": null,
          "bear": null,
          "reason": "사전 선언한 별도 OOS와 확률 보정 검증이 없습니다. 과거 승률은 미래 확률이 아닙니다."
        },
        "invalidation": {
          "price_below": 92,
          "price_above": 102,
          "valid_until": "2026-10-08T02:06:00Z",
          "detail": "진입 상한·손절·진입 창이 무효화 기준입니다. 갭 손실은 계획 손실보다 커질 수 있습니다."
        },
        "missing": [
          "regime",
          "sector",
          "event",
          "sentiment",
          "calibrated_probability"
        ]
      },
      {
        "opportunity_id": "448c95da92677b78d9bff35e85261239123e0ceca44416e5270703a5e5a2d892",
        "symbol": "000002",
        "name": "종목000002",
        "state": "Watch",
        "audit": {
          "status": "passed",
          "reasons": [],
          "independent_sources": 2
        },
        "probability": {
          "kind": "unavailable",
          "bull": null,
          "base": null,
          "bear": null,
          "reason": "사전 선언한 별도 OOS와 확률 보정 검증이 없습니다. 과거 승률은 미래 확률이 아닙니다."
        },
        "invalidation": {
          "price_below": 92,
          "price_above": 102,
          "valid_until": "2026-10-08T02:06:00Z",
          "detail": "진입 상한·손절·진입 창이 무효화 기준입니다. 갭 손실은 계획 손실보다 커질 수 있습니다."
        },
        "missing": [
          "regime",
          "sector",
          "event",
          "sentiment",
          "calibrated_probability"
        ]
      }
    ],
    "promotion": {
      "stage": "M0",
      "reasons": [
        "predeclared_oos_pending",
        "calibration_pending",
        "manual_approval_required"
      ]
    },
    "contract": {
      "schema_version": 1,
      "policy_version": "desk-evidence-v2",
      "policy_hash": "be6e79dd2df6145d815df3c01fa130a56cf42f08329db470d0fb0abb10f5c41f",
      "decision_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "evidence_snapshot_id": "85cd744cfb875f81c4205215c1566859d23772c3a906aed4f98d0985d62547ac",
      "evidence_status": "ready",
      "market_checks": [
        {
          "symbol": "000001",
          "opportunity_id": "c63db60c87f2900e7e58f725e7d145dff27305cfebfe9ac00a5357ee1ac557b7",
          "status": "passed",
          "reasons": [],
          "valid_until": "2026-10-08T02:06:00Z"
        },
        {
          "symbol": "000003",
          "opportunity_id": "0859a5c2af9d4254ba7d73e3ff1ac36235ab1abf60949e555bde69beb5260ef1",
          "status": "passed",
          "reasons": [],
          "valid_until": "2026-10-08T02:06:00Z"
        },
        {
          "symbol": "000002",
          "opportunity_id": "448c95da92677b78d9bff35e85261239123e0ceca44416e5270703a5e5a2d892",
          "status": "passed",
          "reasons": [],
          "valid_until": "2026-10-08T02:06:00Z"
        }
      ]
    }
  },
  "board": {
    "schema_version": 1,
    "policy_version": "profit-opportunity-v1",
    "decision_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "input_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "source_audit_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "generated_at": "2026-10-08T01:00:00Z",
    "latest_session": "2026-10-07",
    "entry_session": "2026-10-08",
    "valid_until": "2026-10-08T06:30:00Z",
    "status": "ready",
    "research_only": true,
    "live_orders": false,
    "candidates": [
      {
        "opportunity_id": "c63db60c87f2900e7e58f725e7d145dff27305cfebfe9ac00a5357ee1ac557b7",
        "decision_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "input_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "source_audit_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "symbol": "000001",
        "name": "종목000001",
        "market": "KR",
        "strategy_id": "momentum",
        "rank": 1,
        "action": "entry_candidate",
        "current_price": 101,
        "quote_at": "2026-10-08T01:59:00Z",
        "fetched_at": "2026-10-08T01:59:20Z",
        "quote_source": "KIS:J:FHKST03010200+FHKST01010100",
        "valid_until": "2026-10-08T06:30:00Z",
        "reference_weight": 0.05,
        "plan": {
          "basis": "observed_quote_reference",
          "entry_low": 101,
          "entry_high": 102,
          "stop_price": 92,
          "target_price": 116,
          "horizon_sessions": 10
        },
        "ranking": {
          "score": 0.012,
          "calibration_samples": 40,
          "confirmation_samples": 12
        },
        "audit": {
          "status": "passed",
          "independent_validation": false
        },
        "reasons": []
      },
      {
        "opportunity_id": "0859a5c2af9d4254ba7d73e3ff1ac36235ab1abf60949e555bde69beb5260ef1",
        "decision_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "input_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "source_audit_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "symbol": "000003",
        "name": "종목000003",
        "market": "KR",
        "strategy_id": "momentum",
        "rank": 2,
        "action": "entry_candidate",
        "current_price": 101,
        "quote_at": "2026-10-08T01:59:00Z",
        "fetched_at": "2026-10-08T01:59:20Z",
        "quote_source": "KIS:J:FHKST03010200+FHKST01010100",
        "valid_until": "2026-10-08T06:30:00Z",
        "reference_weight": 0.05,
        "plan": {
          "basis": "observed_quote_reference",
          "entry_low": 101,
          "entry_high": 102,
          "stop_price": 92,
          "target_price": 116,
          "horizon_sessions": 10
        },
        "ranking": {
          "score": 0.012,
          "calibration_samples": 40,
          "confirmation_samples": 12
        },
        "audit": {
          "status": "passed",
          "independent_validation": false
        },
        "reasons": []
      },
      {
        "opportunity_id": "448c95da92677b78d9bff35e85261239123e0ceca44416e5270703a5e5a2d892",
        "decision_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "input_fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "source_audit_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "symbol": "000002",
        "name": "종목000002",
        "market": "KR",
        "strategy_id": "momentum",
        "rank": 3,
        "action": "entry_candidate",
        "current_price": 101,
        "quote_at": "2026-10-08T01:59:00Z",
        "fetched_at": "2026-10-08T01:59:20Z",
        "quote_source": "KIS:J:FHKST03010200+FHKST01010100",
        "valid_until": "2026-10-08T06:30:00Z",
        "reference_weight": 0.05,
        "plan": {
          "basis": "observed_quote_reference",
          "entry_low": 101,
          "entry_high": 102,
          "stop_price": 92,
          "target_price": 116,
          "horizon_sessions": 10
        },
        "ranking": {
          "score": 0.012,
          "calibration_samples": 40,
          "confirmation_samples": 12
        },
        "audit": {
          "status": "passed",
          "independent_validation": false
        },
        "reasons": []
      }
    ],
    "reasons": []
  },
  "now": "2026-10-08T02:00:00Z"
};

describe('backend saved desk contract compatibility', () => {
    it('accepts the actual three-candidate saved projection at the public frontend boundary', () => {
        // The backend's fixture supplies the board identity and prices consumed
        // by this desk boundary; full opportunity-board validation is separate.
        const desk = validateAgentDesk(backendSnapshot.desk, backendSnapshot.board as unknown as OpportunityEngine, Date.parse(backendSnapshot.now));
        expect(desk.contract?.evidence_status).toBe('ready');
        expect(desk.candidates).toHaveLength(3);
        expect(desk.contract?.market_checks).toHaveLength(3);
        expect(desk.contract?.market_checks.every(check => check.status === 'passed')).toBe(true);
        expect(desk.order_allowed).toBe(false);
    });
});
