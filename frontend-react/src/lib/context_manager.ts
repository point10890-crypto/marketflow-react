export interface ContextEntry {
  type: 'constraint' | 'file' | 'summary';
  content: string;
  source?: string;
}

const SOURCE_FILES = Object.keys(
  import.meta.glob<string>('../**/*.{ts,tsx}', { eager: false }),
);

export class ProjectMemory {
  private pinnedConstraints: string[];
  private recentTasks: string[];
  private readonly maxWindowSize: number;

  constructor(globalConstraints: string[] = [], maxWindowSize = 10) {
    this.pinnedConstraints = [...globalConstraints];
    this.recentTasks = [];
    this.maxWindowSize = maxWindowSize;
  }

  public getRelevantContext(currentTask: string): ContextEntry[] {
    const activeContext: ContextEntry[] = [];

    // 1. 전역 제약 조건은 항상 고정(pin)
    //    예: "사용자 로그인 기능 구현 금지"
    activeContext.push(...this.getGlobalConstraints());

    // 2. 현재 하위 작업과 직접 관련된 파일만 가져옴
    const hotFiles = this.vectorSearchCodebase(currentTask);
    activeContext.push(...hotFiles);

    // 3. 메모리 압축: 이미 완료된 과거 코드는 제거
    this.runGarbageCollection();

    this.recordTask(currentTask);
    return activeContext;
  }

  public addGlobalConstraint(constraint: string): void {
    if (!this.pinnedConstraints.includes(constraint)) {
      this.pinnedConstraints.push(constraint);
    }
  }

  public getGlobalConstraints(): ContextEntry[] {
    return this.pinnedConstraints.map((constraint) => ({
      type: 'constraint',
      content: constraint,
      source: 'global',
    }));
  }

  public runGarbageCollection(): void {
    if (this.recentTasks.length <= this.maxWindowSize) {
      return;
    }

    const overflow = this.recentTasks.length - this.maxWindowSize;
    const removed = this.recentTasks.splice(0, overflow);

    // 이전 단계들을 요약하고 관련 없는 파일들을 버림
    this.pinnedConstraints.push(
      `요약: 이전 ${removed.length}개의 작업은 완료되어 현재 컨텍스트에서 제거되었습니다.`,
    );
    if (this.pinnedConstraints.length > this.maxWindowSize) {
      this.pinnedConstraints = this.pinnedConstraints.slice(-this.maxWindowSize);
    }
  }

  private recordTask(task: string): void {
    this.recentTasks.push(task);
    if (this.recentTasks.length > this.maxWindowSize * 2) {
      this.recentTasks = this.recentTasks.slice(-this.maxWindowSize);
    }
  }

  private vectorSearchCodebase(task: string): ContextEntry[] {
    const normalizedTask = task.trim().toLowerCase();
    const tokens = normalizedTask.split(/\s+/).filter(Boolean);

    const candidateFiles = SOURCE_FILES.filter((filename) =>
      tokens.some((word) => filename.toLowerCase().includes(word)),
    );

    if (candidateFiles.length > 0) {
      return candidateFiles.map((filename) => ({
        type: 'file',
        content: `관련 파일: ${filename}`,
        source: 'vector-search',
      }));
    }

    return [
      {
        type: 'summary',
        content: '관련 파일을 찾을 수 없습니다. 일반적인 코드 컨텍스트로 처리합니다.',
        source: 'vector-search',
      },
    ];
  }
}
