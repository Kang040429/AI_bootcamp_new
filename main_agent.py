import os
import json
import time
import urllib.parse
import requests
import random
import re
import pandas as pd
import numpy as np
import joblib
import streamlit as st
from bs4 import BeautifulSoup
from gemini_client import call_gemini_api


# =====================================================================
# 🌲 [LightGBM] 저장된 예측 모델 및 Feature Importance 로드
# =====================================================================


# =====================================================================
# 🔧 [수정] 파일이 있는 현재 위치를 기준으로 절대 경로를 자동 생성합니다.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "lightgbm_pm10_model.pkl")

@st.cache_resource
def load_lgbm_model():
    if os.path.exists(MODEL_PATH):
        try:
            model = joblib.load(MODEL_PATH)
            print("✅ [LightGBM] 모델 로드 성공!")
            return model
        except Exception as e:
            print(f"❌ [LightGBM] 모델 로드 실패: {e}")
    else:
        print(f"⚠️ [LightGBM] '{MODEL_PATH}' 파일이 경로에 없습니다. ML 예측을 건너뜁니다.")
    return None

lgb_model = load_lgbm_model()

# 특성 중요도 사전 계산 (%)
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
        print(f"⚠️ [LightGBM] 특성 중요도 계산 중 예외 발생: {e}")


def predict_pm10_with_explanation(air_data: dict) -> dict:
    """
    대기질 수집 결과(SO2, CO, O3, NO2 등)를 LightGBM 모델 입력 형식으로 변환하여 PM10을 예측합니다.
    """
    if lgb_model is None:
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

        predicted_pm10 = float(round(lgb_model.predict(input_df)[0], 1))

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
# 🕸️ [크롤링 모듈] 네이버 실시간 기온, 미세먼지, 초미세, 자외선 수집
# =====================================================================
def get_naver_weather_with_numbers(location_name: str) -> dict:
    """
    네이버 검색을 통해 [현재 온도, 미세먼지, 초미세먼지, 자외선]을 수치 및 상태로 수집합니다.
    """
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

        # 1. 현재 온도
        temp_val = 22.0
        temp_elem = soup.select_one(".temperature_text strong, .weather_graph .temperature_text strong")
        if temp_elem:
            temp_raw = temp_elem.get_text().replace("현재 온도", "").replace("°", "").strip()
            match = re.search(r"[-+]?\d*\.\d+|\d+", temp_raw)
            if match:
                temp_val = float(match.group())

        # 2. 미세먼지/초미세/자외선/오존 영역
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

                status_text = re.sub(r"[\d\.\s㎍/㎥ppm]", "", full_text).strip()
                if not status_text:
                    status_text = full_text

                target_key = None
                if "미세먼지" in title and "초" not in title:
                    target_key = "미세먼지"
                elif "초미세먼지" in title:
                    target_key = "초미세먼지"
                elif "자외선" in title:
                    target_key = "자외선"
                elif "오존" in title:
                    target_key = "오존"

                if target_key:
                    metrics[target_key]["status"] = status_text if status_text else "보통"
                    metrics[target_key]["value"] = num_val

        # 3. 수치 보정
        pm10_num = metrics["미세먼지"]["value"]
        if pm10_num is None:
            status_map = {"좋음": 20, "보통": 45, "나쁨": 90, "매우나쁨": 160, "매우 나쁨": 160}
            pm10_num = status_map.get(metrics["미세먼지"]["status"], 45)

        pm25_num = metrics["초미세먼지"]["value"]
        if pm25_num is None:
            status_map = {"좋음": 10, "보통": 23, "나쁨": 55, "매우나쁨": 85, "매우 나쁨": 85}
            pm25_num = status_map.get(metrics["초미세먼지"]["status"], 23)

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


# =====================================================================
# 🛡️ [API 예외 시 즉시 크롤링 전환] HTTP 요청 함수
# =====================================================================
def safe_requests_get(url: str, params: dict) -> requests.Response:
    """
    API 요청 실패 시 대기 및 재시도 없이 즉시 None을 반환하여
    크롤링 단계로 빠르게 전환되도록 합니다.
    """
    try:
        res = requests.get(url, params=params, timeout=3)
        if res.status_code == 200:
            return res
        else:
            print(f"🚨 [API 접속 실패] URL: {url.split('/')[-1]} | Status: {res.status_code} -> 즉시 크롤링으로 전환합니다.")
            return None
    except Exception as e:
        print(f"❌ [HTTP 요청 예외 발생] URL: {url.split('/')[-1]} | Error: {e} -> 즉시 크롤링으로 전환합니다.")
        return None


# =====================================================================
# [PRE-STEP] 국가데이터처 CSV 기반 위치 마스터 로드 및 매핑
# =====================================================================
@st.cache_data
def locations_upload():
    csv_filename = "C:/AI_bootcamp/국가데이터처_법정동 연계정보_20250602.csv"
    
    if not os.path.exists(csv_filename):
        csv_filename = "국가데이터처_법정동 연계정보_20250602.csv"

    if not os.path.exists(csv_filename):
        print(f"❌ [파일 에러] '{csv_filename}' 파일이 경로에 존재하지 않습니다.")
        return None, None, None

    try:
        print("📂 [마스터 데이터] CSV 로드 시작...")
        try:
            raw_df = pd.read_csv(csv_filename, encoding="cp949")
        except UnicodeDecodeError:
            raw_df = pd.read_csv(csv_filename, encoding="utf-8-sig")

        raw_df.columns = raw_df.columns.str.strip()
        clean_df = raw_df.copy()

        cols = {
            'sido': '시도명' if '시도명' in clean_df.columns else '시도',
            'sgg': '시군구명' if '시군구명' in clean_df.columns else '시군구',
            'hjd': '행정동명' if '행정동명' in clean_df.columns else '행정동',
            'bjd': '법정동명' if '법정동명' in clean_df.columns else '법정동'
        }

        target_cols = list(cols.values())
        clean_df = clean_df.dropna(subset=target_cols).copy()
        
        for col in target_cols:
            clean_df[col] = clean_df[col].astype(str).str.strip()

        locations_df = clean_df[target_cols].drop_duplicates().copy()
        locations_df.columns = ['시도명', '시군구명', '행정동명', '법정동명']

        exact_dummy = (locations_df['행정동명'] == locations_df['시군구명']) | \
                      (locations_df['법정동명'] == locations_df['시군구명'])
        
        sgg_cores = locations_df['시군구명'].apply(lambda x: x[:-1] if len(x) > 2 else x)
        core_dummy = (locations_df['행정동명'] == sgg_cores) | \
                     (locations_df['법정동명'] == sgg_cores)

        dummy_indices = locations_df[exact_dummy | core_dummy].index
        drop_count = len(dummy_indices)
        
        locations_df = locations_df.drop(dummy_indices).reset_index(drop=True)

        h2b_map = locations_df.groupby(['시도명', '시군구명', '행정동명'])['법정동명'].apply(lambda x: list(set(x))).to_dict()
        valid_bjd_map = locations_df.groupby(['시도명', '시군구명'])['법정동명'].apply(lambda x: list(set(x))).to_dict()

        print(f"🧹 더미 데이터 총 {drop_count}개 행 삭제 완료.")
        print("✅ [마스터 데이터] 로드 완료!")
        return locations_df, h2b_map, valid_bjd_map

    except Exception as e:
        print(f"❌ [마스터 데이터 로드 실패]: {e}")
        return None, None, None


def get_beobjong_from_map(sido: str, sigungu: str, umd_name: str, h2b_map: dict, valid_bjd_map: dict) -> str:
    if not h2b_map or not valid_bjd_map:
        return umd_name

    map_key = (sido, sigungu, umd_name)
    if map_key in h2b_map:
        bjd_list = h2b_map[map_key]
        if bjd_list:
            return bjd_list[0]

    sgg_key = (sido, sigungu)
    if sgg_key in valid_bjd_map:
        valid_bjds = valid_bjd_map[sgg_key]
        if umd_name in valid_bjds:
            return umd_name
        
        if valid_bjds:
            fallback_bjd = sorted(valid_bjds)[0]
            print(f"⚠️ [{sido} {sigungu} {umd_name}] 교정 ➔ 실제 법정동 [{fallback_bjd}]")
            return fallback_bjd

    return umd_name


def combine_user_input_with_location(user_input: str, selected_location: str = None) -> str:
    if selected_location:
        selected_location = selected_location.strip()
        if selected_location and selected_location not in user_input:
            return f"[{selected_location}] {user_input}"
            
    return user_input


# =====================================================================
# [STEP 1] Gemini 기반 지명 추론
# =====================================================================
def process_user_request(user_input: str) -> dict:
    prompt = f"""
    당신은 한국어 지명 추론 및 행정구역 세트 추출 전문가입니다.
    사용자 질문을 분석하여 아래 규칙에 따라 JSON으로 답변하세요.

    [사용자 질문]
    "{user_input}"

    [수행 규칙]
    1. 사용자의 질문이 날씨, 대기질, 미세먼지, 오존, 황사, 공기 상태, 야외활동 가능 여부 등 [환경 정보] 관련 질문인지 판단하세요 (is_location_query: true/false).
    2. 질문에서 언급되거나 유추되는 지명을 **[시도명, 시군구명, 법정동명] 형태의 3개 원소를 가진 배열 세트**로 구성하여 location_sets에 담으세요.
    3. 지역명만 써져 있는 경우에는 환경 정보를 묻는 질문으로 취급해 주세요.

    [행정구역 정제 엄격 규칙]
    - **'리' 단위 금지:** '리' 단위 지명(예: 화리현리, 가재리)은 반드시 상위 '읍/면' 또는 대표 '동' 명칭으로 변환하세요.
    - **상위 행정구역만 입력 시 (예: "시흥", "오산", "서울"):** 
      단일 지역 확정이 어려운 경우 해당 시/도의 주요 대표 거점 2~3곳을 `location_sets`에 배열로 반환하세요.
    - **숫자형 행정동 통합:** "반포1동" ➔ "반포동".

    [응답 포맷] (다른 설명 없이 오직 이 JSON만 출력)
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
        else:
            print(f"❌ [1차 Gemini API 응답 에러]: {result}")
    except Exception as e:
        print(f"❌ [1차 Gemini API 예외 발생]: {e}")

    return {"is_location_query": False, "location_sets": []}


# =====================================================================
# [STEP 2] Fallback 데이터 정의
# =====================================================================
def get_fallback_data(station_name="기본측정소", sido="", sigungu="", umd=""):
    print(f"⚠️ [{sido} {sigungu} {umd}] API 및 크롤링 실패로 기본 Fallback 데이터 적용")
    return {
        "pm10": 45,
        "status_pm10": "보통",
        "pm25": 23,
        "status_pm25": "보통",
        "o3": 0.035,
        "status_o3": "보통",
        "so2": 0.003,
        "co": 0.5,
        "no2": 0.025,
        "yellow_dust": "안심 (영향 없음)",
        "temp": 22.0,
        "humi": 50,
        "traffic": "보통 정체",
        "station": station_name,
        "sido": sido,
        "sigungu": sigungu,
        "umd": umd
    }


@st.cache_data(ttl=86400)
def get_station_name_cached(sido: str, sigungu: str, umd_name: str, location_key: str) -> str:
    raw_location_key = urllib.parse.unquote(location_key)

    search_umd = ''.join([i for i in umd_name if not i.isdigit()])
    if search_umd.endswith("동") and len(search_umd) > 2:
        search_umd = search_umd
    elif search_umd.endswith("리") and len(search_umd) > 2:
        search_umd = search_umd[:-1]

    try:
        # 1️⃣ TM 좌표 변환 API
        url_tm = "http://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getTMStdrCrdnt"
        params_tm = {
            "serviceKey": raw_location_key,
            "returnType": "json",
            "umdName": search_umd,
            "numOfRows": "50",
            "pageNo": "1"
        }
        
        res_tm_raw = safe_requests_get(url_tm, params=params_tm)
        if not res_tm_raw:
            return None

        tmX, tmY = None, None
        try:
            items_tm = res_tm_raw.json().get("response", {}).get("body", {}).get("items", [])
            if isinstance(items_tm, list):
                for item in items_tm:
                    item_sido = item.get("sidoName", "") or ""
                    item_sgg = item.get("sggName", "") or ""
                    
                    sido_check = (sido[:2] in item_sido) if sido and item_sido else True
                    sgg_check = (sigungu in item_sgg or item_sgg in sigungu) if sigungu and item_sgg else True

                    if sido_check and sgg_check:
                        tmX, tmY = item.get("tmX"), item.get("tmY")
                        break
                
                if not tmX and items_tm:
                    tmX, tmY = items_tm[0].get("tmX"), items_tm[0].get("tmY")
        except Exception as parse_e:
            print(f"❌ [TM 좌표 JSON 파싱 에러]: {parse_e}")
            return None

        if not tmX or not tmY:
            print(f"❌ [{sido} {sigungu} {umd_name}] TM 좌표를 찾을 수 없습니다.")
            return None

        # 2️⃣ 근접 측정소 조회 API
        url_nearby = "http://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getNearbyMsrstnList"
        params_nearby = {
            "serviceKey": raw_location_key,
            "returnType": "json",
            "tmX": tmX,
            "tmY": tmY,
            "ver": "1.1"
        }
        
        res_nearby_raw = safe_requests_get(url_nearby, params=params_nearby)
        if not res_nearby_raw:
            return None

        try:
            items_nearby = res_nearby_raw.json().get("response", {}).get("body", {}).get("items", [])
            if isinstance(items_nearby, list) and items_nearby:
                station_name = items_nearby[0].get("stationName")
                print(f"✅ [{sido} {sigungu} {umd_name}] ➔ 측정소 매핑: {station_name}")
                return station_name
        except Exception as parse_e:
            print(f"❌ [근접측정소 JSON 파싱 에러]: {parse_e}")
            return None

    except Exception as e:
        print(f"❌ [get_station_name_cached 예외 발생]: {e}")

    return None


# =====================================================================
# 🔄 [핵심 수집 함수] API 접속 실패 시 즉시 크롤링 ➔ 실패 시 Fallback
# =====================================================================
def fetch_air_quality_by_location(location_set: list, location_key: str, air_key: str, h2b_map: dict, valid_bjd_map: dict = None) -> dict:
    if not location_set or len(location_set) < 3:
        return get_fallback_data()

    sido, sigungu, raw_umd = location_set[0], location_set[1], location_set[2]
    umd_name = get_beobjong_from_map(sido, sigungu, raw_umd, h2b_map, valid_bjd_map)
    full_location = f"{sido} {sigungu} {umd_name}".strip()
    raw_air_key = urllib.parse.unquote(air_key) if air_key else ""

    # -------------------------------------------------------------
    # 1️⃣ [1순위] 에어코리아 API 호출 시도
    # -------------------------------------------------------------
    if location_key and air_key:
        try:
            station_name = get_station_name_cached(sido, sigungu, umd_name, location_key)

            if station_name:
                base_air_url = st.secrets.get(
                    "AIR_PORTAL_URL",
                    "http://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
                )
                params_air = {
                    "serviceKey": raw_air_key,
                    "returnType": "json",
                    "stationName": station_name,
                    "dataTerm": "DAILY",
                    "ver": "1.3"
                }
                
                res_air_raw = safe_requests_get(base_air_url, params=params_air)

                if res_air_raw:
                    items_air = res_air_raw.json().get("response", {}).get("body", {}).get("items", [])
                    if isinstance(items_air, list) and len(items_air) > 0:
                        target_station = items_air[0]
                        
                        pm10_val = target_station.get("pm10Value")
                        pm25_val = target_station.get("pm25Value")
                        o3_val = target_station.get("o3Value")
                        so2_val = target_station.get("so2Value")
                        co_val = target_station.get("coValue")
                        no2_val = target_station.get("no2Value")

                        pm10 = int(pm10_val) if pm10_val and pm10_val != "-" else 35
                        pm25 = int(pm25_val) if pm25_val and pm25_val != "-" else 18
                        o3 = float(o3_val) if o3_val and o3_val != "-" else 0.030
                        so2 = float(so2_val) if so2_val and so2_val != "-" else 0.003
                        co = float(co_val) if co_val and co_val != "-" else 0.5
                        no2 = float(no2_val) if no2_val and no2_val != "-" else 0.025

                        status_pm10 = "좋음" if pm10 <= 30 else ("보통" if pm10 <= 80 else ("나쁨" if pm10 <= 150 else "매우 나쁨"))
                        status_pm25 = "좋음" if pm25 <= 15 else ("보통" if pm25 <= 35 else ("나쁨" if pm25 <= 75 else "매우 나쁨"))
                        status_o3 = "좋음" if o3 <= 0.030 else ("보통" if o3 <= 0.090 else ("나쁨" if o3 <= 0.150 else "매우 나쁨"))

                        yellow_dust_status = "안심 (영향 없음)"
                        if pm10 > 300: yellow_dust_status = "🚨 황사 경보 수준 (매우 위험)"
                        elif pm10 > 150: yellow_dust_status = "⚠️ 황사 주의 수준 (위험)"
                        elif pm10 > 80 and (pm10 / (pm25 + 1)) > 2.5: yellow_dust_status = "🟡 가벼운 황사 영향/약한 황사"

                        print(f"✅ [에어코리아 API 수집 성공] {full_location} ({station_name} 측정소)")
                        return {
                            "pm10": pm10, "status_pm10": status_pm10,
                            "pm25": pm25, "status_pm25": status_pm25,
                            "o3": o3, "status_o3": status_o3,
                            "so2": so2, "co": co, "no2": no2,
                            "yellow_dust": yellow_dust_status,
                            "temp": 24.5, "humi": 65, "traffic": "보통",
                            "station": station_name,
                            "sido": sido, "sigungu": sigungu, "umd": umd_name
                        }
        except Exception as e:
            print(f"⚠️ [API 수집 예외] {e} -> 크롤링으로 직행합니다.")

    # -------------------------------------------------------------
    # 2️⃣ [2순위] API 접속 실패 시 즉시 네이버 크롤링 수행
    # -------------------------------------------------------------
    print(f"🌐 [크롤링 전환] 네이버에서 '{full_location}' 날씨/대기질 정보 수집 중...")
    crawled = get_naver_weather_with_numbers(full_location)

    if crawled:
        print(f"✅ [네이버 크롤링 성공] {full_location} -> PM10: {crawled['pm10']} ({crawled['status_pm10']})")
        return {
            "pm10": crawled["pm10"],
            "status_pm10": crawled["status_pm10"],
            "pm25": crawled["pm25"],
            "status_pm25": crawled["status_pm25"],
            "o3": 0.030,
            "status_o3": crawled["status_o3"],
            "so2": 0.003,
            "co": 0.5,
            "no2": 0.025,
            "yellow_dust": "안심 (영향 없음)",
            "temp": crawled["temperature"],
            "uv_num": crawled["uv_num"],
            "status_uv": crawled["status_uv"],
            "station": f"{full_location}(네이버 크롤링)",
            "sido": sido,
            "sigungu": sigungu,
            "umd": umd_name
        }

    # -------------------------------------------------------------
    # 3️⃣ [3순위] 크롤링까지 실패 시 Fallback 데이터 반환
    # -------------------------------------------------------------
    return get_fallback_data("기본측정소", sido, sigungu, umd_name)


# =====================================================================
# [STEP 3] N개 지명 후보 일괄 수집
# =====================================================================
def fetch_all_air_candidates(location_sets: list, location_key: str, air_key: str, h2b_map: dict, valid_bjd_map: dict = None) -> list:
    results = []
    if not location_sets:
        return [get_fallback_data()]

    for loc in location_sets:
        res = fetch_air_quality_by_location(
            location_set=loc,
            location_key=location_key,
            air_key=air_key,
            h2b_map=h2b_map,
            valid_bjd_map=valid_bjd_map
        )
        results.append(res)
        time.sleep(0.3)

    return results


# =====================================================================
# [STEP 4] Gemini 답변 생성
# =====================================================================
def generate_final_response(user_input: str, air_results: list, user_profile: dict = None) -> str:
    for air in air_results:
        ml_res = predict_pm10_with_explanation(air)
        if ml_res:
            air["ml_model_prediction"] = ml_res

    profile_guide = ""
    style_instruction = ""
    
    if user_profile:
        user_type = user_profile.get('user_type', '일반 성인')
        activity = user_profile.get('activity', '환기 / 산책')
        ai_style = user_profile.get('ai_style', '핵심만 3줄 요약')

        profile_guide = f"""
    [사용자 맞춤 프로필 정보]
    - 사용자 상태/대상: {user_type} (영유아/노약자/호흡기 질환자인 경우 안전 가이드를 보수적으로 제공)
    - 관심 야외활동/목적: {activity}
    - 선호 답변 스타일: {ai_style}
    """

        if ai_style == "친절하고 세심한 설명":
            style_instruction = """
    [답변 출력 스타일: 친절하고 세심한 설명]
    반드시 아래의 구조 템플릿을 그대로 활용하여 따뜻하게 작성해 주세요.

    [작성 양식]
    안녕하세요! 😊 (상황에 맞는 친근한 인사말)

    🌿 **오늘의 공기 상태**
    (어려운 전문 수치 대신 '좋음', '보통' 등 등급 중심으로 쉽게 풀어서 설명하는 2~3문장)

    🤖 **AI 머신러닝(LightGBM) 예측**
    - (ml_model_prediction 데이터가 있는 경우, 주요 가스 오염원 기여도 및 모델이 예상한 PM10 수치를 쉽게 풀어서 1~2문장 안내)

    💡 **세심한 산책/외출 팁**
    - (마스크 착용 여부, 추천 외출 시간대 등 따뜻하고 세심한 권장사항 2~3개)
    - 기분 좋은 산책 되세요! (따뜻한 마무리 인사)
    """
        elif ai_style == "전문 수치/데이터 중심 분석":
            style_instruction = """
    [답변 출력 스타일: 전문 수치/데이터 중심 분석]
    감정적인 인사말이나 사족을 제거하고, 오직 아래의 전문 보고서 서식으로만 작성해 주세요.

    [작성 양식]
    📊 **[대기질 측정 데이터 분석 보고서]**
    • 측정소: {측정소명}
    • 실시간 미세먼지(PM10): {수치}㎍/㎥ ({상태})
    • 초미세먼지(PM2.5): {수치}㎍/㎥ ({상태})
    • 오존(O3): {수치}ppm ({상태})
    • 황사 영향: {황사상태}

    🤖 **[LightGBM AI 머신러닝 예측 결과]**
    • 예상 PM10 농도: {ml_predicted_pm10} ㎍/㎥
    • 주요 가스 오염원 기여 요인: {top_contributing_factors}

    🔍 **[데이터 종합 평가]**
    (수치 기반 대기 상태 및 오염 물질 축적/정체 요인 2문장 이내 분석)

    📋 **[행동 권고 기준]**
    1. 야외활동: (수치에 근거한 활동 가능 여부 판정)
    2. 환기 여부: (수치에 근거한 환기 적합성 판정)
    """
        else:
            style_instruction = """
    [답변 출력 스타일: 핵심만 3줄 요약]
    오직 아래 3줄 형태로만 출력하세요. 다른 서론/결론은 일절 작성하지 마세요.

    • **공기 상태:** (측정소 및 수치/상태 요약 + ML 예측 PM10 수치 간단 병기)
    • **활동 판정:** (산책/환기 가능 여부)
    • **주의 사항:** (주요 가스 오염원 기여도 또는 핵심 주의사항 1가지)
    """

    prompt = f"""
    당신은 친절하고 전문적인 대기질 및 호흡기/면역 건강 안내 AI 비서입니다.
    사용자 질문과 수집 데이터, 그리고 LightGBM 머신러닝 예측 결과를 종합하여 답변해 주세요.

    [사용자 질문]
    "{user_input}"
    {profile_guide}

    [수집된 실시간 대기질 및 LightGBM 예측 데이터]
    {json.dumps(air_results, ensure_ascii=False, indent=2)}

    {style_instruction}

    [공통 필수 규칙]
    0. **다중지역:** 두 곳 이상 여러 곳에서 환경정보 값을 받았다면, 두 곳의 환경정보를 모두 표시해 주세요.
    1. **주요 대기질 항목 포함:** 요청된 지역의 미세먼지(PM10), 초미세먼지(PM2.5), 오존(O3) 수치 및 등급과 황사 영향도를 언급해 주세요.
    2. **LightGBM ML 예측 언급:** 데이터 내 `ml_model_prediction` 항목이 존재하는 경우, AI 머신러닝 예측 결과(예상 PM10 농도 및 주요 가스 기여도)를 답변에 반드시 포함해 주세요.
    3. **오존(O3) 특화 안내:** 오존 수치가 '나쁨'(0.091ppm 이상) 이상일 경우, 실외 활동 자제를 강조해 주세요.
    4. **측정소 정보 명시:** 어떤 측정소 데이터인지 밝혀 주세요.
    5. **질문 의도 확인:** 질문 내용이 대기질/환경정보 관련 질문이 아니라면 "잘못 입력하셨거나 환경질문이 아닙니다"라는 취지의 문장을 출력해 주세요.
    """.strip()

    try:
        result = call_gemini_api(prompt=prompt, output_type="text")
        if isinstance(result, str): return result
        elif isinstance(result, dict) and "text" in result: return result["text"]
    except Exception as e:
        print(f"❌ [2차 Gemini API 예외 발생]: {e}")

    return "죄송합니다. 대기질 정보 및 ML 예측 결과를 바탕으로 답변을 생성하는 중 오류가 발생했습니다."


# =====================================================================
# 🧪 대화형 실행 테스트
# =====================================================================
if __name__ == "__main__":
    LOCATION_KEY = st.secrets.get("AIR_PORTAL_LOCATION_KEY", "")
    AIR_KEY = st.secrets.get("AIR_PORTAL_KEY", "")

    if not LOCATION_KEY or not AIR_KEY:
        print("ℹ️ API 키 미설정/누락 -> [네이버 크롤링 모드]를 기본 우선으로 연동합니다.")

    locations_df, h2b_map, valid_bjd_map = locations_upload()

    print("=" * 80)
    print("🚀 [대화형 파이프라인 테스트] 질문을 입력하세요. (종료: 'exit' 또는 'q')")
    print("=" * 80)

    test_cnt = 1
    key = True

    selected_location = "시흥시 정왕동"
    user_profile = {
        'user_type': '일반 성인',
        'activity': '산책',
        'ai_style': '친절하고 세심한 설명'
    }

    while key:
        try:
            raw_input_text = input(f"\n[{test_cnt:02d}] 💬 질문 입력 >> ").strip()

            if raw_input_text.lower() in ["exit", "q", "quit", "종료"]:
                print("\n👋 테스트를 종료합니다.")
                key = False
                break

            if not raw_input_text:
                print("⚠️ 질문을 입력해 주세요.")
                continue

            user_input = combine_user_input_with_location(raw_input_text, selected_location)
            print(f"📌 [최종 프롬프트 전달 문장]: {user_input}")

            gemini_res = process_user_request(user_input)
            is_query = gemini_res.get("is_location_query", False)
            location_sets = gemini_res.get("location_sets", [])

            print(f"  1️⃣ [1차 Gemini 추론] 추출된 행정구역: {location_sets}")

            if not is_query or not location_sets:
                print("  ⚠️ 환경/지명 질문이 아니거나 위치를 파악하지 못했습니다.")
                test_cnt += 1
                continue

            time.sleep(0.5)

            # API -> 크롤링 -> Fallback 3단계 자동 수집
            air_results = fetch_all_air_candidates(
                location_sets=location_sets,
                location_key=LOCATION_KEY,
                air_key=AIR_KEY,
                h2b_map=h2b_map,
                valid_bjd_map=valid_bjd_map
            )
            print(f"  2️⃣ [데이터 수집] 결과 데이터 {len(air_results)}건 준비 완료")

            final_answer = generate_final_response(user_input, air_results, user_profile)

            print("\n  3️⃣ [2차 Gemini + LightGBM] 최종 답변:")
            print("  " + "-" * 60)
            print(f"{final_answer}")
            print("  " + "-" * 60)

            test_cnt += 1
            time.sleep(0.5)

        except KeyboardInterrupt:
            print("\n\n👋 사용자 중단(Ctrl+C)으로 종료합니다.")
            key = False
            break
        except Exception as e:
            print(f"\n❌ [메인 루프 예외 발생]: {e}")
