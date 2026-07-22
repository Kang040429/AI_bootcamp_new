# pages/ai_chat.py
import streamlit as st
import main_agent as env_api

st.set_page_config(
    page_title="숨쉬는 일상 - AI 에이전트 상담소",
    page_icon="💬",
    layout="wide"
)

# CSS 스타일 적용
try:
    with open("style.css", "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass

# 마스터 데이터 및 Secrets 키 로드
locations_df, h2b_map, valid_bjd_map = env_api.locations_upload()
LOCATION_KEY = st.secrets.get("AIR_PORTAL_LOCATION_KEY", "")
AIR_KEY = st.secrets.get("AIR_PORTAL_KEY", "")

# 🏠 상단 이동 버튼
if st.button("🏠 메인 대시보드로 돌아가기"):
    st.switch_page("app.py")

st.markdown("---")

# 사용자 정보 세션 처리
user_name = st.session_state.get("user_name", "성주")
user_disease = st.session_state.get("user_disease", "비염")

if "current_region" not in st.session_state:
    st.session_state["current_region"] = ["서울특별시", "강남구", "역삼동"]
if "current_region_str" not in st.session_state:
    st.session_state["current_region_str"] = "서울특별시 강남구 역삼동"

# ---------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------
with st.sidebar:
    st.header("👤 사용자 정보")
    st.write(f"**이름**: {user_name}")
    st.write(f"**관심 질환**: {user_disease}")
    st.write(f"**현재 설정 위치**: {st.session_state['current_region_str']}")
    st.markdown("---")
    if st.button("🏠 대시보드로 이동", key="sidebar_home_btn", use_container_width=True):
        st.switch_page("app.py")

# ---------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------
st.title("💬 AI 대기질 맞춤 상담소")
st.caption(f"반갑습니다, **{user_name}**님! ({user_disease} 맞춤 대기케어 가이드 서비스)")

# ---------------------------------------------------------------------
# 대화창 및 main_agent 함수 직접 연결
# ---------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "assistant", 
            "content": f"안녕하세요 {user_name}님! 궁금하신 지역이나 대기질 상태를 편하게 물어보세요."
        }
    ]

# 이전 대화 출력
for msg in st.session_state["messages"]:
    st.chat_message(msg["role"]).write(msg["content"])

# 사용자 입력
if prompt := st.chat_input("궁금한 지역이나 질문을 입력하세요"):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)

    # 🖥️ [CMD 로그] 질문 수신
    print("\n" + "=" * 80)
    print(f"💬 [사용자 질문 수신]: {prompt}")
    print("=" * 80)

    with st.spinner("🤖 main_agent 파이프라인 가동 중..."):
        # 1. main_agent: Gemini 지명 및 질문 의도 추론
        gemini_res = env_api.process_user_request(prompt)
        is_query = gemini_res.get("is_location_query", False)
        location_sets = gemini_res.get("location_sets", [])

        print(f" 1️⃣ [1차 Gemini 추론] 환경질문: {is_query} | 추출 지명: {location_sets}")

        if is_query and location_sets:
            # 2. main_agent: API 데이터 조회 (단일/다중 일괄)
            air_results = env_api.fetch_all_air_candidates(
                location_sets=location_sets,
                location_key=LOCATION_KEY,
                air_key=AIR_KEY,
                h2b_map=h2b_map,
                valid_bjd_map=valid_bjd_map
            )
            print(f" 2️⃣ [API 데이터 수집] 총 {len(air_results)}건 완료")

            # 3. main_agent: Gemini 최종 답변 생성
            response = env_api.generate_final_response(prompt, air_results)
            print(" 3️⃣ [2차 Gemini] 최종 응답 생성 완료\n" + "-" * 50 + f"\n{response}\n" + "-" * 50)
            
        else:
            response = "질문에서 유효한 지역을 찾지 못했거나 환경 관련 질문이 아닙니다. 지역명(예: '시흥', '오산')을 포함하여 다시 질문해주세요!"
            print(" ⚠️ [예외] 유효한 지명 미감지")

    # 화면에 결과 출력 및 저장
    st.session_state["messages"].append({"role": "assistant", "content": response})
    st.rerun()
