# chat_manager.py
import streamlit as st
import main_agent as env_api  # main_agent.py를 env_api라는 별칭으로 임포트

def init_chat_session(user_name):
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": f"안녕하세요, {user_name}님! 궁금하신 지역(예: '역삼1동 공기 어때?', '신사동 미세먼지 알려줘')을 편하게 물어보세요! 😊"
            }
        ]

def display_chat_history():
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

def handle_user_question(user_input, user_name, user_disease, air_results):
    if not user_input:
        return

    # 1. 사용자 입력 메시지 출력 및 저장
    with st.chat_message("user"):
        st.write(user_input)
    
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 2. AI 답변 생성 및 출력
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        with st.spinner("🤖 실시간 대기질 분석 및 맞춤형 답변 생성 중..."):
            try:
                # Secrets에서 Gemini API 키 로드
                api_key = st.secrets.get("GEMINI_API_KEY", "")
                
                # air_results 리스트 처리
                air_data_param = air_results[0] if (isinstance(air_results, list) and len(air_results) > 0) else air_results

                # [수정 포인트] main_agent.py의 ask_gemini_agent 함수 호출
                if hasattr(env_api, "generate_final_response"):
                    answer = env_api.generate_final_response(user_input, air_results)
                else:
                    # 기존 ask_gemini_agent 함수 호환 호출
                    answer = env_api.ask_gemini_agent(
                        api_key=api_key,
                        user_name=user_name,
                        user_disease=user_disease,
                        user_input=user_input,
                        air_data=air_data_param
                    )
            except Exception as e:
                answer = f"죄송합니다. 답변을 생성하는 도중 오류가 발생했습니다. (오류 내용: {e})"
        
        message_placeholder.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
