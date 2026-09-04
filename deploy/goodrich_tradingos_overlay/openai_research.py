from __future__ import annotations

import json
import re
from pathlib import Path

from openai import OpenAI


class OpenAIConfigurationError(RuntimeError):
    pass


class OpenAIResearchError(RuntimeError):
    pass


class DeepSeekConfigurationError(RuntimeError):
    pass


class DeepSeekResearchError(RuntimeError):
    pass


class ResearchPipelineError(RuntimeError):
    pass


def load_openai_api_key(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise OpenAIConfigurationError("OpenAI API 키 파일을 찾을 수 없습니다.")
    raw = source.read_text(encoding="utf-8-sig").strip()
    match = re.search(r"sk-[A-Za-z0-9_-]{20,}", raw)
    if not match:
        raise OpenAIConfigurationError("OpenAI API 키 파일 형식이 올바르지 않습니다.")
    return match.group(0)


def _instructions() -> str:
    return (
        "You are the bounded AI research reviewer for a Korean stock monitoring system. "
        "Analyze every supplied KIS-verified candidate and return exactly one analysis per "
        "symbol. Never add, remove, reorder, or replace a symbol. Never alter or invent any "
        "market number, rank, target, or stop. A risky candidate must remain present with a "
        "WATCH or REJECT verdict; the upstream verified selection is authoritative. "
        "당신은 한국 주식 리서치 검증 에이전트다. 제공된 KIS 검증 데이터만 사용하고 "
        "모든 종목을 빠짐없이 동일한 순서로 평가한다. 종목·가격·순위·목표가·손절가를 "
        "변경하거나 새로 만들지 않는다. 각 종목의 강점과 핵심 위험을 쉬운 한국어 한 "
        "문장씩 작성하며 수익을 보장하거나 매수 명령을 하지 않는다. JSON만 반환한다."
    )


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "market_summary": {"type": "string"},
            "analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "thesis": {"type": "string"},
                        "risk": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["BUY_CANDIDATE", "WATCH", "REJECT"],
                        },
                        "conviction_score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                        },
                        "monitoring_focus": {"type": "string"},
                    },
                    "required": [
                        "symbol",
                        "thesis",
                        "risk",
                        "verdict",
                        "conviction_score",
                        "monitoring_focus",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["market_summary", "analyses"],
        "additionalProperties": False,
    }


def _verified_input(candidates: list[dict]) -> str:
    return json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))


def _completed_output_text(response: object) -> str:
    if (
        str(getattr(response, "status", "")).lower() != "completed"
        or getattr(response, "error", None) is not None
        or getattr(response, "incomplete_details", None) is not None
    ):
        raise ValueError("리서치 응답이 완료되지 않았습니다.")
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise ValueError("리서치 응답 본문이 비어 있습니다.")
    return output_text


def _validate_result(result: object, candidates: list[dict]) -> dict:
    if (
        not isinstance(result, dict)
        or set(result) != {"market_summary", "analyses"}
        or not isinstance(result.get("market_summary"), str)
    ):
        raise ValueError("리서치 응답의 시장 요약 형식이 올바르지 않습니다.")
    analyses = result.get("analyses")
    if not isinstance(analyses, list):
        raise ValueError("리서치 응답의 종목 분석 형식이 올바르지 않습니다.")

    expected = [str(item.get("symbol") or "") for item in candidates]
    received: list[str] = []
    normalized: list[dict] = []
    for row in analyses:
        if not isinstance(row, dict) or set(row) != {
            "symbol",
            "thesis",
            "risk",
            "verdict",
            "conviction_score",
            "monitoring_focus",
        }:
            raise ValueError("리서치 종목 분석 형식이 올바르지 않습니다.")
        symbol = row.get("symbol")
        verdict = row.get("verdict")
        conviction = row.get("conviction_score")
        if not isinstance(symbol, str):
            raise ValueError("리서치 종목 코드 형식이 올바르지 않습니다.")
        if verdict not in {"BUY_CANDIDATE", "WATCH", "REJECT"}:
            raise ValueError("리서치 판정 형식이 올바르지 않습니다.")
        if type(conviction) is not int:
            raise ValueError("리서치 확신도 형식이 올바르지 않습니다.")
        if not 0 <= conviction <= 100:
            raise ValueError("리서치 확신도 범위가 올바르지 않습니다.")
        for field in ("thesis", "risk", "monitoring_focus"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError("리서치 설명 형식이 올바르지 않습니다.")
        received.append(symbol)
        normalized.append(
            {
                "symbol": symbol,
                "thesis": row["thesis"].strip(),
                "risk": row["risk"].strip(),
                "verdict": verdict,
                "conviction_score": conviction,
                "monitoring_focus": row["monitoring_focus"].strip(),
            }
        )
    if received != expected or len(set(received)) != len(received):
        raise ValueError("리서치 응답 종목과 순서가 KIS 검증 후보와 일치하지 않습니다.")
    return {"market_summary": result["market_summary"].strip(), "analyses": normalized}


class OpenAIResearchAgent:
    def __init__(self, credentials_file: str, model: str) -> None:
        self.credentials_file = credentials_file
        self.model = model

    def analyze(self, candidates: list[dict]) -> dict:
        client = OpenAI(
            api_key=load_openai_api_key(self.credentials_file),
            timeout=15,
            max_retries=0,
        )
        try:
            response = client.responses.create(
                model=self.model,
                reasoning={"effort": "low"},
                instructions=_instructions(),
                input=f"검증된 KIS 후보 데이터:\n{_verified_input(candidates)}",
                max_output_tokens=2400,
                text={
                    "verbosity": "low",
                    "format": {
                        "type": "json_schema",
                        "name": "fund_manager_research",
                        "strict": True,
                        "schema": _schema(),
                    },
                },
                store=False,
            )
            result = _validate_result(
                json.loads(_completed_output_text(response)), candidates
            )
        except OpenAIConfigurationError:
            raise
        except Exception as error:
            raise OpenAIResearchError("OpenAI 백업 리서치 호출에 실패했습니다.") from error
        result.update(
            {
                "provider": "openai",
                "response_id": str(response.id or ""),
                "model": self.model,
            }
        )
        return result


class DeepSeekResearchAgent:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip() or "deepseek-v4-pro"
        self.base_url = base_url.rstrip("/")

    def analyze(self, candidates: list[dict]) -> dict:
        if len(self.api_key) < 20:
            raise DeepSeekConfigurationError("DeepSeek API 키가 설정되지 않았습니다.")
        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=30,
                max_retries=0,
            )
            response = client.responses.create(
                model=self.model,
                instructions=_instructions(),
                input=f"검증된 KIS 후보 데이터:\n{_verified_input(candidates)}",
                reasoning={"effort": "max"},
                max_output_tokens=4096,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "fund_manager_research",
                        "schema": _schema(),
                    }
                },
                store=False,
            )
            result = _validate_result(
                json.loads(_completed_output_text(response)), candidates
            )
        except DeepSeekConfigurationError:
            raise
        except Exception as error:
            raise DeepSeekResearchError("DeepSeek 리서치 호출에 실패했습니다.") from error
        result.update(
            {
                "provider": "deepseek",
                "response_id": str(response.id or ""),
                "model": self.model,
            }
        )
        return result


class DeepSeekFirstResearchAgent:
    def __init__(
        self,
        *,
        deepseek_api_key: str,
        deepseek_model: str,
        openai_credentials_file: str,
        openai_model: str,
        deepseek_base_url: str = "https://api.deepseek.com",
    ) -> None:
        self.deepseek = DeepSeekResearchAgent(
            api_key=deepseek_api_key,
            model=deepseek_model,
            base_url=deepseek_base_url,
        )
        self.openai = OpenAIResearchAgent(
            credentials_file=openai_credentials_file,
            model=openai_model,
        )

    def analyze(self, candidates: list[dict]) -> dict:
        try:
            return self.deepseek.analyze(candidates)
        except (DeepSeekConfigurationError, DeepSeekResearchError):
            try:
                result = self.openai.analyze(candidates)
            except (OpenAIConfigurationError, OpenAIResearchError) as error:
                raise ResearchPipelineError(
                    "DeepSeek 분석과 OpenAI 백업 분석이 모두 실패했습니다."
                ) from error
            result["fallback_from"] = "deepseek"
            result["storage_provider"] = "openai_fallback_from_deepseek"
            return result
