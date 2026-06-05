"""공지글 #24 업데이트 — MarketFlow 완전 가이드"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models.community import Post, db

TITLE = "MarketFlow 완전 가이드 — 모든 기능 사용법 · 활용 팁 · 실전 루틴"

CONTENT = """
<p>안녕하세요, MarketFlow 운영진입니다.</p>
<p>MarketFlow를 처음 사용하시는 분들과, 아직 모든 기능을 100% 활용하지 못하고 계셨던 분들을 위해 <strong>앱 전체 기능 가이드</strong>를 준비했습니다. 이 글 하나로 MarketFlow의 모든 메뉴와 활용법을 마스터하실 수 있습니다.</p>

<hr>

<h2>시작하기</h2>
<p>MarketFlow는 <strong>KR(국내), US(미국), Crypto(암호화폐)</strong> 3개 시장을 하나의 대시보드에서 분석할 수 있는 올인원 트레이딩 플랫폼입니다.</p>
<ul>
<li><strong>회원가입 → 관리자 승인 → Pro 등급 부여</strong> 순서로 이용이 시작됩니다</li>
<li>PC 브라우저, 모바일 PWA(앱 설치) 모두 지원합니다</li>
<li>내 계정 페이지에서 <strong>"앱 설치하기"</strong> 버튼을 눌러 홈화면에 추가하면 네이티브 앱처럼 사용 가능합니다</li>
</ul>

<hr>

<h2>Summary (메인 대시보드)</h2>
<p>로그인 후 가장 먼저 보이는 화면입니다.</p>
<ul>
<li><strong>멀티 마켓 티커</strong>: KOSPI, KOSDAQ, S&P500, 나스닥, BTC, ETH 등 주요 지수 실시간 현황</li>
<li><strong>각 마켓 포털 링크</strong>: 원클릭으로 KR/US/Crypto 상세 페이지 이동</li>
<li><strong>AI 브리핑 프리뷰</strong>: 오늘의 시장 핵심 요약</li>
</ul>

<hr>

<h2>Briefing (시장 브리핑 포털)</h2>
<p>AI가 매일 생성하는 시장 종합 분석 보고서입니다.</p>
<ul>
<li><strong>시장 센티먼트</strong>: 공포/탐욕 지수, VIX 변동성 지수</li>
<li><strong>Decision Signal</strong>: AI 종합 매매 신호 (Bullish/Bearish)</li>
<li><strong>섹터 로테이션</strong>: 자금 이동 흐름 분석</li>
<li><strong>Smart Money Top Picks</strong>: AI가 선별한 핵심 종목</li>
</ul>
<p><strong>활용 팁</strong>: 매일 아침 브리핑을 확인하고 시장 방향성을 먼저 판단한 뒤 개별 종목을 분석하세요.</p>

<hr>

<h2>VCP Enhanced (통합 VCP 스크리닝)</h2>
<p>마크 미너비니의 <strong>VCP(변동성 축소 패턴)</strong> 전략을 3개 시장에서 통합 스크리닝합니다.</p>
<ul>
<li><strong>탭 전환</strong>으로 KR / US / Crypto 시장별 VCP 종목 확인</li>
<li><strong>날짜 선택</strong>으로 과거 데이터도 조회 가능</li>
<li><strong>Composite Score</strong>: 0~100점 종합 점수 (Textbook/Strong/Good 등급)</li>
<li><strong>세부 점수</strong>: Trend Template, VCP Pattern, Volume, Pivot Proximity, Relative Strength</li>
<li><strong>Entry Ready</strong>: 매수 진입 가능 상태 표시</li>
<li><strong>Gate 상태</strong>: 시장 전체의 GREEN/YELLOW/RED 신호</li>
</ul>
<p><strong>활용 팁</strong>: Gate가 GREEN일 때 Composite Score 70 이상 + Entry Ready인 종목에 집중하세요. Gate RED에서는 관망이 유리합니다.</p>

<hr>

<h2>W Pattern (웨이브 패턴)</h2>
<p>AI가 W패턴, M패턴 등 하모닉 패턴을 자동 감지합니다.</p>
<ul>
<li><strong>패턴 분류</strong>: W(이중바닥), M(이중천장) 등</li>
<li><strong>Confidence Score</strong>: 패턴 신뢰도 0~100%</li>
<li><strong>완성도</strong>: 패턴 진행 퍼센트</li>
<li><strong>Neckline 가격</strong>: 돌파 기준선</li>
<li><strong>거래량 확인</strong>: Volume Confirmation 여부</li>
</ul>

<hr>

<h2>KR 마켓 (국내 주식)</h2>

<h3>KR Overview</h3>
<p>국내 시장 전체 현황을 한눈에 파악할 수 있습니다.</p>
<ul>
<li><strong>Market Gate 게이지</strong>: 시장 심리를 -180 ~ +100 아크 게이지로 시각화</li>
<li><strong>KOSPI/KOSDAQ 지수</strong>: 실시간 등락률</li>
<li><strong>백테스트 통계</strong>: VCP 승률, 종가베팅 성과 요약</li>
</ul>

<h3>주도주LIVE</h3>
<p><strong>장중 실시간</strong>으로 시장을 주도하는 종목을 포착합니다.</p>
<ul>
<li><strong>S/A/B 등급</strong>: 100점 만점 채점 (거래대금 30 + 모멘텀 25 + 수급 25 + 급증 10 + 섹터 10)</li>
<li><strong>실시간 갱신</strong>: 장중 5초 간격으로 업데이트</li>
<li><strong>투자자 수급</strong>: 외국인/기관 순매수 현황</li>
<li><strong>AI 테마</strong>: AI가 부여한 테마 태그 (예: "AI 반도체", "2차전지")</li>
<li><strong>52주 신고가 거리</strong>: ATH 대비 현재 위치</li>
</ul>
<p><strong>활용 팁</strong>: S등급 종목이 외국인+기관 동시 순매수이면서 AI 테마가 부여된 경우, 시장 주도 테마의 핵심 종목일 가능성이 높습니다.</p>

<h3>종가베팅 (Close Bet)</h3>
<p><strong>매일 오후 3:10</strong>에 AI가 자동 분석하여 다음 날 상승 가능성이 높은 종목을 추천합니다.</p>
<ul>
<li><strong>20점 만점 채점</strong>: 뉴스(3) + 거래대금(3) + 차트(2) + 캔들(1) + 기간조정(1) + 수급(2) + 공시(2) + 애널리스트(3) + 재무(3)</li>
<li><strong>S/A/B/C 등급</strong>: S급(9점이상, 500억이상) > A급(7점이상, 100억이상) > B급(5점이상) > C급(탈락)</li>
<li><strong>Multi-AI Consensus</strong>: Gemini + GPT-4o 두 AI가 독립 선별하여 교집합 종목은 CONSENSUS 태그</li>
<li><strong>R 기반 포지션 사이징</strong>: 자본금 대비 최적 매수 수량 자동 계산</li>
<li><strong>DART 공시 반영</strong>: 자사주 매입, 무상증자 등 호재 공시를 점수에 가산</li>
</ul>
<p><strong>활용 팁</strong>: Market Gate가 RISK_ON일 때 S급 CONSENSUS 종목에 집중하세요. C등급은 매매 대상이 아닙니다.</p>

<h3>성과 히스토리 / Track Record</h3>
<ul>
<li>종가베팅 시그널의 실제 수익률 추적</li>
<li>일별 등급별 성과 요약 및 30일 롤링 히스토리</li>
<li>과거 시그널 전체의 날짜별, 등급별 분포와 수익률 통계</li>
</ul>

<h3>AI Chart (KR)</h3>
<p>AI가 기술적 분석을 수행하여 BUY/HOLD/SELL 시그널을 생성합니다.</p>
<ul>
<li><strong>신뢰도</strong>: 0~100% Confidence Score</li>
<li><strong>기술 지표</strong>: 이동평균선 정배열, RSI, 거래량 추세</li>
</ul>

<hr>

<h2>US 마켓 (미국 주식)</h2>

<h3>US Overview</h3>
<ul>
<li><strong>시장 레짐</strong>: Risk-On / Risk-Off 감지</li>
<li><strong>주요 지수</strong>: SPY, QQQ, IWM, DXY, VIX 등</li>
<li><strong>누적 수익률</strong>: 포트폴리오 성과 추적</li>
</ul>

<h3>ETF Flows</h3>
<p>주요 ETF의 자금 유출입을 추적하여 <strong>큰손들의 자금 흐름</strong>을 파악합니다.</p>
<ul>
<li><strong>Flow Score</strong>: 5일/20일 자금 유입량 점수화</li>
<li><strong>카테고리 필터</strong>: 섹터별, 자산별 분류</li>
<li><strong>센티먼트 분석</strong>: 시장 전체 Risk-On/Off 점수</li>
<li><strong>AI 분석</strong>: 전체 자금 흐름에 대한 AI 코멘터리</li>
</ul>
<p><strong>활용 팁</strong>: ETF Flow가 양(+)이면서 가격도 상승 중인 섹터에 주목하세요. 자금이 빠지는 섹터는 피하는 것이 좋습니다.</p>

<h3>AI Chart (US)</h3>
<p>미국 주식 AI 기술적 분석. BUY/HOLD/SELL 신호와 Confidence 제공.</p>

<hr>

<h2>Crypto 마켓 (암호화폐)</h2>
<ul>
<li><strong>BTC/ETH 도미넌스</strong>: 시장 점유율 변화</li>
<li><strong>Gate Score</strong>: 암호화폐 시장 전체 심리</li>
<li><strong>Top Gainers/Losers</strong>: 급등/급락 코인</li>
<li><strong>VCP Signals</strong>: 암호화폐 변동성 축소 패턴 스크리닝</li>
</ul>

<hr>

<h2>Tools (분석 도구)</h2>

<h3>ProPicks (종목 심층 분석)</h3>
<ul>
<li><strong>애널리스트 컨센서스</strong>: Strong Buy~Strong Sell 분포 및 평균 점수</li>
<li><strong>목표가</strong>: 현재가 대비 고/저/평균/중앙값 목표가 및 상승 여력</li>
<li><strong>핵심 지표</strong>: PER, PBR, 시가총액, 배당수익률, 베타, 52주 고저</li>
<li><strong>재무 건전성</strong>: ROE, 부채비율, 매출 성장률, 영업이익률 종합 점수</li>
</ul>
<p><strong>활용 팁</strong>: VCP나 종가베팅에서 발견한 종목을 ProPicks에서 한 번 더 검증하세요. 재무 건전성 점수가 낮은 종목은 주의가 필요합니다.</p>

<h3>DART 심층분석</h3>
<p>OpenDART 전자공시 데이터를 활용한 기업 공시 분석. 자사주 매입, 무상증자, 합병 등 주가에 영향을 미치는 공시를 자동 탐지합니다.</p>

<hr>

<h2>커뮤니티</h2>
<ul>
<li><strong>공지사항</strong>: 운영진 공지 (지금 읽고 계신 게시판입니다!)</li>
<li><strong>자유게시판</strong>: 자유로운 투자 이야기</li>
<li><strong>종목분석</strong>: 개별 종목 분석글 공유</li>
<li><strong>매매일지</strong>: 매매 기록 공유 및 복기</li>
<li><strong>Pro 라운지</strong>: Pro 등급 이상 전용 게시판</li>
<li><strong>수식 마켓</strong>: 트레이딩 수식/조건검색식 거래</li>
<li><strong>AI 로또분석</strong>: AI 기반 로또 번호 분석</li>
</ul>

<hr>

<h2>내 계정</h2>
<ul>
<li><strong>구독 상태</strong>: 현재 등급, 만료일 확인</li>
<li><strong>구독 연장</strong>: 계좌이체 후 연장 요청</li>
<li><strong>비밀번호 변경</strong>: 8자 이상, 영문+숫자 필수 (강도 인디케이터 제공)</li>
<li><strong>앱 설치</strong>: PWA 원클릭 설치</li>
</ul>

<hr>

<h2>MarketFlow 실전 활용 루틴 (추천)</h2>

<h3>매일 아침 (시장 개장 전)</h3>
<ol>
<li>Briefing에서 AI 시장 분석 확인하여 오늘의 방향성 판단</li>
<li>VCP Enhanced에서 Gate 상태 확인 (GREEN/YELLOW/RED)</li>
<li>US ETF Flows로 글로벌 자금 흐름 체크</li>
</ol>

<h3>장중</h3>
<ol>
<li><strong>주도주LIVE</strong>에서 S등급 종목 실시간 모니터링</li>
<li>관심 종목을 ProPicks에서 재무 건전성 검증</li>
</ol>

<h3>장 마감 후 (15:10~)</h3>
<ol>
<li><strong>종가베팅</strong> 결과 확인하여 S/A급 시그널 체크</li>
<li>AI Chart에서 BUY 시그널 + 높은 Confidence 종목 크로스체크</li>
<li>성과 히스토리에서 과거 시그널 수익률 참고</li>
</ol>

<hr>

<h2>참고사항</h2>
<ul>
<li>MarketFlow의 모든 분석은 <strong>투자 참고 자료</strong>이며, 투자 판단의 최종 책임은 본인에게 있습니다</li>
<li>데이터는 스케줄러에 의해 자동 갱신됩니다 (KR: 장 마감 후, US: 새벽 4시, Crypto: 4시간 간격)</li>
<li>문의사항은 커뮤니티 자유게시판이나 텔레그램 채널을 이용해 주세요</li>
</ul>

<p>MarketFlow와 함께 성공적인 투자 여정이 되시길 바랍니다. 감사합니다!</p>
<p><strong>MarketFlow 운영진 드림</strong></p>
""".strip()

app = create_app()
with app.app_context():
    post = db.session.get(Post, 24)
    if post:
        post.title = TITLE
        post.content = CONTENT
        db.session.commit()
        print(f"[OK] Post updated: id={post.id}")
        print(f"[OK] Content length: {len(post.content)} chars")
    else:
        print("[ERROR] Post 24 not found")
