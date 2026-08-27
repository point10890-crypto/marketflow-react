import { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { PublicShell } from '@/components/public/PublicShell';
import { useSeo } from '@/lib/seo';

/**
 * 정책·정보 페이지 3종 (공개) — /privacy, /terms, /about.
 * AdSense 심사 필수 페이지. 광고는 싣지 않는다(정책 페이지 관례).
 */

function PolicyLayout({ label, title, updated, path, description, children }: {
    label: string; title: string; updated?: string; path: string; description: string; children: ReactNode;
}) {
    useSeo({ title: `${title} | MarketFlow`, description, path });
    return (
        <PublicShell section={label.toLowerCase()}>
            <div className="mx-auto max-w-[760px] px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                <div className="pub-rise">
                    <div className="pub-label">// {label}</div>
                    <h1 className="mt-2 text-3xl font-black tracking-tight text-white sm:text-4xl">{title}</h1>
                    {updated && (
                        <p className="mt-2 font-mono text-[11px] text-gray-600">시행일 {updated}</p>
                    )}
                </div>
                <div className="pub-policy pub-rise mt-8" style={{ animationDelay: '80ms' }}>
                    {children}
                </div>
            </div>
        </PublicShell>
    );
}

export function PrivacyPage() {
    return (
        <PolicyLayout label="PRIVACY" title="개인정보처리방침" updated="2026-08-17" path="/privacy"
                      description="MarketFlow 개인정보처리방침 — 수집 항목, 이용 목적, 보유·파기 원칙, Google AdSense 광고 쿠키, 이용자의 권리와 문의처를 안내합니다.">
            <p>
                MarketFlow(이하 "서비스")는 이용자의 개인정보를 소중히 여기며, 「개인정보 보호법」 등 관련 법령을
                준수합니다. 본 방침은 서비스가 어떤 정보를 수집하고 어떻게 이용·보관·파기하는지를 설명합니다.
            </p>

            <h2>1. 수집하는 개인정보 항목</h2>
            <ul>
                <li><strong>회원가입 시</strong>: 이메일 주소, 이름(닉네임), 비밀번호(단방향 암호화 저장)</li>
                <li><strong>구독 신청 시</strong>: 입금자명, 선택 플랜</li>
                <li><strong>자동 수집</strong>: 서비스 이용 기록, 접속 일시, 브라우저 정보(쿠키 및 유사 기술)</li>
            </ul>

            <h2>2. 개인정보의 이용 목적</h2>
            <ul>
                <li>회원 식별, 로그인 및 구독 상태 관리</li>
                <li>구독 결제(계좌이체) 확인 및 승인 처리</li>
                <li>서비스 공지, 구독 만료 안내 등 필수 알림</li>
                <li>서비스 품질 개선 및 부정 이용 방지</li>
            </ul>

            <h2>3. 보유 및 파기</h2>
            <p>
                개인정보는 회원 탈퇴 시 지체 없이 파기합니다. 단, 관련 법령에 따라 보존이 필요한 정보(결제·정산
                기록 등)는 해당 법령이 정한 기간 동안 분리 보관 후 파기합니다.
            </p>

            <h2>4. 광고 및 쿠키 (Google AdSense)</h2>
            <p>
                서비스의 공개 페이지에는 Google AdSense 광고가 게재될 수 있습니다. Google 을 포함한 제3자 광고
                사업자는 쿠키 및 광고 식별자를 사용하여 이용자의 이전 방문 기록에 기반한 맞춤 광고를 표시할 수
                있습니다.
            </p>
            <ul>
                <li>
                    Google 의 광고 쿠키 사용에 대한 자세한 내용은{' '}
                    <a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener noreferrer">
                        Google 광고 정책
                    </a>
                    에서 확인할 수 있습니다.
                </li>
                <li>
                    이용자는{' '}
                    <a href="https://adssettings.google.com" target="_blank" rel="noopener noreferrer">
                        Google 광고 설정
                    </a>
                    에서 맞춤 광고를 비활성화할 수 있으며, 브라우저 설정을 통해 쿠키 저장을 거부할 수 있습니다.
                </li>
            </ul>

            <h2>5. 제3자 제공</h2>
            <p>
                서비스는 이용자의 개인정보를 외부에 판매하거나 제공하지 않습니다. 다만 법령에 근거한 요청이 있는
                경우는 예외로 합니다.
            </p>

            <h2>6. 이용자의 권리</h2>
            <p>
                이용자는 언제든지 자신의 개인정보를 조회·수정하거나 삭제(회원 탈퇴)를 요청할 수 있습니다. 관련
                요청은 아래 문의처로 연락해 주세요.
            </p>

            <h2>7. 문의처</h2>
            <p>
                개인정보 관련 문의: <a href="mailto:point10890@gmail.com">point10890@gmail.com</a>
            </p>
        </PolicyLayout>
    );
}

export function TermsPage() {
    return (
        <PolicyLayout label="TERMS" title="이용약관" updated="2026-08-17" path="/terms"
                      description="MarketFlow 이용약관 — 서비스 범위, 구독·결제·환불 규정, 투자 정보 면책, 이용자의 의무를 규정합니다.">
            <h2>1. 목적</h2>
            <p>
                본 약관은 MarketFlow(이하 "서비스")가 제공하는 시장 분석 정보 서비스의 이용 조건과 이용자·서비스
                간의 권리·의무를 규정합니다.
            </p>

            <h2>2. 서비스의 내용</h2>
            <ul>
                <li>KR·US·Crypto 시장에 대한 AI 기반 분석 정보 및 시그널 제공</li>
                <li>커뮤니티(공개 열람 + 회원 참여) 운영</li>
                <li>유료 구독(Pro / Ultra Pro)을 통한 전체 기능 이용</li>
            </ul>

            <h2>3. 구독 및 결제</h2>
            <ul>
                <li>구독은 계좌이체 후 관리자 승인 방식으로 활성화되며, 승인 시점부터 이용 기간(30일)이 시작됩니다.</li>
                <li>Ultra Pro 는 1회 결제로 무기한 이용하는 플랜입니다.</li>
                <li>구독 만료 후에는 재구독 신청을 통해 동일한 방식으로 이용을 재개할 수 있습니다.</li>
            </ul>

            <h2>4. 환불</h2>
            <p>
                결제 후 7일 이내에 서비스를 실질적으로 이용하지 않은 경우 전액 환불을 요청할 수 있습니다. 이용
                개시 이후에는 잔여 기간에 대해 일할 계산 환불을 원칙으로 하며, 자세한 사항은 문의처를 통해
                협의합니다.
            </p>

            <h2>5. 투자 정보에 대한 면책</h2>
            <p>
                서비스가 제공하는 모든 정보(AI 분석, 시그널, 커뮤니티 게시물 포함)는 투자 판단을 위한{' '}
                <strong>참고 자료</strong>이며, 「자본시장과 금융투자업에 관한 법률」상의 투자 자문 또는 투자 권유가
                아닙니다. 투자의 최종 결정과 그 결과에 대한 책임은 전적으로 이용자 본인에게 있으며, 서비스는
                이용자의 투자 손실에 대해 책임을 지지 않습니다.
            </p>

            <h2>6. 이용자의 의무</h2>
            <ul>
                <li>타인의 계정을 도용하거나 서비스 콘텐츠를 무단으로 복제·재배포하지 않습니다.</li>
                <li>커뮤니티에 법령 위반, 허위 사실, 스팸성 게시물을 작성하지 않습니다.</li>
            </ul>

            <h2>7. 서비스의 변경 및 중단</h2>
            <p>
                서비스는 운영상·기술상 필요에 따라 제공 내용을 변경할 수 있으며, 중대한 변경은 사전에 공지합니다.
            </p>

            <h2>8. 문의처</h2>
            <p>
                약관 관련 문의: <a href="mailto:point10890@gmail.com">point10890@gmail.com</a>
            </p>
        </PolicyLayout>
    );
}

export function AboutPage() {
    return (
        <PolicyLayout label="ABOUT" title="서비스 소개" path="/about"
                      description="MarketFlow 는 시장 데이터를 반복 관찰하고 데이터 품질을 확인한 뒤 의미 있는 변화만 기록하는 AI 시장 관찰 서비스입니다. 핵심 에이전트 Claw 의 작동 방식과 운영 원칙을 소개합니다.">
            <p>
                <strong>MarketFlow</strong> 는 시장 데이터를 반복 관찰하고, 원천 시각과 데이터 품질을 확인한 뒤
                의미 있는 변화만 기록하는 시장 관찰 서비스입니다. 핵심 에이전트 <strong>Claw</strong> 와 함께
                한국·미국·암호화폐 분석 도구를 한 대시보드에서 제공합니다.
            </p>

            <h2>Claw는 어떻게 작동하나요</h2>
            <ul>
                <li><strong>관찰</strong> — 정해진 주기로 시장 원천과 후보군을 수집합니다.</li>
                <li><strong>품질 확인</strong> — 결측·지연·중복 여부와 원천 시각을 먼저 확인합니다.</li>
                <li><strong>변화 검출</strong> — 조건을 통과한 변화만 관찰 이벤트로 기록합니다.</li>
                <li><strong>위험 우선</strong> — 품질이 부족하거나 위험 신호가 있으면 긍정 알림을 HOLD 합니다.</li>
                <li><strong>사후 검증</strong> — 검출 이후 결과를 D+1·D+5 기준으로 기록해 다음 판단의 근거로 남깁니다.</li>
            </ul>

            <h2>대시보드에서 확인할 수 있는 것</h2>
            <p>
                Claw 운영 상태, 데이터 신선도와 품질, 검출 이벤트와 근거, 위험·무효화 조건, 시장별 분석 및
                브리핑을 확인할 수 있습니다. AI Brain은 여러 분석 결과를 교차 검토하는 선택형 확장 기능입니다.
                등급과 점수는 매수·매도 지시가 아니라 관찰 우선순위를 정리하기 위한 지표입니다.
            </p>

            <h2>운영 원칙</h2>
            <ul>
                <li>실제 주문을 실행하지 않는 관찰 전용 서비스입니다.</li>
                <li>데이터가 불충분하면 추정값으로 채우지 않고 HOLD 또는 확인 불가로 표시합니다.</li>
                <li>모든 신호를 가설로 다루며, 원천과 시각을 함께 남기는 것을 우선합니다.</li>
                <li>특정 수익률이나 손실 회피를 보장하지 않습니다.</li>
            </ul>

            <h2>투자 유의사항</h2>
            <p>
                본 서비스가 제공하는 모든 정보는 투자 참고 자료이며 투자 권유·자문이 아닙니다. 특정 종목의 매수·매도를
                권유하지 않으며, 과거 성과는 미래 수익을 보장하지 않습니다. 투자의 최종 판단과 책임은 투자자 본인에게
                있습니다.
            </p>

            <h2>문의</h2>
            <p>
                제휴·오류 제보·기타 문의: <a href="mailto:point10890@gmail.com">point10890@gmail.com</a>
            </p>

            <div className="mt-8 flex flex-wrap gap-2">
                <Link to="/community"
                      className="rounded-xl border border-white/10 px-5 py-3 text-[13px] font-bold text-gray-300 transition-colors hover:text-white">
                    커뮤니티 둘러보기
                </Link>
                <Link to="/pricing"
                      className="rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 px-5 py-3 text-[13px] font-black text-black transition-transform hover:scale-[1.02]">
                    요금제 보기
                </Link>
            </div>
        </PolicyLayout>
    );
}
