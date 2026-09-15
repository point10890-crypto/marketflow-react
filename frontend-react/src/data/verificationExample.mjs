// Synthetic teaching inputs. These are not market prices or service performance.
export const EXAMPLE_COST_PP = 0.5;
export const EXAMPLE_ROWS = [
    { label: '가상 A', entry: 100, exit: 108, benchmarkPct: 3 },
    { label: '가상 B', entry: 100, exit: 96, benchmarkPct: 3 },
    { label: '가상 C', entry: 100, exit: 102, benchmarkPct: 3 },
    { label: '가상 D', entry: 100, exit: 100, benchmarkPct: 3 },
];
export const EXAMPLE_RESULTS = EXAMPLE_ROWS.map(row => ({ ...row,
    grossPct: (row.exit / row.entry - 1) * 100,
    netPct: (row.exit / row.entry - 1) * 100 - EXAMPLE_COST_PP,
}));
export const EXAMPLE_MEAN_NET = EXAMPLE_RESULTS.reduce((sum, row) => sum + row.netPct, 0) / EXAMPLE_RESULTS.length;
export const EXAMPLE_HIT_RATE = EXAMPLE_RESULTS.filter(row => row.netPct > 0).length / EXAMPLE_RESULTS.length * 100;

export const VERIFICATION_GUIDE = {
    slug: 'signal-verification-worked-example',
    title: 'AI 후보 6건을 검증하는 법 — 적중률·비용·미평가를 함께 읽기',
    description: '가상의 관찰 후보 6건으로 비용 차감 수익률, 평가 표본, 기준지수 비교를 직접 계산합니다. 잘 맞은 신호만 골라 보는 오류를 피하기 위한 재현 가능한 예제입니다.',
    category: 'AI 활용', date: '2026-09-15', updatedDate: '2026-09-15', readMinutes: 8,
    methodology: '이 글의 A~F와 모든 가격·비용·기준지수는 설명을 위해 만든 가상 자료입니다. 계산은 동일한 입력 배열에서 생성하며, MarketFlow의 실제 후보·백테스트·계좌 성과가 아닙니다.',
    sources: [{
        label: 'SEC Investor.gov — Investor Bulletin: Performance Claims',
        url: 'https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47',
        note: '비용, 가상 백테스트, 유리한 기간만 선택하는 문제, 적절한 기준지수 비교를 확인하는 일반 원칙의 참고 자료입니다. 아래 숫자의 출처는 아닙니다.',
    }],
    html: `
<p>AI가 후보를 보여 주었을 때 가장 먼저 확인할 것은 ‘몇 개나 올랐는가’만이 아닙니다.
언제 선택했는지, 그때 실제로 진입할 수 있었는지, 아직 결과를 모르는 후보가 몇 개인지를 함께 봐야 합니다.
이 글은 관찰 기록을 직접 점검할 수 있도록 작은 표 하나를 끝까지 계산합니다.</p>
<h2>먼저 고정할 평가 약속</h2>
<p><strong>아래는 전부 가상 교육 예제이며 서비스의 성과가 아닙니다.</strong>
국내 주식을 관찰한다고 가정하고, 서로 다른 관찰일에 후보 A~F 여섯 건을 저장했습니다. 각 후보의 관찰일을 D라고 부릅니다.
진입은 다음 거래일 D+1 시가, 종료는 D+5 종가로 미리 정합니다. 휴일을 제외한 거래일 기준입니다.
실제 기록에는 D를 달력 날짜·시간·시간대로 바꿔 적고, 종목 코드와 시장도 기록해야 합니다.</p>
<p>비교를 단순하게 만들기 위해 모든 진입 가격을 100으로 정규화했습니다.
왕복 수수료·세금·슬리피지 합계는 진입 금액의 ${EXAMPLE_COST_PP.toFixed(1)}%로 가정합니다.
이는 현재 증권사 요율이 아닙니다. 실제 평가는 시장·계좌·유동성에 맞는 비용으로 다시 계산해야 합니다.</p>
<h2>평가 완료와 평가 불가를 분리하기</h2>
<p>A~D 네 건은 종료 가격을 확인했습니다. E는 종료 가격 누락으로 평가 불가, F는 평가 시점에 D+5가
도래하지 않아 대기 중이라고 가정합니다. E와 F를 손실이나 보합으로 채우지 않습니다.</p>
<div style="overflow-x:auto"><table>
<caption>가상 A~D: 정규화 가격과 비용 차감 결과</caption>
<thead><tr><th scope="col">대상</th><th scope="col">진입</th><th scope="col">종료</th><th scope="col">가격 수익률</th><th scope="col">비용 차감</th></tr></thead>
<tbody>${EXAMPLE_RESULTS.map(row => `<tr><th scope="row">${row.label}</th><td>${row.entry}</td><td>${row.exit}</td><td>${row.grossPct.toFixed(1)}%</td><td>${row.netPct.toFixed(1)}%</td></tr>`).join('')}</tbody></table></div>
<p>계산식은 (종료 가격 ÷ 진입 가격 − 1) × 100 − ${EXAMPLE_COST_PP.toFixed(1)}입니다.
마지막 차감 단위는 퍼센트포인트입니다. A는 8.0 − 0.5 = 7.5%, D는 0.0 − 0.5 = −0.5%가 됩니다.
가격이 그대로여도 비용을 지불하면 순손실입니다.</p>
<h2>적중률 분모가 달라지면 다른 이야기가 됩니다</h2>
<p>이 예제에서는 ‘비용 차감 수익률이 0보다 큰 경우’를 적중으로 정의했습니다.
완료 네 건 중 A와 C 두 건이 적중해 ${EXAMPLE_HIT_RATE.toFixed(0)}%입니다.
전체 여섯 건 중 확정 수익 두 건은 33.3%지만, 이것을 완료 표본의 적중률이라고 부르면 안 됩니다.
화면에는 <strong>전체 6 / 완료 4 / 평가 불가 1 / 대기 1 / 완료 기준 적중률 50%</strong>를 함께 적는 편이 낫습니다.</p>
<p>누락이 급락·거래정지 종목에 집중되면 완료 표본만 봐도 편향될 수 있습니다.
따라서 누락을 제외했다고 끝내지 말고 이유와 나중에 보완했는지를 기록합니다.
손실이 난 B와 D를 표에서 지우는 것은 평가 기준을 바꾸는 행동입니다.</p>
<h2>50% 적중이 시장보다 좋다는 뜻은 아닙니다</h2>
<p>네 건의 동일 비중 평균은 (7.5 − 4.5 + 1.5 − 0.5) ÷ 4 = ${EXAMPLE_MEAN_NET.toFixed(1)}%입니다.
각 후보와 동일한 평가 기간에 적절한 기준지수가 각각 가상으로 3.0% 올랐다면 평균 차이는 ${(EXAMPLE_MEAN_NET - 3).toFixed(1)}%포인트입니다.
이 표의 후보 묶음은 수익이 났지만 그 기준지수보다 낮았습니다.</p>
<p>여기서 1.0%는 완료 후보 네 건의 산술 평균입니다. 순차 재투자 수익률이나 계좌 수익률이 아닙니다.
대기 후보·현금·배당·동시 보유 한도는 반영하지 않았습니다. 기준지수의 가격/총수익 기준과 비용 반영 여부도
실제 평가에서는 명시해야 합니다. 작은 가상 표에서 통계적 우수성을 주장할 수는 없습니다.</p>
<h2>놓친 종목과 잘못 고른 종목도 남기기</h2>
<p>이 예제 기준에서 선택했지만 순수익이 양수가 아닌 B·D는 실패 후보입니다.
반면 선택하지 않았는데 이후 기준을 충족한 종목이 얼마나 되는지는 A~F 표만으로 알 수 없습니다.
누락된 기회를 평가하려면 당시 스캔한 전체 종목과 탈락 이유도 저장해야 합니다.
성공한 후보 목록만으로 탐지기의 전체 성능을 계산할 수 없는 이유입니다.</p>
<h2>다음 분석에 바로 쓸 기록 양식</h2>
<ol>
<li>관찰 시각과 분석 버전, 종목 코드·이름·시장, 데이터 제공자와 원천 시각을 적습니다.</li>
<li>진입 날짜·가격 규칙, 종료 날짜·보유기간, 비용과 기준지수를 결과 확인 전에 정합니다.</li>
<li>완료·대기·평가 불가를 나누고, 제외 사유와 실패 후보도 보존합니다.</li>
<li>당시 알 수 없던 공시나 종가를 과거 판단의 입력에 넣지 않았는지 확인합니다.</li>
<li>평가 후 규칙을 바꿨다면 새 버전으로 남기고, 별도의 이후 기간에서 다시 검증합니다.</li>
</ol>
<p>관찰 결과를 읽을 때는 <a href="/guide/using-ai-signals">AI 신호의 출처와 신선도 확인</a>,
위험 금액을 이해할 때는 <a href="/guide/position-sizing-r">포지션 사이징 가이드</a>를 함께 참고하세요.
이 예제는 검증 질문을 만드는 연습이며 특정 전략의 매매 권유가 아닙니다.</p>`,
};
