#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
US Market - 전체 데이터 업데이트 스크립트 (Parallel Pipeline v2.0)
의존성 기반 그룹 병렬 실행으로 ~20분 → ~8분 단축

사용법:
    python3 update_all.py               # 전체 업데이트 (그룹 병렬)
    python3 update_all.py --quick       # 빠른 업데이트 (AI 제외)
    python3 update_all.py --ai-only     # AI 분석만 업데이트
    python3 update_all.py --force       # 강제 업데이트 (최신 여부 무시)
    python3 update_all.py --sequential  # 순차 실행 (디버깅용)
"""

import os
import sys
import subprocess
import time
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

# 스크립트 디렉토리 기준 절대경로
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# pandas는 선택적 (데이터 신선도 체크에만 사용)
try:
    import pandas as pd
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

# 휴일/거래일 유틸리티 (holidays.py에서 import, 없으면 폴백)
try:
    sys.path.insert(0, SCRIPT_DIR)
    from holidays import US_MARKET_HOLIDAYS, get_last_trading_day
except ImportError:
    US_MARKET_HOLIDAYS = []
    def get_last_trading_day(reference_date=None):
        """폴백: 단순 주말 체크만"""
        if reference_date is None:
            reference_date = datetime.now()
        if reference_date.hour < 7:
            reference_date = reference_date - timedelta(days=1)
        check_date = reference_date.date()
        while check_date.weekday() >= 5:
            check_date -= timedelta(days=1)
        return check_date.strftime("%Y-%m-%d")


def get_data_last_date():
    """
    저장된 가격 데이터의 마지막 날짜 확인

    Returns:
        str: 마지막 데이터 날짜 (YYYY-MM-DD) 또는 None
    """
    csv_path = os.path.join(SCRIPT_DIR, 'data', 'us_daily_prices.csv')

    if not os.path.exists(csv_path):
        return None

    if not _HAS_PANDAS:
        return None

    try:
        df = pd.read_csv(csv_path, usecols=['Date'])
        last_date = df['Date'].max()
        return last_date
    except Exception as e:
        print(f"  ⚠️  데이터 날짜 확인 실패: {e}")
        return None


def is_data_fresh():
    """
    데이터가 최신인지 확인

    Returns:
        tuple: (is_fresh: bool, last_trading_day: str, data_last_date: str)
    """
    last_trading_day = get_last_trading_day()
    data_last_date = get_data_last_date()

    if data_last_date is None:
        return False, last_trading_day, None

    is_fresh = data_last_date >= last_trading_day
    return is_fresh, last_trading_day, data_last_date


os.chdir(SCRIPT_DIR)

# ANSI 색상 코드
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(message):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.END}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.END}\n")

def print_step(step_num, total, message):
    print(f"{Colors.CYAN}[{step_num}/{total}]{Colors.END} {Colors.BOLD}{message}{Colors.END}")

def print_success(message):
    print(f"  {Colors.GREEN}✅ {message}{Colors.END}")

def print_error(message):
    print(f"  {Colors.RED}❌ {message}{Colors.END}")

def print_skip(message):
    print(f"  {Colors.YELLOW}⏭️  {message}{Colors.END}")

def run_script(script_name, description, timeout=600):
    """
    Python 스크립트 실행

    Args:
        script_name: 실행할 스크립트 파일명
        description: 스크립트 설명
        timeout: 타임아웃 (초)

    Returns:
        bool: 성공 여부
    """
    parts = script_name.split()
    script_file = parts[0]
    script_args = parts[1:]
    script_path = os.path.join(SCRIPT_DIR, script_file)

    if not os.path.exists(script_path):
        print_skip(f"{script_file} not found (skipped)")
        return True  # 아직 복사되지 않은 스크립트는 스킵 처리 (실패 아님)

    start_time = time.time()

    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run(
            [sys.executable, script_path] + script_args,
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            print_success(f"{description} 완료 ({elapsed:.1f}초)")
            return True
        else:
            print_error(f"{description} 실패 (exit code: {result.returncode})")
            if result.stderr:
                print(f"      Error: {result.stderr[:200]}...")
            return False

    except subprocess.TimeoutExpired:
        print_error(f"{description} 타임아웃 ({timeout}초)")
        return False
    except Exception as e:
        print_error(f"{description} 에러: {str(e)}")
        return False


def run_script_worker(script_name, description, timeout=600):
    """Parallel-safe wrapper around run_script (module-level for pickling)"""
    success = run_script(script_name, description, timeout)
    return (script_name, description, success)


def run_parallel_group(scripts, group_name, max_workers=4):
    """
    Run scripts in parallel using ProcessPoolExecutor

    Args:
        scripts: List of (script_name, description, timeout) tuples
        group_name: Name of this execution group
        max_workers: Max parallel workers

    Returns:
        tuple: (success_count, failed_scripts)
    """
    success_count = 0
    failed_scripts = []

    print(f"\n  {Colors.BLUE}⚡ 병렬 실행 ({len(scripts)}개, max_workers={max_workers}){Colors.END}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for script, desc, timeout in scripts:
            future = executor.submit(run_script_worker, script, desc, timeout)
            futures[future] = (script, desc)

        for future in as_completed(futures):
            script, desc = futures[future]
            try:
                _script_name, _desc, success = future.result()
                if success:
                    success_count += 1
                else:
                    failed_scripts.append(script)
            except Exception as e:
                print_error(f"{desc} 프로세스 에러: {str(e)}")
                failed_scripts.append(script)

    return success_count, failed_scripts


def update_full_grouped():
    """전체 업데이트 파이프라인 (의존성 그룹)"""
    return [
        ("Group 0: Market Regime", [
            ("market_regime.py", "🌍 마켓 레짐 감지 (adaptive config)", 120),
        ], False),  # sequential — must run before all other analysis

        ("Group 1: Prices", [
            ("create_us_daily_prices.py", "📊 S&P 500 가격 데이터 수집", 900),
        ], False),  # sequential

        ("Group 2: Independent Analysis", [
            ("analyze_volume.py", "📈 거래량/수급 분석", 300),
            ("analyze_13f.py", "🏦 기관 보유 분석 (13F)", 600),
            ("analyze_etf_flows.py", "💰 ETF 자금 흐름", 300),
            ("options_flow.py", "📊 옵션 플로우", 300),
            ("insider_tracker.py", "🕵️  내부자 거래", 300),
            ("sec_filings.py", "📋 SEC 공시 (10-K/10-Q/8-K)", 300),
            ("earnings_analyzer.py", "📅 실적 분석", 300),
            ("earnings_transcripts.py", "📞 실적 콜 트랜스크립트", 300),
            ("sector_heatmap.py", "🗺️  섹터 히트맵", 300),
            ("sector_rotation.py", "🔄 섹터 로테이션", 300),
            ("portfolio_risk.py", "⚖️  포트폴리오 리스크", 300),
            ("risk_alert.py", "🚨 리스크 알림", 300),
            ("earnings_impact.py", "💥 어닝 임팩트", 300),
        ], True),  # parallel

        ("Group 3: Screening", [
            ("smart_money_screener_v2.py", "🎯 Smart Money 스크리닝", 600),
            ("super_performance_scanner.py", "🚀 Super Performance (VCP) 스캐닝", 300),
        ], False),  # sequential

        ("Group 4: AI & Macro", [
            ("ai_summary_generator.py", "🤖 AI 종목 분석", 900),
            ("us_news_analyzer.py --batch", "📰 Perplexity 뉴스 분석", 300),
            ("macro_analyzer.py", "🌍 매크로 AI 분석", 300),
            ("economic_calendar.py", "📅 경제 캘린더 + AI 전망", 300),
            ("us_market_briefing.py", "📋 US Market 시황 브리핑", 300),
        ], True),  # parallel

        ("Group 5: Final Reports", [
            ("final_report_generator.py", "🏆 Final Top 10 리포트 생성", 60),
            ("index_predictor.py", "🔮 지수 방향 예측", 300),
            ("smart_money_tracker.py", "📈 Smart Money 성과 추적", 300),
        ], False),  # sequential
    ]


def update_full():
    """전체 업데이트 (레거시 순차 모드 - --sequential 용)"""

    scripts = [
        # 0. 마켓 레짐 감지
        ("market_regime.py", "🌍 마켓 레짐 감지 (adaptive config)", 120),

        # 1. 가격 데이터 수집
        ("create_us_daily_prices.py", "📊 S&P 500 가격 데이터 수집", 900),

        # 2. 기술적/수급 분석
        ("analyze_volume.py", "📈 거래량/수급 분석", 300),
        ("analyze_13f.py", "🏦 기관 보유 분석 (13F)", 600),
        ("analyze_etf_flows.py", "💰 ETF 자금 흐름", 300),

        # 3. 종합 스크리닝
        ("smart_money_screener_v2.py", "🎯 Smart Money 스크리닝", 600),

        # 4. AI 분석 (시간 소요 큼)
        ("ai_summary_generator.py", "🤖 AI 종목 분석", 900),
        ("final_report_generator.py", "🏆 Final Top 10 리포트 생성", 60),

        # 5. 시황 분석
        ("us_news_analyzer.py --batch", "📰 Perplexity 뉴스 분석", 300),
        ("us_market_briefing.py", "📋 US Market 시황 브리핑", 300),

        # 6. Super Performance (VCP) Scanner
        ("super_performance_scanner.py", "🚀 Super Performance (VCP) 스캐닝", 300),

        ("macro_analyzer.py", "🌍 매크로 AI 분석", 300),
        ("economic_calendar.py", "📅 경제 캘린더 + AI 전망", 300),

        # 7. 부가 분석
        ("sector_heatmap.py", "🗺️  섹터 히트맵", 300),
        ("options_flow.py", "📊 옵션 플로우", 300),
        ("insider_tracker.py", "🕵️  내부자 거래", 300),
        ("portfolio_risk.py", "⚖️  포트폴리오 리스크", 300),
        ("sector_rotation.py", "🔄 섹터 로테이션", 300),
        ("risk_alert.py", "🚨 리스크 알림", 300),
        ("earnings_impact.py", "💥 어닝 임팩트", 300),

        # 8. 공시/실적 분석
        ("sec_filings.py", "📋 SEC 공시 (10-K/10-Q/8-K)", 300),
        ("earnings_transcripts.py", "📞 실적 콜 트랜스크립트", 300),

        # 9. 최종 리포트
        ("index_predictor.py", "🔮 지수 방향 예측", 300),
        ("smart_money_tracker.py", "📈 Smart Money 성과 추적", 300),
    ]

    return scripts


def update_quick():
    """빠른 업데이트 (AI 제외)"""

    scripts = [
        ("analyze_volume.py", "📈 거래량/수급 분석", 300),
        ("analyze_13f.py", "🏦 기관 보유 분석", 300),
        ("smart_money_screener_v2.py", "🎯 Smart Money 스크리닝", 600),
        ("sector_heatmap.py", "🗺️  섹터 히트맵", 300),
        ("options_flow.py", "📊 옵션 플로우", 300),
        ("sector_rotation.py", "🔄 섹터 로테이션", 300),
        ("risk_alert.py", "🚨 리스크 알림", 300),
        ("smart_money_tracker.py", "📈 Smart Money 성과 추적", 300),
    ]

    return scripts


def update_ai_only():
    """AI 분석만 업데이트"""

    scripts = [
        ("ai_summary_generator.py", "🤖 AI 종목 분석", 900),
        ("macro_analyzer.py", "🌍 매크로 AI 분석", 300),
        ("economic_calendar.py", "📅 경제 캘린더 + AI 전망", 300),
    ]

    return scripts


def main():
    parser = argparse.ArgumentParser(description='US Market 데이터 전체 업데이트')
    parser.add_argument('--quick', action='store_true', help='빠른 업데이트 (AI 제외)')
    parser.add_argument('--ai-only', action='store_true', help='AI 분석만 업데이트')
    parser.add_argument('--force', action='store_true', help='강제 업데이트 (최신 여부 무시)')
    parser.add_argument('--sequential', action='store_true', help='순차 실행 (디버깅용)')
    parser.add_argument('--no-telegram', action='store_true', help='텔레그램 알림 스킵')
    args = parser.parse_args()

    # 시작 시간
    start_time = datetime.now()

    print_header(f"🇺🇸 US Market 데이터 업데이트 시작")
    print(f"📅 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 작업 디렉토리: {SCRIPT_DIR}")

    # 데이터 최신 여부 확인
    is_fresh, last_trading_day, data_last_date = is_data_fresh()
    print(f"\n📊 마지막 거래일: {last_trading_day}")
    print(f"💾 저장된 데이터: {data_last_date or '없음'}")

    if is_fresh and not args.force:
        print(f"{Colors.GREEN}✅ 데이터가 이미 최신입니다! (가격 수집 스킵){Colors.END}")
        skip_price_collection = True
    else:
        if args.force:
            print(f"{Colors.YELLOW}⚡ 강제 업데이트 모드{Colors.END}")
        else:
            print(f"{Colors.YELLOW}📥 새로운 데이터가 필요합니다{Colors.END}")
        skip_price_collection = False

    # 모드 선택
    use_grouped = not args.sequential and not args.ai_only and not args.quick

    if args.ai_only:
        print(f"\n🔧 모드: AI 분석만 업데이트")
        scripts = update_ai_only()
    elif args.quick:
        print(f"\n🔧 모드: 빠른 업데이트 (AI 제외)")
        scripts = update_quick()
    elif use_grouped:
        print(f"\n🔧 모드: 전체 업데이트 (그룹 병렬)")
    else:
        print(f"\n🔧 모드: 전체 업데이트 (순차)")
        scripts = update_full()

    total_success = 0
    total_failed = []
    total_scripts = 0

    if use_grouped:
        # 그룹 병렬 실행 모드
        groups = update_full_grouped()

        # 가격 수집 스킵 처리
        if skip_price_collection:
            filtered_groups = []
            for group_name, scripts_list, is_parallel in groups:
                filtered = [s for s in scripts_list if s[0] != "create_us_daily_prices.py"]
                if filtered:
                    filtered_groups.append((group_name, filtered, is_parallel))
            groups = filtered_groups

        for group_name, scripts_list, is_parallel in groups:
            total_scripts += len(scripts_list)
            print_header(f"📦 {group_name}")

            if is_parallel and len(scripts_list) > 1:
                s_count, f_scripts = run_parallel_group(scripts_list, group_name)
                total_success += s_count
                total_failed.extend(f_scripts)
            else:
                for script, desc, timeout in scripts_list:
                    print_step("", "", desc)
                    if run_script(script, desc, timeout):
                        total_success += 1
                    else:
                        total_failed.append(script)
    else:
        # 순차 실행 모드 (레거시 / quick / ai-only)
        if skip_price_collection:
            scripts = [s for s in scripts if s[0] != "create_us_daily_prices.py"]

        total_scripts = len(scripts)

        for i, (script, desc, timeout) in enumerate(scripts, 1):
            print_step(i, total_scripts, desc)

            if run_script(script, desc, timeout):
                total_success += 1
            else:
                total_failed.append(script)

    # 결과 요약
    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    print_header("📋 업데이트 완료 요약")
    print(f"⏱️  총 소요 시간: {elapsed/60:.1f}분")
    print(f"✅ 성공: {total_success}/{total_scripts}")

    if skip_price_collection:
        print(f"{Colors.CYAN}⏭️  스킵: 가격 데이터 수집 (이미 최신){Colors.END}")

    if total_failed:
        print(f"{Colors.RED}❌ 실패: {', '.join(total_failed)}{Colors.END}")
    else:
        print(f"{Colors.GREEN}🎉 모든 스크립트 성공적으로 완료!{Colors.END}")

    print(f"\n📅 완료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌐 대시보드: http://localhost:5001")

    return 0 if not total_failed else 1


if __name__ == "__main__":
    sys.exit(main())
