import streamlit as st
import main_agent as agent  # main_agent.py 모듈 임포트

# 1. 페이지 설정
st.set_page_config(
    page_title="공기질 AI - AIR AI", 
    page_icon="💬", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------------------------------------------------
# CSS 스타일링 (모바일 프레임 + 하단바 규격 통일)
# -------------------------------------------------------------------
st.markdown("""
    <style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 120px !important;
    }
    
    header[data-testid="stHeader"] { height: 0px !important; background: transparent !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }

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

# -------------------------------------------------------------------
# 🔗 user.py 세션 프로필 로드
# -------------------------------------------------------------------
if "user_profile" not in st.session_state:
    st.session_state.user_profile = {
        "location": "경기도 시흥시",
        "user_type": "일반 성인",
        "activity": "환기 / 산책",
        "ai_style": "핵심만 3줄 요약",
        "notify_alarm": True
    }

profile = st.session_state.user_profile

# 대화 기록 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# -------------------------------------------------------------------
# 화면 상단 헤더
# -------------------------------------------------------------------
st.markdown("<h3 style='margin-top:0px; margin-bottom:2px;'>💬 공기질 맞춤 AI 상담소</h3>", unsafe_allow_html=True)
st.caption(f"📍 **{profile['location']}** | 👤 **{profile['user_type']}** | 🏃 **{profile['activity']}** 기준 맞춤 상담")

st.divider()

# 기존 대화 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 채팅 입력 및 처리
if prompt := st.chat_input(f"예: 오늘 {profile['location']}에서 {profile['activity']} 해도 될까요?"):
    # 1. 사용자 메시지 표시 및 저장
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. main_agent 파이프라인을 통한 대기질 수집 및 AI 답변 생성
    with st.chat_message("assistant"):
        with st.spinner("📡 실시간 공기질 측정 데이터 확인 중..."):
            try:
                # secrets에서 API 키 로드
                loc_key = st.secrets.get("AIR_PORTAL_LOCATION_KEY", "")
                air_key = st.secrets.get("AIR_PORTAL_KEY", "")

                # 법정동 마스터 매핑 데이터 로드
                _, h2b_map, valid_bjd_map = agent.locations_upload()

                # [STEP 1] 1차 Gemini 추론 (지역 및 의도 파악)
                gemini_res = agent.process_user_request(prompt)
                is_query = gemini_res.get("is_location_query", False)
                location_sets = gemini_res.get("location_sets", [])

                # 질문에 지역 정보가 모호한 경우 프로필 기본 위치 추가 후 재시도
                if not location_sets and profile.get("location"):
                    fallback_prompt = f"{prompt} ({profile['location']})"
                    gemini_res = agent.process_user_request(fallback_prompt)
                    is_query = gemini_res.get("is_location_query", False)
                    location_sets = gemini_res.get("location_sets", [])

                if not is_query or not location_sets:
                    response_text = "대기질, 미세먼지, 오존 등 공기 상태나 환기/외출 관련 질문을 입력해 주세요! (예: 오늘 시흥시 미세먼지 어때?)"
                else:
                    # [STEP 2] 실시간 공공데이터 수집
                    air_results = agent.fetch_all_air_candidates(
                        location_sets=location_sets,
                        location_key=loc_key,
                        air_key=air_key,
                        h2b_map=h2b_map,
                        valid_bjd_map=valid_bjd_map
                    )

                    # 사용자 프로필 정보를 가이드 프롬프트로 구성
                    user_context_prompt = f"""
                    [사용자 프로필 컨텍스트]
                    - 사용자 질문: "{prompt}"
                    - 대상/상태: {profile.get('user_type', '일반 성인')}
                    - 관심 야외활동: {profile.get('activity', '환기 / 산책')}
                    - 선호 스타일: {profile.get('ai_style', '핵심만 3줄 요약')}
                    """

                    # [STEP 3] 2차 Gemini 최종 답변 생성
                    response_text = agent.generate_final_response(
                        user_input=user_context_prompt,
                        air_results=air_results
                    )

                st.markdown(response_text)

            except Exception as e:
                response_text = f"⚠️ 데이터 분석 중 오류가 발생했습니다: {str(e)}"
                st.error(response_text)

    # 3. AI 메시지 저장
    st.session_state.messages.append({"role": "assistant", "content": response_text})

# -------------------------------------------------------------------
# 화면 최하단 완전 고정 구역 (st.bottom)
# -------------------------------------------------------------------
with st.bottom:
    b_col1, b_col2, b_col3 = st.columns(3)

    with b_col1:
        if st.button("공기질 AI", type="primary", use_container_width=True):
            st.rerun()

    with b_col2:
        if st.button("홈", use_container_width=True):
            st.switch_page("app.py")

    with b_col3:
        if st.button("사용자 설정", use_container_width=True):
            st.switch_page("pages/user.py")
