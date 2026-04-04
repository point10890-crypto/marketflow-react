import { runHarnessLoop } from './harness_loop';
import {
  extractIntent,
  buildConstraints,
  triggerDeepInterview,
  sendToStandardLLM,
  HarnessConstraints,
} from './llm_utils';

export async function handleUserInput(userPrompt: string): Promise<string> {
  // 1. 프롬프트의 의도를 먼저 분석합니다.
  const intent = extractIntent(userPrompt);

  // 2. 요구사항이 모호하다면, 소크라테스식 인터뷰 하네스를 트리거
  //    → AI가 잘못된 요구사항으로 코드를 환각하는 것을 방지
  if (intent.isAmbiguous) {
    return triggerDeepInterview(userPrompt);
  }

  // 3. 명확하고 실행 가능한 작업이면, 실행 하네스로 라우팅
  if (intent.isActionable) {
    const constraints: HarnessConstraints = buildConstraints(intent);
    // 일반 LLM 호출 대신 지속적인(persistent) 루프에 작업을 넘김
    return runHarnessLoop(userPrompt, constraints);
  }

  // 그 외의 경우 일반 채팅으로 폴백
  return sendToStandardLLM(userPrompt);
}
