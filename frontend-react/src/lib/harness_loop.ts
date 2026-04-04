import { callIsolatedLLMWorker } from './worker';
import { ProjectMemory, ContextEntry } from './context_manager';
import type { HarnessConstraints } from './llm_utils';

export async function runHarnessLoop(
  task: string,
  constraints: HarnessConstraints,
): Promise<string> {
  const memory = new ProjectMemory();
  let isTaskComplete = false;
  let attemptCount = 0;
  const MAX_ATTEMPTS = Math.min(5, constraints.maxIterations);
  let currentTask = task;

  while (!isTaskComplete && attemptCount < MAX_ATTEMPTS) {
    const contextEntries = memory.getRelevantContext(currentTask);
    const context = contextEntries
      .map((entry) => `[${entry.type}] ${entry.content}`)
      .join('\n');
    const constraintList = [
      `mode=${constraints.mode}`,
      `maxIterations=${constraints.maxIterations}`,
      `expectedOutput=${constraints.expectedOutput}`,
      `requireConfirmation=${constraints.requireConfirmation}`,
    ];

    const generatedCode = await callIsolatedLLMWorker(
      'WRITE_CODE',
      currentTask,
      context,
      constraintList,
    );

    const verificationResult = await runAutomatedTests(generatedCode);

    if (verificationResult.passed) {
      isTaskComplete = true;
      console.log('작업이 완료되고 검증되었습니다.');
      return generatedCode;
    }

    console.warn('검증 실패. AI를 수정 루프에 집어넣습니다...', verificationResult.errorTrace);
    currentTask = `코드가 다음 에러를 발생시켰습니다:\n${verificationResult.errorTrace}\n수정하세요.`;
    attemptCount += 1;
  }

  throw new Error(
    '하네스 중단: AI가 제한된 시도 횟수 내에 문제를 해결하지 못했습니다.',
  );
}

interface VerificationResult {
  passed: boolean;
  errorTrace: string;
  details?: string;
}

async function runAutomatedTests(generatedCode: string): Promise<VerificationResult> {
  // TODO: 실제 테스트 실행 로직을 여기에 연결합니다.
  const codeLooksLikeCode = /(?:function\s+|const\s+|let\s+|var\s+|class\s+|export\s+)/.test(
    generatedCode,
  );

  if (!codeLooksLikeCode) {
    return {
      passed: false,
      errorTrace: 'LLM 출력에 코드 구조가 포함되지 않았습니다.',
    };
  }

  return {
    passed: true,
    errorTrace: '',
  };
}
