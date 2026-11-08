import './bitman-agent-brand.css';

/** Shared dashboard identity. The network illustration is decorative, not live telemetry. */
export function BitManAgentTitle() {
    return (
        <span className="bitman-agent-title">
            <span className="bitman-agent-name">BitMan <span className="bitman-agent-ai">AI</span></span>{' '}
            <span className="bitman-agent-description">주식분석 에이전트</span>
        </span>
    );
}

export function BitManAgentFlow() {
    return (
        <div className="bitman-agent-flow" aria-label="분석 흐름: 정보 수집, 근거 검증, 후보 비교">
            <span>정보 수집</span><i className="fas fa-angle-right" aria-hidden="true" />
            <span>근거 검증</span><i className="fas fa-angle-right" aria-hidden="true" />
            <span>후보 비교</span>
        </div>
    );
}

export function BitManAgentNetwork() {
    return (
        <div className="bitman-agent-network" aria-hidden="true">
            <div className="bitman-agent-orbit" />
            <div className="bitman-agent-wire bitman-agent-wire-a" />
            <div className="bitman-agent-wire bitman-agent-wire-b" />
            <div className="bitman-agent-wire bitman-agent-wire-c" />
            <span className="bitman-agent-node bitman-agent-node-a"><i className="fas fa-chart-line" /></span>
            <span className="bitman-agent-node bitman-agent-node-b"><i className="fas fa-layer-group" /></span>
            <span className="bitman-agent-node bitman-agent-node-c"><i className="fas fa-check" /></span>
            <span className="bitman-agent-core"><i className="fas fa-brain" /></span>
        </div>
    );
}
