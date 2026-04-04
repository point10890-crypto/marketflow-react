export interface Intent {
  isAmbiguous: boolean;
  isActionable: boolean;
  category: 'action' | 'conversation' | 'other';
  confidence: number;
}

export interface Constraints {
  maxIterations: number;
  mode: 'safe' | 'balanced' | 'aggressive';
  expectedOutput: 'code' | 'response' | 'analysis';
}

export interface HarnessConstraints extends Constraints {
  requireConfirmation: boolean;
}

const ACTION_PATTERNS = [
  'fix',
  'implement',
  'update',
  'create',
  'refactor',
  'remove',
  'add',
  'build',
  'write',
  'generate',
  'convert',
  '수정',
  '구현',
  '추가',
  '삭제',
  '생성',
  '리팩터',
  '고쳐',
  '작성',
  '바꿔',
  '개선',
];

const AMBIGUOUS_PATTERNS = [
  'what do you think',
  'help me with',
  'i need advice',
  'tell me',
  'suggest',
  'what should i do',
  'i want to know',
  '어떻게 하는지',
  '도와줘',
  '알려줘',
  '추천',
  '어떻게 생각해',
  '의견',
  '조언',
];

export function extractIntent(userPrompt: string): Intent {
  const normalized = userPrompt.trim().toLowerCase();
  const isActionable = ACTION_PATTERNS.some((pattern) => normalized.includes(pattern));
  const isAmbiguous =
    AMBIGUOUS_PATTERNS.some((pattern) => normalized.includes(pattern)) && !isActionable;

  const category: Intent['category'] = isActionable ? 'action' : isAmbiguous ? 'conversation' : 'other';
  const confidence = isActionable ? 0.95 : isAmbiguous ? 0.65 : 0.5;

  return {
    isAmbiguous,
    isActionable,
    category,
    confidence,
  };
}

export function buildConstraints(intent: Intent): HarnessConstraints {
  return {
    maxIterations: intent.isActionable ? 4 : 2,
    mode: intent.category === 'action' ? 'safe' : 'balanced',
    expectedOutput: intent.category === 'action' ? 'code' : 'analysis',
    requireConfirmation: !intent.isActionable,
  };
}

export async function triggerDeepInterview(userPrompt: string): Promise<string> {
  const followUp = [
    '무엇을 달성하려고 하나요?',
    '결과물은 어떤 형태여야 하나요?',
    '추가적인 제약조건(언어, 형식, 프레임워크 등)이 있나요?',
  ].join(' ');

  return `요구사항이 모호합니다. 아래 질문에 답해주세요:\n${followUp}\n\n원본: "${userPrompt}"`;
}

export async function sendToStandardLLM(userPrompt: string): Promise<string> {
  return `일반 LLM 채팅 모드로 전달 중입니다: "${userPrompt}"`;
}
