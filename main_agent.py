import os
import json
import time
import urllib.parse
import requests
import re
import pandas as pd
import numpy as np
import joblib
import streamlit as st
from bs4 import BeautifulSoup
from gemini_client import call_gemini_api


# =====================================================================
# ⚙️ [Streamlit 페이지 기본 설정 & Session State 초기화]
# =====================================================================
st.set_page_config(page_title="대기질 및 호흡기 건강 안내 AI", page_icon="🌤️", layout="wide")

# 웹 세션 상태 유지
if "selected_sido" not in st.session_state:
    st.session_state["selected_sido"] = "경기도"
if "selected_sigungu" not in st.session_state:
    st.session_state["selected_sigungu"] = "시흥시"
if "selected_umd" not in st.session_state:
    st.session_state["selected_umd"] = "정왕동"
if "user_profile" not in st.session_state:
    st.session_state["user_profile"] = {
        "user_type": "일반 성인",
        "activity": "산책 / 환기",
        "ai_style": "친절하고 세심한 설명"
    }


# =====================================================================
# 🌲 [LightGBM] 저장된 예측 모델 및 Feature Importance 로드
# =====================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "lightgbm_pm10_model.pkl")

@st.cache_resource
def load_lgbm_model():
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            return model
        except Exception as e:
            st.error(f"❌ [LightGBM] 모델 로드 실패: {e}")
    return None

lgb_model = load_lgbm_model()

FEATURE_COLS = ['지역_규모', '계절_가중치', '아황산가스(SO2)', '일산화탄소(CO)', '오존(O3)', '이산화질소(NO2)']
FEATURE_IMPORTANCES = {}

if lgb_model is not None:
    try:
        raw_imps = lgb_model.feature_importances_
        imp_sum = np.sum(raw_imps)
        if imp_sum > 0:
            imp_ratios = (raw_imps / imp_sum) * 100
            FEATURE_IMPORTANCES = {col: round(ratio, 1) for col, ratio in zip(FEATURE_COLS, imp_ratios)}
    except Exception as e:
        print(f"⚠️ [LightGBM] 특성 중요도 계산 실패: {e}")


def predict_pm10_with_explanation(air_data: dict) -> dict:
    model = load_lgbm_model()
    if model is None or not isinstance(air_data, dict):
        return None

    try:
        so2 = float(air_data.get("so2", 0.003)) if air_data.get("so2") not in [None, "-"] else 0.003
        co = float(air_data.get("co", 0.5)) if air_data.get("co") not in [None, "-"] else 0.5
        o3 = float(air_data.get("o3", 0.030)) if air_data.get("o3") not in [None, "-"] else 0.030
        no2 = float(air_data.get("no2", 0.025)) if air_data.get("no2") not in [None, "-"] else 0.025
        
        month = pd.Timestamp.now().month
        season_weight = 1.0 if month in [12, 1, 2, 6, 7, 8] else 0.0
        
        sido = air_data.get("sido", "")
        region_scale = 3 if any(k in sido for k in ["서울", "경기", "인천", "부산", "대구"]) else 2

        input_df = pd.DataFrame([{
            '지역_규모': region_scale,
            '계절_가중치': season_weight,
            '아황산가스(SO2)': so2,
            '일산화탄소(CO)': co,
            '오존(O3)': o3,
            '이산화질소(NO2)': no2
        }])

        predicted_pm10 = float(round(model.predict(input_df)[0], 1))

        top_3_str = "분석 불요"
        if FEATURE_IMPORTANCES:
            top_3_factors = sorted(FEATURE_IMPORTANCES.items(), key=lambda x: x[1], reverse=True)[:3]
            top_3_str = ", ".join([f"{feat}({score}%)" for feat, score in top_3_factors])

        return {
            "ml_predicted_pm10": predicted_pm10,
            "top_contributing_factors": top_3_str,
            "model_type": "LightGBM (비선형 트리 기반 Machine Learning)"
        }
    except Exception as e:
        print(f"❌ [LightGBM 예측 수행 실패]: {e}")
        return None


# =====================================================================
# 🕸️ [크롤링 모듈] 네이버 실시간 기온, 미세먼지 수집
# =====================================================================
def get_naver_weather_with_numbers(location_name: str) -> dict:
    query = urllib.parse.quote(f"{location_name} 날씨")
    url = f"https://search.naver.com/search.naver?query={query}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        temp_val = 22.0
        temp_elem = soup.select_one(".temperature_text strong, .weather_graph .temperature_text strong")
        if temp_elem:
            temp_raw = temp_elem.get_text().replace("현재 온도", "").replace("°", "").strip()
            match = re.search(r"[-+]?\d*\.\d+|\d+", temp_raw)
            if match:
                temp_val = float(match.group())

        chart_items = soup.select(".today_chart_box .item_today, .item_today")
        metrics = {
            "미세먼지": {"status": "보통", "value": None},
            "초미세먼지": {"status": "보통", "value": None},
            "자외선": {"status": "보통", "value": None},
            "오존": {"status": "보통", "value": None}
        }

        for item in chart_items:
            title_elem = item.select_one(".title, .item_title")
            txt_elem = item.select_one(".txt, .item_txt, .value")

            if title_elem and txt_elem:
                title = title_elem.get_text().strip()
                full_text = txt_elem.get_text().strip()

                num_match = re.search(r"\d+(\.\d+)?", full_text)
                num_val = float(num_match.group()) if num_match else None
                status_text = re.sub(r"[\d\.\s㎍/㎥ppm]", "", full_text).strip() or "보통"

                target_key = None
                if "미세먼지" in title and "초" not in title: target_key = "미세먼지"
                elif "초미세먼지" in title: target_key = "초미세먼지"
                elif "자외선" in title: target_key = "자외선"
                elif "오존" in title: target_key = "오존"

                if target_key:
                    metrics[target_key]["status"] = status_text
                    metrics[target_key]["value"] = num_val

        pm10_num = metrics["미세먼지"]["value"] or 45
        pm25_num = metrics["초미세먼지"]["value"] or 23

        return {
            "temperature": temp_val,
            "pm10": int(pm10_num),
            "status_pm10": metrics["미세먼지"]["status"],
            "pm25": int(pm25_num),
            "status_pm25": metrics["초미세먼지"]["status"],
            "uv_num": metrics["자외선"]["value"],
            "status_uv": metrics["자외선"]["status"],
            "status_o3": metrics["오존"]["status"]
        }
    except Exception as e:
        print(f"❌ [네이버 크롤링 실패]: {e}")
        return None


def safe_requests_get(url: str, params: dict) -> requests.Response:
    try:
        res = requests.get(url, params=params, timeout=3)
        return res if res.status_code == 200 else None
    except Exception:
        return None


# =====================================================================
# [PRE-STEP] 법정동 연계정보 마스터 로드
# =====================================================================
@st.cache_data
def locations_upload():
    csv_filename = "국가데이터처_법정동 연계정보_20250602.csv"
    if not os.path.exists(csv_filename):
        csv_filename = os.path.join(BASE_DIR, "국가데이터처_법정동 연계정보_20250602.csv")

    if not os.path.exists(csv_filename):
        return None, None, None

    try:
        try:
            raw_df = pd.read_csv(csv_filename, encoding="cp949")
        except UnicodeDecodeError:
            raw_df = pd.read_csv(csv_filename, encoding="utf-8-sig")

        raw_df.columns = raw_df.columns.str.strip()
        cols = {
            'sido': '시도명' if '시도명' in raw_df.columns else '시도',
            'sgg': '시군구명' if '시군구명' in raw_df.columns else '시군구',
            'hjd': '행정동명' if '행정동명' in raw_df.columns else '행정동',
            'bjd': '법정동명' if '법정동명' in raw_df.columns else '법정동'
        }

        target_cols = list(cols.values())
        clean_df = raw_df.dropna(subset=target_cols).copy()
        for col in target_cols:
            clean_df[col] = clean_df[col].astype(str).str.strip()

        locations_df = clean_df[target_cols].drop_duplicates().copy()
        locations_df.columns = ['시도명', '시군구명', '행정동명', '법정동명']

        h2b_map = locations_df.groupby(['시도명', '시군구명', '행정동명'])['법정동명'].apply(lambda x: list(set(x))).to_dict()
        valid_bjd_map = locations_df.groupby(['시도명', '시군구명'])['법정동명'].apply(lambda x: list(set(x))).to_dict()

        return locations_df, h2b_map, valid_bjd_map
    except Exception as e:
        print(f"❌ [마스터 데이터 로드 실패]: {e}")
        return None, None, None


def get_beobjong_from_map(sido: str, sigungu: str, umd_name: str, h2b_map: dict, valid_bjd_map: dict) -> str:
    if not h2b_map or not valid_bjd_map:
        return umd_name

    map_key = (sido, sigungu, umd_name)
    if map_key in h2b_map and h2b_map[map_key]:
        return h2b_map[map_key][0]

    sgg_key = (sido, sigungu)
    if sgg_key in valid_bjd_map:
        valid_bjds = valid_bjd_map[sgg_key]
        if umd_name in valid_bjds:
            return umd_name
        if valid_bjds:
            return sorted(valid_bjds)[0]

    return umd_name


# =====================================================================
# [STEP 1] Gemini 기반 지명 추론 및 환각 검증
# =====================================================================
def process_user_request(user_input: str) -> dict:
    prompt = f"""
    당신은 한국어 지명 추론 및 행정구역 세트 추출 전문가입니다.
    사용자 질문을 분석하여 아래 규칙에 따라 JSON으로 답변하세요.

    [사용자 질문]
    "{user_input}"

    [수행 규칙]
    1. 사용자의 질문이 날씨, 대기질, 미세먼지, 오존 등 [환경 정보] 관련 질문인지 판단하세요 (is_location_query: true/false).
    2. 질문에서 언급되거나 유추되는 지명을 **[시도명, 시군구명, 법정동명] 형태의 3개 원소를 가진 배열 세트**로 구성하여 location_sets에 담으세요.

    [행정구역 정제 엄격 규칙]
    - **가상 지명 절대 생성 금지:** 시/군/구 명칭 뒤에 단순히 '동'이나 '리'를 붙인 가상 지명(예: 경기도 시흥시 시흥동)을 만들지 마세요.
    - **상위 행정구역만 입력 시:** 해당 시/군/구의 실제 대표 주요 동 2~3곳을 반환하세요.
    - **숫자형 행정동 통합:** "정왕1동" ➔ "정왕동".

    [응답 포맷] (JSON만 출력)
    {{
        "is_location_query": true,
        "location_sets": [
            ["시도명", "시군구명", "법정동명"]
        ]
    }}
    """.strip()

    try:
        result = call_gemini_api(prompt=prompt, output_type="json")
        if isinstance(result, dict) and not result.get("error"):
            return {
                "is_location_query": result.get("is_location_query", False),
                "location_sets": result.get("location_sets", [])
            }
    except Exception as e:
        print(f"❌ [Gemini 1차 추론 예외]: {e}")

    return {"is_location_query": False, "location_sets": []}


# =====================================================================
# [STEP 2 & 3] 대기질 수집 및 파이프라인 연동
# =====================================================================
def get_fallback_data(station_name="기본측정소", sido="", sigungu="", umd=""):
    return {
        "pm10": 45, "status_pm10": "보통",
        "pm25": 23, "status_pm25": "보통",
        "o3": 0.035, "status_o3": "보통",
        "so2": 0.003, "co": 0.5, "no2": 0.025,
        "yellow_dust": "안심 (영향 없음)",
        "temp": 22.0, "station": station_name,
        "sido": sido, "sigungu": sigungu, "umd": umd
    }


def fetch_air_quality_by_location(location_set: list, h2b_map: dict, valid_bjd_map: dict) -> dict:
    if not location_set or len(location_set) < 3:
        return get_fallback_data()

    sido, sigungu, raw_umd = location_set[0], location_set[1], location_set[2]
    umd_name = get_beobjong_from_map(sido, sigungu, raw_umd, h2b_map, valid_bjd_map)
    full_location = f"{sido} {sigungu} {umd_name}".strip()

    crawled = get_naver_weather_with_numbers(full_location)
    if crawled:
        return {
            "pm10": crawled["pm10"], "status_pm10": crawled["status_pm10"],
            "pm25": crawled["pm25"], "status_pm25": crawled["status_pm25"],
            "o3": 0.030, "status_o3": crawled["status_o3"],
            "so2": 0.003, "co": 0.5, "no2": 0.025,
            "yellow_dust": "안심 (영향 없음)",
            "temp": crawled["temperature"],
            "station": f"{full_location}(실시간)",
            "sido": sido, "sigungu": sigungu, "umd": umd_name
        }

    return get_fallback_data("기본측정소", sido, sigungu, umd_name)


def generate_final_response(user_input: str, air_results: list, user_profile: dict = None) -> str:
    for air in air_results:
        ml_res = predict_pm10_with_explanation(air)
        if ml_res: air["ml_model_prediction"] = ml_res

    prompt = f"""
    당신은 친절하고 전문적인 대기질 안내 AI 비서입니다.
    사용자 질문과 실시간 측정 데이터 및 LightGBM 머신러닝 예측 결과를 종합하여 답변하세요.

    [사용자 질문]
    "{user_input}"

    [사용자 프로필 설정]
    {json.dumps(user_profile, ensure_ascii=False)}

    [수집된 대기질 및 ML 예측 데이터]
    {json.dumps(air_results, ensure_ascii=False, indent=2)}

    [답변 필수 포함 항목]
    1. 측정된 지역 및 실시간 미세먼지, 초미세먼지, 오존 수치 및 등급
    2. LightGBM 모델의 PM10 예측 수치와 가스 오염원(SO2, CO, O3, NO2) 기여도 언급
    3. 사용자 프로필 맞춤 활동(환기/산책) 가이드 작성
    """.strip()

    try:
        res = call_gemini_api(prompt=prompt, output_type="text")
        return res if isinstance(res, str) else res.get("text", "")
    except Exception as e:
        return f"답변 생성 중 오류가 발생했습니다: {e}"


# =====================================================================
# 🖥️ [Streamlit 메인 UI 레이아웃]
# =====================================================================
locations_df, h2b_map, valid_bjd_map = locations_upload()

st.title("🌤️ 대기질 및 호흡기 건강 안내 AI 비서")
st.markdown("실시간 공기 상태 분석 및 LightGBM 머신러닝 기반 미세먼지 예측 리포트를 제공합니다.")

# 사이드바 설정
with st.sidebar:
    st.header("📍 기본 관심 지역 설정")
    sido_val = st.selectbox("시/도", ["경기도", "서울특별시", "인천광역시"], index=0)
    sigungu_val = st.text_input("시/군/구", value="시흥시")
    umd_val = st.text_input("읍/면/동", value="정왕동")

    st.session_state["selected_sido"] = sido_val
    st.session_state["selected_sigungu"] = sigungu_val
    st.session_state["selected_umd"] = umd_val

    st.markdown("---")
    st.header("👤 맞춤 프로필 설정")
    user_type = st.selectbox("대상 구분", ["일반 성인", "영유아/어린이", "노약자", "호흡기 질환자"])
    activity = st.selectbox("주요 활동", ["산책 / 야외운동", "환기 / 실내활동", "출퇴근"])
    ai_style = st.selectbox("답변 스타일", ["친절하고 세심한 설명", "전문 수치/데이터 중심 분석", "핵심만 3줄 요약"])

    st.session_state["user_profile"] = {
        "user_type": user_type,
        "activity": activity,
        "ai_style": ai_style
    }

current_location_str = f"{st.session_state['selected_sido']} {st.session_state['selected_sigungu']} {st.session_state['selected_umd']}"
st.info(f"현재 지정된 위치: **[{current_location_str}]**")

raw_user_input = st.text_input("💬 대기질 질문을 입력하세요 (예: 미세먼지 어때?, 마스크 써야 해?):", key="user_question")

if st.button("분석 실행", type="primary") or raw_user_input:
    if not raw_user_input.strip():
        st.warning("질문을 입력해 주세요!")
    else:
        with st.spinner("🔍 실시간 데이터 수집 및 LightGBM AI 분석 진행 중..."):
            
            # 🌟 [기존 구조 변경 없이 딱 여기만 추가!]
            # 사용자가 단답으로 검색 시, 사이드바에서 고른 위치를 강제로 입력문 앞에 연결합니다.
            full_user_input = raw_user_input.strip()
            if current_location_str not in full_user_input:
                full_user_input = f"[{current_location_str}] {full_user_input}"

            # 기존 함수 그대로 호출
            gemini_res = process_user_request(full_user_input)
            is_query = gemini_res.get("is_location_query", False)
            location_sets = gemini_res.get("location_sets", [])

            # Gemini가 지명을 못 찾았을 경우 Fallback
            if not location_sets:
                location_sets = [[st.session_state['selected_sido'], st.session_state['selected_sigungu'], st.session_state['selected_umd']]]

            # 기존 함수 그대로 호출
            air_results = [
                fetch_air_quality_by_location(loc, h2b_map, valid_bjd_map)
                for loc in location_sets
            ]

            # 기존 함수 그대로 호출
            final_answer = generate_final_response(full_user_input, air_results, st.session_state["user_profile"])

            st.markdown("### 📊 분석 결과 리포트")
            st.success(final_answer)
