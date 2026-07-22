'''
# app.py
import streamlit as st
import time
import numpy as np
import pandas as pd
from pathlib import Path  # 📌 [추가] 경로 추적용 모듈

# [모듈 임포트]
import main_agent as env_api

st.set_page_config(
    page_title="숨쉬는 일상 - 관리자 대시보드",
    page_icon="😷",
    layout="wide"
)

# 📌 [핵심 해결] Python 3.14 호환을 위한 ai_chat.py 절대 경로 설정
AI_CHAT_PAGE = Path(__file__).parent /  "ai_chat.py"

try:
    with open("style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass

# 위치 마스터 데이터 로드 (캐싱)
locations_df, h2b_map, valid_bjd_map = env_api.locations_upload()

# Session State 초기화
if "current_region" not in st.session_state:
    st.session_state["current_region"] = ["서울특별시", "강남구", "역삼동"]

if "current_region_str" not in st.session_state:
    st.session_state["current_region_str"] = "서울특별시 강남구 역삼동"

if "user_name" not in st.session_state:
    st.session_state["user_name"] = "성주"

if "user_disease" not in st.session_state:
    st.session_state["user_disease"] = "비염"

# ---------------------------------------------------------------------
# 헤더 & 상단 이동 버튼
# ---------------------------------------------------------------------
head_col1, head_col2 = st.columns([3, 1])

with head_col1:
    st.markdown('<span style="font-size: 24px; font-weight: bold; color: #4CAF50;">🍀 숨쉬는 일상</span>', unsafe_allow_html=True)
    st.write("실시간 공기 질 상태와 AI 에이전트 맞춤 케어 리포트를 확인하세요.")

with head_col2:
    if st.button("💬 AI 상담소 이동", key="head_chat_btn", use_container_width=True):
        st.switch_page(AI_CHAT_PAGE)

st.markdown("---")

# ---------------------------------------------------------------------
# 1. 사이드바 설정
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("👤 사용자 정보 설정")
    st.session_state["user_name"] = st.text_input("사용자 이름", value=st.session_state["user_name"])
    st.session_state["user_disease"] = st.selectbox(
        "알레르기/질환군", 
        ["비염", "천식", "아토피", "없음"],
        index=["비염", "천식", "아토피", "없음"].index(st.session_state["user_disease"])
    )
    
    st.markdown("---") 
    st.header("⚙️ 대시보드 설정")
    st.info(f"📍 현재 측정 지역:\n**{st.session_state['current_region_str']}**")
    
    # 사이드바 이동 버튼
    if st.button("💬 AI 챗봇 상담소 이동", key="sidebar_chat_btn", use_container_width=True):
        st.switch_page(AI_CHAT_PAGE)
    
    st.markdown("---")
    auto_refresh = st.checkbox("센서 데이터 자동 업데이트 (5초)", value=False)
    if st.button("데이터 수동 업데이트", use_container_width=True):
        st.rerun()

# ---------------------------------------------------------------------
# 2. 실시간 대기질 데이터 수집
# ---------------------------------------------------------------------
air_data = env_api.fetch_air_quality_by_location(
    location_set=st.session_state["current_region"],
    location_key=st.secrets.get("AIR_PORTAL_LOCATION_KEY", ""),
    air_key=st.secrets.get("AIR_PORTAL_KEY", ""),
    h2b_map=h2b_map,
    valid_bjd_map=valid_bjd_map
)

# 데이터 바인딩
pm25_status = air_data.get('status', '보통')
pm10_val = air_data.get('pm10', '-')
pm25_val = air_data.get('pm25', '-')
o3_val = air_data.get('o3', 0.030)
o3_status = air_data.get('status_o3', '보통') if 'status_o3' in air_data else '보통'
station_name = air_data.get('station', '측정소')
traffic_status = air_data.get('traffic', '보통')

# ---------------------------------------------------------------------
# 3. 종합 위험도 배너
# ---------------------------------------------------------------------
st.subheader(f"📍 {st.session_state['current_region_str']} 대기 상태 ({st.session_state['user_name']}님 기준)")

if pm25_status in ['매우 나쁨', '나쁨'] or o3_status in ['매우 나쁨', '나쁨']:
    st.error(f"🚨 **[경고]** 현재 실외 공기질이 좋지 않습니다! ({st.session_state['user_disease']} 질환 주의 필요)")
elif pm25_status == '보통':
    st.warning("🟠 **[주의]** 대기 상태가 보통이나, 민감군(호흡기/면역 질환)은 장시간 야외 활동 시 주의하세요.")
else:
    st.success("🟢 **[쾌적]** 야외 활동을 즐기기 아주 좋은 공기 상태입니다.")

# ---------------------------------------------------------------------
# 4. 핵심 지표 Metric 카드
# ---------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(label="미세먼지 (PM10)", value=f"{pm10_val} ㎍/㎥", delta=air_data.get('status_pm10', '보통'), delta_color="inverse")

with col2:
    st.metric(label="초미세먼지 (PM2.5)", value=f"{pm25_val} ㎍/㎥", delta=pm25_status, delta_color="inverse")

with col3:
    o3_str = f"{o3_val:.3f} ppm" if isinstance(o3_val, float) else f"{o3_val} ppm"
    st.metric(label="오존 농도 (O3)", value=o3_str, delta=o3_status, delta_color="inverse")

with col4:
    st.metric(label="주변 도로 소통", value=traffic_status, delta="매연 주의" if traffic_status in ['원활하지 않음', '정체'] else "정상", delta_color="inverse")

if o3_status in ['나쁨', '매우 나쁨']:
    st.info("💡 **오존 주의 안내:** 오존은 가스형 오염물질로 **KF94 마스크로 차단되지 않습니다.** 햇빛이 강한 14~17시 사이 야외 운동을 자제하세요.")

st.markdown("---") 

# ---------------------------------------------------------------------
# 5. 리포트 및 질환별 팁
# ---------------------------------------------------------------------
st.subheader("🤖 AI 에이전트 분석 리포트 & 행동 지침")

tab1, tab2, tab3 = st.tabs(["📋 종합 행동 지침", "🩺 질환별 맞춤 팁", "📊 24시간 추이 차트"])

with tab1:
    st.success(f"🤖 **{st.session_state['user_name']}님({st.session_state['user_disease']} 맞춤)**을 위한 AI 에이전트의 오늘의 행동 가이드")
    st.markdown(f"""
    1. **미세먼지 현황**: **{st.session_state['current_region_str']}** (측정소: {station_name}) 주변 초미세먼지가 **{pm25_val} ㎍/㎥ ({pm25_status})** 상태입니다.
    2. **교통 상황 연계**: 현재 도로 소통이 **{traffic_status}** 상태로, 차도 주변 산책 시 배기가스 노출 위험이 있습니다.
    3. **외출 권고사항**: 외출 시 반드시 마스크를 지참하시고, 실내 착석 시 창문 환기 시간을 조정해 주세요.
    """)

with tab2:
    st.write("💡 **질환군별 맞춤 케어 팁**을 확인하세요.")
    d_tab1, d_tab2, d_tab3 = st.tabs(["🤧 비염", "🫁 천식", "🩺 아토피"])
    
    with d_tab1:
        st.markdown("- **외출 전/후**: 외출 후 식염수로 코 세척을 실시하여 알레르기 유발 물질을 씻어내세요.\n- **환기 수칙**: 초미세먼지 '나쁨' 이상 시 직접 환기 대신 공기청정기를 가동하세요.")
    with d_tab2:
        st.markdown("- **응급 대비**: 기관지 확장제(흡입기)를 항시 지참하세요.\n- **운동 수칙**: 야외 유산소 운동은 실내 운동으로 대체하는 것을 권장합니다.")
    with d_tab3:
        st.markdown("- **보습 케어**: 외출 후 미온수로 샤워 후 3분 이내 보습제를 충분히 발라주세요.\n- **의류 착용**: 피부 자극을 줄이기 위해 순면 소재 옷을 착용하세요.")

with tab3:
    st.write(f"📈 최근 24시간 동안의 초미세먼지(PM2.5) 추이 ({st.session_state['current_region_str']})")
    base_val = pm25_val if isinstance(pm25_val, int) else 25
    chart_data = pd.DataFrame(
        np.random.randint(max(5, base_val - 15), base_val + 15, size=24), 
        columns=["PM2.5 (㎍/㎥)"],
        index=pd.date_range(start=pd.Timestamp.now().floor('h'), periods=24, freq='h')
    )
    st.line_chart(chart_data)

# ---------------------------------------------------------------------
# 6. 하단 CTA 영역
# ---------------------------------------------------------------------
st.markdown("---")
st.subheader("💬 AI 에이전트와 실시간 대화가 필요하신가요?")
st.write("궁금한 지역이나 실시간 호흡기 건강 궁금증을 AI 상담소에서 물어보세요.")

if st.button("💬 AI 대기질 맞춤 상담소로 이동하기", key="bottom_chat_btn", use_container_width=True):
    st.switch_page(AI_CHAT_PAGE)

if auto_refresh:
    time.sleep(5)
    st.rerun()

st.markdown("---")
st.write("© 2026 숨쉬는 일상 Team.")
'''

# app.py
import streamlit as st

# [모듈 임포트] main_agent 연동
import main_agent as env_api

st.set_page_config(
    page_title="숨쉬는 일상 - 메인 대시보드",
    page_icon="🌬️",
    initial_sidebar_state="collapsed",
    layout="centered"
)

# 📌 모바일 전용 프레임 고정 & st.columns 가로 강제 CSS
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
    }

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0E1117 !important;
    }
    
    /* 스마트폰 메인 폭 고정 */
    [data-testid="block-container"] {
        width: 100% !important;
        max-width: 380px !important;
        padding: 0.8rem 0.5rem !important;
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

    /* 3. 모바일 강제 가로 Flex 그리드 (미세먼지 상자 전용) */
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

    /* 🚨 5. Streamlit st.columns 모바일 강제 가로 고정 CSS */
    [data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 4px !important;
        width: 100% !important;
    }
    [data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0 !important;
        width: 0 !important;
        min-width: 0 !important;
    }
    [data-testid="stHorizontalBlock"] button {
        padding: 6px 0px !important;
        font-size: 11px !important;
        white-space: nowrap !important;
    }
    </style>
""", unsafe_allow_html=True)

# Session State 초기화
if "current_region" not in st.session_state:
    st.session_state["current_region"] = ["서울특별시", "강남구", "역삼동"]
if "current_region_str" not in st.session_state:
    st.session_state["current_region_str"] = "서울특별시 강남구 역삼동"

user_name = st.session_state.get("user_name", "성주")
user_disease = st.session_state.get("user_disease", "비염")

# 위치 마스터 데이터 로드
locations_df, h2b_map, valid_bjd_map = env_api.locations_upload()

# 실시간 대기질 데이터 수집
air_data = env_api.fetch_air_quality_by_location(
    location_set=st.session_state["current_region"],
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
# 1. 안내문구 구역
# ---------------------------------------------------------------------
st.markdown(f"""
<div class="notice-card">
    <div class="notice-title">🌬️ 숨쉬는 일상 (Breathable Life)</div>
    <div class="notice-sub">
        반갑습니다 <b>{user_name}</b>님! 현재 대기 상태는 <b>{pm25_status}</b>입니다. ({user_disease} 맞춤)
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 2. 지역 표시
# ---------------------------------------------------------------------
st.markdown(f'<div class="region-header">📍 {st.session_state["current_region_str"]} <span style="font-size:0.68rem; color:#94A3B8; font-weight:normal;">({station_name})</span></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 3. 미세먼지 / 초미세먼지 / 오존
# ---------------------------------------------------------------------
st.markdown(f"""
<div class="mobile-flex-row">
    <div class="mobile-card">
        <div class="metric-label">미세(PM10)</div>
        <div class="metric-value">{pm10_val}<span style="font-size:0.6rem;">㎍</span></div>
        <div class="metric-status">{pm25_status}</div>
    </div>
    <div class="mobile-card">
        <div class="metric-label">초미세(PM2.5)</div>
        <div class="metric-value">{pm25_val}<span style="font-size:0.6rem;">㎍</span></div>
        <div class="metric-status">{pm25_status}</div>
    </div>
    <div class="mobile-card">
        <div class="metric-label">오존(O₃)</div>
        <div class="metric-value">{o3_val}<span style="font-size:0.55rem;">ppm</span></div>
        <div class="metric-status">좋음</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 4. 그래프 구역
# ---------------------------------------------------------------------
st.markdown('<div class="graph-card">', unsafe_allow_html=True)
st.markdown('<div class="graph-title">📈 실시간 대기오염 추이</div>', unsafe_allow_html=True)

if hasattr(env_api, 'get_air_chart'):
    fig = env_api.get_air_chart(st.session_state["current_region"])
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
# 5. 💡 하단 탭 버튼 구역 (Streamlit 순수 버튼 + CSS 가로 강제)
# ---------------------------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🤖 AI상담", type="primary", use_container_width=True):
        st.switch_page("pages/ai_chat.py")

with col2:
    if st.button("🏠 홈", use_container_width=True):
        st.rerun()

with col3:
    if st.button("⚙️ 설정", use_container_width=True):
        st.toast("사이드바에서 사용자 설정을 변경하세요!")