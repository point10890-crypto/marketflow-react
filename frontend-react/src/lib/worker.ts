type LLMRole = 'WRITE_CODE' | 'SECURITY_REVIEW';

interface LLMGeneratePayload {
  system: string;
  user_message: string;
  context_data: string;
  temperature: number;
}

const llmApi = {
  async generate(payload: LLMGeneratePayload): Promise<string> {
    // TODO: 실제 LLM API 호출로 교체하세요.
    return `// LLM generated response for action:\n// ${payload.user_message}\n// context:\n${payload.context_data}`;
  },
};

export async function callIsolatedLLMWorker(
  role: LLMRole,
  task: string,
  context: string,
  constraints: string[],
): Promise<string> {
  let systemPrompt = '';

  if (role === 'WRITE_CODE') {
    systemPrompt =
      '당신은 전문 실행 에이전트입니다. ' +
      '코드를 작성하세요. 설명하지 마세요. ' +
      '마크다운을 쓰지 마세요. 순수한 코드만 출력하세요.';
  } else if (role === 'SECURITY_REVIEW') {
    systemPrompt =
      '당신은 보안 감사관입니다. ' +
      '취약점을 찾으세요. 기능 코드를 작성하지 마세요.';
  }

  const userMessage = `작업: ${task}\n제약조건: ${constraints.join(', ')}`;

  const response = await llmApi.generate({
    system: systemPrompt,
    user_message: userMessage,
    context_data: context,
    temperature: 0.0,
  });

  return response;
}
