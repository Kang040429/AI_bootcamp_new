import streamlit as st

# 1. 페이지 설정
st.set_page_config(
    page_title="개인설정 - AIR AI", 
    page_icon="⚙️", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------------------------------------------------
# ✂️ 상단 여백 제거 + 하단 탭 버튼 규격 통일 CSS (ai_chat.py와 100% 동일)
# -------------------------------------------------------------------
st.markdown("""
    <style>
    /* 1. 기본 배경 및 상/하단 여백 세팅 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 120px !important; /* 하단 고정 버튼 바 높이만큼 여백 확보 */
    }
    
    /* 2. Streamlit 헤더 공간 및 사이드바 완전 숨김 */
    header[data-testid="stHeader"] { height: 0px !important; background: transparent !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }

    /* 3. st.bottom 하단 거대 여백 완전 제거 */
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

    /* 4. 💡 모바일/PC 강제 가로 3분할 및 촘촘한 버튼 간격 제어 */
    div[data-testid="stBottom"] [data-testid="stHorizontalBlock"] {
        border-top: 1px solid #262730 !important;
        padding: 8px 16px 12px 16px !important;
        background-color: #0e1117 !important;
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 6px !important; /* ai_chat.py와 동일한 6px 간격 */
        width: 100% !important;
        margin: 0 !important;
    }
    
    div[data-testid="stBottom"] [data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0 !important;
        width: 0 !important;
        min-width: 0 !important;
    }

    /* 5. 💡 하단 탭 버튼 규격 및 폰트 크기 통일 (높이 42px) */
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

# 2. 초기 세션 상태 설정
if "user_profile" not in st.session_state:
    st.session_state.user_profile = {
        "location": "경기도 시흥시",
        "user_type": "일반 성인",
        "activity": "환기 / 산책",
        "ai_style": "핵심만 3줄 요약",
        "notify_alarm": True
    }

current = st.session_state.user_profile

# 3. 맨 위쪽 헤더 구역
st.markdown("<h2 style='margin-top: 0px; margin-bottom: 2px; font-size: 24px;'>⚙️ 개인 맞춤 환경 설정</h2>", unsafe_allow_html=True)
st.caption("사용자 환경 및 건강 상태에 최적화된 AI 대기질 리포트 및 가이드를 제공합니다.")

st.divider()

# 4. [각 항목별 접이식 설정 입력 폼]
with st.form("user_settings_form"):
    # 항목 1
    with st.expander("📍 **1. 기본 위치 및 관심 지역**", expanded=False):
        new_location = st.text_input(
            "거주지 또는 자주 확인하는 지역",
            value=current["location"],
            help="예: 경기도 시흥시, 서울시 종로구, 인천 연수구"
        )

    # 항목 2
    with st.expander("👥 **2. 사용자 대상 및 건강 상태**", expanded=False):
        user_type_options = ["일반 성인", "영유아 / 어린이 보호자", "호흡기 질환자 / 노약자", "야외 운동 마니아"]
        new_user_type = st.selectbox(
            "건강 상태 유형을 선택해 주세요",
            options=user_type_options,
            index=user_type_options.index(current["user_type"]) if current["user_type"] in user_type_options else 0,
            help="선택한 유형에 따라 미세먼지 경보 기준 및 건강 수칙 가이드가 맞춤형으로 제공됩니다."
        )

    # 항목 3
    with st.expander("🏃 **3. 주요 관심 야외 활동**", expanded=False):
        activity_options = ["환기 / 산책", "러닝 / 자전거", "아이와 야외 활동", "출퇴근 / 통학"]
        new_activity = st.selectbox(
            "가장 자주 확인하는 활동 목적",
            options=activity_options,
            index=activity_options.index(current["activity"]) if current["activity"] in activity_options else 0
        )

    # 항목 4
    with st.expander("🤖 **4. AI 답변 가이드 스타일**", expanded=False):
        style_options = ["핵심만 3줄 요약", "친절하고 세심한 설명", "전문 수치/데이터 중심 분석"]
        new_ai_style = st.radio(
            "Gemini AI 가이드의 응답 방식을 선택하세요",
            options=style_options,
            index=style_options.index(current["ai_style"]) if current["ai_style"] in style_options else 0
        )

    # 항목 5
    with st.expander("🔔 **5. 위험 대기질 알림 수신 설정**", expanded=False):
        new_notify = st.checkbox(
            "미세먼지 / 초미세먼지 '나쁨' 이상 시 맞춤 알림 받기",
            value=current["notify_alarm"]
        )

    st.write("")
    # 전체 저장 버튼
    submit_btn = st.form_submit_button("💾 설정 내용 통합 저장하기", type="primary", use_container_width=True)

    if submit_btn:
        st.session_state.user_profile = {
            "location": new_location,
            "user_type": new_user_type,
            "activity": new_activity,
            "ai_style": new_ai_style,
            "notify_alarm": new_notify
        }
        st.success("🎉 개인 설정이 성공적으로 저장되었습니다!")
        st.rerun()

# 5. 💡 화면 최하단 완전 고정 구역 (규격 동일 적용)
with st.bottom:
    b_col1, b_col2, b_col3 = st.columns(3)

    with b_col1:
        if st.button("공기질 AI", use_container_width=True):
            st.switch_page("pages/ai_chat.py")

    with b_col2:
        if st.button("홈", use_container_width=True):
            st.switch_page("app.py")

    with b_col3:
        if st.button("사용자 설정", type="primary", use_container_width=True):
            st.rerun()