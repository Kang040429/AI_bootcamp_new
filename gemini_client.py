# gemini_client.py
import os
import json
import requests
import streamlit as st

# =====================================================================
# 💡 API 키 로딩 함수 (다양한 경로 탐색)
# =====================================================================
def _get_api_key(api_key: str | None = None) -> str:
    # 1. 함수 인자로 직접 전달된 경우
    if api_key and api_key.strip():
        return api_key.strip()
    
    # 2. Streamlit secrets 확인
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

    # 3. OS 환경 변수 확인
    env_key = os.getenv("GEMINI_API_KEY", "")
    if env_key:
        return env_key

    # 4. (임시) 만약 위 방법으로도 안 들어오면 여기에 직접 키 문자열을 넣어서 테스트하세요.
    # return "AIzaSy..." 

def get_fallback_response(output_type: str = "text") -> str | dict:
    if output_type == "json":
        return {"is_location_query": False, "error": True}
    return "현재 환경 데이터를 불러오는 중에 잠시 지연이 발생했습니다."

# HTTP 세션 객체
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"Content-Type": "application/json"})

# =====================================================================
# 메인 호출 함수
# =====================================================================
def call_gemini_api(
    prompt: str, 
    api_key: str | None = None, 
    model: str = "gemini-3.1-flash-lite",
    output_type: str = "text"
) -> str | dict:
    
    key = _get_api_key(api_key)
    
    # API 키가 비어있는 경우 즉시 알림
    if not key:
        print("⚠️ [Gemini Client Error] API 키를 찾을 수 없습니다! GEMINI_API_KEY를 확인하세요.")
        return get_fallback_response(output_type)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    if output_type == "json":
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }

    try:
        response = HTTP_SESSION.post(url, json=payload, timeout=30)
        
        # HTTP 에러 발생 시 원인 출력 (디버깅용)
        if response.status_code != 200:
            print(f"❌ [Gemini API HTTP Error] Status Code: {response.status_code}")
            print(f"   - 응답 내용: {response.text}")
            return get_fallback_response(output_type)

        res_json = response.json()
        candidates = res_json.get("candidates", [])
        
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts and "text" in parts[0]:
                raw_text = parts[0]["text"].strip()
                
                if output_type == "json":
                    clean_text = raw_text.replace("```json", "").replace("```", "").strip()
                    try:
                        return json.loads(clean_text)
                    except json.JSONDecodeError:
                        print("❌ [Gemini JSON Error] JSON 파싱 실패:", clean_text)
                        return get_fallback_response(output_type)
                
                return raw_text

        return get_fallback_response(output_type)

    except Exception as e:
        print(f"❌ [Gemini Network Exception]: {e}")
        return get_fallback_response(output_type)