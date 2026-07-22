import streamlit as st

# [모듈 임포트] main_agent 연동
import main_agent as env_api

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="숨쉬는 일상 - 메인 대시보드",
    page_icon="🌬️",
    initial_sidebar_state="collapsed",
    layout="centered"
)

# -------------------------------------------------------------------
# ✂️ CSS 스타일링 (모바일 프레임 + 하단바 규격 통일)
# -------------------------------------------------------------------
st.markdown("""
    <style>
    /* 0. 사이드바 및 상단 헤더 완벽 제거 */
    [data-testid="stSidebar"], 
    [data-testid="stSidebarNav"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 0px !important;
    }

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0E1117 !important;
    }
    
    /* 스마트폰 메인 폭 고정 & 하단바 공간(120px) 확보 */
    [data-testid="block-container"] {
        width: 100% !important;
        max-width: 380px !important;
        padding-top: 0.8rem !important;
        padding-bottom: 120px !important;
        margin: 0 auto !important;
    }

    /* 1. 최상단 안내문구 */
    .notice-card {
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 12px;
        padding: 0.6rem 0.7rem !important;
        margin-bottom: 0.6rem !important;
        text-align: center;
    }
    .notice-title {
        font-size: 1.0rem !important;
        font-weight: 800 !important;
        color: #F8FAFC !important;
        margin-bottom: 0.1rem !important;
    }
    .notice-sub {
        font-size: 0.78rem !important;
        color: #CBD5E1 !important;
        margin: 0;
    }

    /* 2. 지역 헤더 */
    .region-header {
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        color: #F8FAFC !important;
        margin-bottom: 0.4rem !important;
    }

    /* 3. 모바일 강제 가로 Flex 그리드 */
    .mobile-flex-row {
        display: flex !important;
        flex-direction: row !important;
        justify-content: space-between !important;
        gap: 6px !important;
        width: 100% !important;
        margin-bottom: 0.6rem !important;
    }
    
    .mobile-card {
        flex: 1 1 0 !important;
        width: 0 !important;
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 10px;
        padding: 0.4rem 0.1rem !important;
        text-align: center;
        min-width: 0 !important;
    }
    .metric-label {
        font-size: 0.68rem !important;
        color: #94A3B8;
        font-weight: 600;
        white-space: nowrap;
    }
    .metric-value {
        font-size: 0.95rem !important;
        font-weight: 800;
        color: #38BDF8;
        margin: 0.1rem 0 !important;
    }
    .metric-status {
        font-size: 0.68rem !important;
        font-weight: 700;
        color: #4ADE80;
    }

    /* 4. 그래프 카드 */
    .graph-card {
        background-color: #1E293B !important;
        border: 1px solid #334155 !important;
        border-radius: 12px;
        padding: 0.6rem 0.5rem !important;
        margin-bottom: 0.6rem !important;
    }
    .graph-title {
        font-size: 0.85rem !important;
        font-weight: 700 !important;
        color: #F8FAFC !important;
        margin-bottom: 0.2rem !important;
    }

    /* 5. 하단 고정바 스타일링 */
    footer { display: none !important; }
    div[data-testid="stBottom"] {
        padding: 0 !important;
        bottom: 0 !important;
        background-color: #0e1117 !important;
    }
    
    div[data-testid="stBottom"] > div {
        padding: 0px !important;
        gap: 0px !important;
    }

    div[data-testid="stBottom"] [data-testid="stHorizontalBlock"] {
        border-top: 1px solid #262730 !important;
        padding: 8px 16px 12px 16px !important;
        background-color: #0e1117 !important;
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 6px !important;
        width: 100% !important;
        margin: 0 !important;
    }

    div[data-testid="stBottom"] [data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0 !important;
        width: 0 !important;
        min-width: 0 !important;
    }

    div[data-testid="stBottom"] button, 
    div[data-testid="stBottom"] button[kind="primary"],
    div[data-testid="stBottom"] button[kind="secondary"] {
        width: 100% !important;
        height: 42px !important;
        min-height: 42px !important;
        max-height: 42px !important;
        margin: 0 !important;
        padding: 0px !important;
        font-size: 13px !important;
        font-weight: bold !important;
        white-space: nowrap !important;
        box-sizing: border-box !important;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 🔗 [핵심] user.py 세션 상태 불러오기 및 기본값 세팅
# ---------------------------------------------------------------------
if "user_profile" not in st.session_state:
    st.session_state.user_profile = {
        "location": "경기도 시흥시",
        "user_type": "일반 성인",
        "activity": "환기 / 산책",
        "ai_style": "핵심만 3줄 요약",
        "notify_alarm": True
    }

profile = st.session_state.user_profile
user_location_str = profile.get("location", "경기도 시흥시")
user_type = profile.get("user_type", "일반 성인")
user_activity = profile.get("activity", "환기 / 산책")

# 위치 문자열을 공백 기준으로 분할하여 리스트로 변환 (API 검색 전달용)
location_list = [loc.strip() for loc in user_location_str.split() if loc.strip()]

# ---------------------------------------------------------------------
# 실시간 대기질 API 조회 (user.py에서 설정된 위치 사용)
# ---------------------------------------------------------------------
locations_df, h2b_map, valid_bjd_map = env_api.locations_upload()

air_data = env_api.fetch_air_quality_by_location(
    location_set=location_list,
    location_key=st.secrets.get("AIR_PORTAL_LOCATION_KEY", ""),
    air_key=st.secrets.get("AIR_PORTAL_KEY", ""),
    h2b_map=h2b_map,
    valid_bjd_map=valid_bjd_map
)

pm25_status = air_data.get('status', '보통')
pm25_val = air_data.get('pm25', '-')
pm10_val = air_data.get('pm10', '-')
o3_val = air_data.get('o3', '-')
station_name = air_data.get('station', '측정소')

# ---------------------------------------------------------------------
# 1. 사용자 맞춤 안내문구
# ---------------------------------------------------------------------
st.markdown(f"""
<div class="notice-card">
    <div class="notice-title">🌬️ 숨쉬는 일상 (Breathable Life)</div>
    <div class="notice-sub">
        맞춤 그룹: <b>[{user_type}]</b> | 주 활동: <b>[{user_activity}]</b><br>
        현재 공기 상태는 <b>{pm25_status}</b>입니다.
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 2. 검색된 지역 표시
# ---------------------------------------------------------------------
st.markdown(f'<div class="region-header">📍 {user_location_str} <span style="font-size:0.68rem; color:#94A3B8; font-weight:normal;">({station_name} 측정소)</span></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 3. 실시간 대기질 지표 카드
# ---------------------------------------------------------------------
st.markdown(f"""
<div class="mobile-flex-row">
    <div class="mobile-card">
        <div class="metric-label">미세(PM10)</div>
        <div class="metric-value">{pm10_val}<span style="font-size:0.6rem;"> ㎍</span></div>
        <div class="metric-status">{pm25_status}</div>
    </div>
    <div class="mobile-card">
        <div class="metric-label">초미세(PM2.5)</div>
        <div class="metric-value">{pm25_val}<span style="font-size:0.6rem;"> ㎍</span></div>
        <div class="metric-status">{pm25_status}</div>
    </div>
    <div class="mobile-card">
        <div class="metric-label">오존(O₃)</div>
        <div class="metric-value">{o3_val}<span style="font-size:0.55rem;"> ppm</span></div>
        <div class="metric-status">좋음</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 4. 차트 영역
# ---------------------------------------------------------------------
st.markdown('<div class="graph-card">', unsafe_allow_html=True)
st.markdown('<div class="graph-title">📈 실시간 대기오염 추이</div>', unsafe_allow_html=True)

if hasattr(env_api, 'get_air_chart'):
    fig = env_api.get_air_chart(location_list)
    st.plotly_chart(fig, use_container_width=True)
else:
    import pandas as pd
    import numpy as np
    
    chart_data = pd.DataFrame(
        np.random.randn(24, 2) + [15, 25],
        columns=['초미세', '미세']
    )
    st.line_chart(chart_data, height=160)

st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 5. 화면 최하단 고정 하단바 (st.bottom)
# ---------------------------------------------------------------------
with st.bottom:
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("공기질 AI", use_container_width=True):
            st.switch_page("pages/ai_chat.py")

    with col2:
        if st.button("홈", type="primary", use_container_width=True):
            st.rerun()

    with col3:
        if st.button("사용자 설정", use_container_width=True):
            st.switch_page("pages/user.py")