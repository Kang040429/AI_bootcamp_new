import os
import json
import time
import urllib.parse
import requests
import random
import pandas as pd
import streamlit as st
from gemini_client import call_gemini_api


# =====================================================================
# 🛡️ [DEBUG 강화] HTTP 요청 및 에러 콘솔 출력 함수
# =====================================================================
def safe_requests_get(url: str, params: dict, max_retries: int = 3) -> requests.Response:
    """
    HTTP 요청 시 429(Rate Limit) 또는 네트워크 에러가 발생하면
    지수 백오프(Exponential Backoff) 방식으로 대기 후 자동 재시도하며 상세 에러를 CMD에 출력합니다.
    """
    delay = 1.0  # 첫 대기시간 1초
    for attempt in range(max_retries):
        try:
            res = requests.get(url, params=params, timeout=10)
            
            # HTTP 200 성공이 아닌 경우 상태 코드 CMD 출력
            if res.status_code != 200:
                print(f"🚨 [API 요청 에러] URL: {url.split('/')[-1]} | Status: {res.status_code} | Body: {res.text[:150]}")

            # 429 에러(Rate Limit) 발생 시 재시도
            if res.status_code == 429:
                print(f"⚠️ [API 429 제한 발생] {delay}초 대기 후 재시도합니다... ({attempt + 1}/{max_retries})")
                time.sleep(delay)
                delay *= 2  # 대기 시간 2배 증가
                break
                
            return res
        except Exception as e:
            print(f"❌ [HTTP 요청 예외 발생] URL: {url.split('/')[-1]} | Error: {e}")
            time.sleep(delay)
            delay *= 2
            
    return None


# =====================================================================
# [PRE-STEP] 국가데이터처 CSV 기반 위치 마스터 로드 및 매핑 딕셔너리 생성
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


# =====================================================================
# ✨ [NEW] 즐겨찾기 선택 지역명 자동 결합 함수
# =====================================================================
def combine_user_input_with_location(user_input: str, selected_location: str = None) -> str:
    """
    선택된 즐겨찾기 지역명이 존재하는 경우, 사용자 질문 앞에 결합하여 Gemini가 인식할 수 있게 변환합니다.
    """
    if selected_location:
        selected_location = selected_location.strip()
        if selected_location and selected_location not in user_input:
            return f"[{selected_location}] {user_input}"
            
    return user_input


# =====================================================================
# [STEP 1] Gemini 기반 지명 추론 및 법정동 세트 추출 함수
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
      (예: "서울 공기 어때?" ➔ [["서울특별시", "종로구", "종로1가"], ["서울특별시", "강남구", "역삼동"], ["서울특별시", "영등포구", "여의도동"]])
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
# [STEP 2] 에어코리아 대기질 수집
# =====================================================================
def get_fallback_data(station_name="기본측정소", sido="", sigungu="", umd=""):
    print(f"⚠️ [{sido} {sigungu} {umd}] 공공데이터 수집 실패로 기본 Fallback 데이터 적용")
    return {
        "pm10": 45,
        "status_pm10": "보통",
        "pm25": 23,
        "status_pm25": "보통",
        "o3": 0.035,
        "status_o3": "보통",
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

        tmX, tmY = None, None
        if res_tm_raw and res_tm_raw.status_code == 200:
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
                print(f"❌ [TM 좌표 JSON 파싱 에러]: {parse_e} | Response: {res_tm_raw.text[:200]}")

        if not tmX or not tmY:
            print(f"❌ [{sido} {sigungu} {umd_name}] TM 좌표를 찾을 수 없습니다.")
            return None

        time.sleep(0.3)

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

        if res_nearby_raw and res_nearby_raw.status_code == 200:
            try:
                items_nearby = res_nearby_raw.json().get("response", {}).get("body", {}).get("items", [])
                if isinstance(items_nearby, list) and items_nearby:
                    station_name = items_nearby[0].get("stationName")
                    print(f"✅ [{sido} {sigungu} {umd_name}] ➔ 측정소 매핑: {station_name}")
                    return station_name
            except Exception as parse_e:
                print(f"❌ [근접측정소 JSON 파싱 에러]: {parse_e} | Response: {res_nearby_raw.text[:200]}")

    except Exception as e:
        print(f"❌ [get_station_name_cached 예외 발생]: {e}")

    return None


def fetch_air_quality_by_location(location_set: list, location_key: str, air_key: str, h2b_map: dict, valid_bjd_map: dict = None) -> dict:
    if not location_set or len(location_set) < 3:
        return get_fallback_data()

    sido, sigungu, raw_umd = location_set[0], location_set[1], location_set[2]
    umd_name = get_beobjong_from_map(sido, sigungu, raw_umd, h2b_map, valid_bjd_map)
    raw_air_key = urllib.parse.unquote(air_key)

    try:
        station_name = get_station_name_cached(sido, sigungu, umd_name, location_key)

        if not station_name:
            return get_fallback_data(sido=sido, sigungu=sigungu, umd=umd_name)

        time.sleep(0.3)

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

        if not res_air_raw or res_air_raw.status_code != 200:
            status = res_air_raw.status_code if res_air_raw else 'No Response'
            print(f"❌ [대기질 API 에러] HTTP Status: {status}")
            return get_fallback_data(station_name, sido, sigungu, umd_name)

        try:
            items_air = res_air_raw.json().get("response", {}).get("body", {}).get("items", [])
            if not items_air or not isinstance(items_air, list):
                print(f"❌ [{station_name}] 대기질 데이터 항목 없음 (API 결과 비어있음)")
                return get_fallback_data(station_name, sido, sigungu, umd_name)

            target_station = items_air[0]
            
            pm10_val = target_station.get("pm10Value")
            pm25_val = target_station.get("pm25Value")
            o3_val = target_station.get("o3Value")

            pm10 = int(pm10_val) if pm10_val and pm10_val != "-" else 35
            pm25 = int(pm25_val) if pm25_val and pm25_val != "-" else 18
            o3 = float(o3_val) if o3_val and o3_val != "-" else 0.030

            if pm10 <= 30: status_pm10 = "좋음"
            elif pm10 <= 80: status_pm10 = "보통"
            elif pm10 <= 150: status_pm10 = "나쁨"
            else: status_pm10 = "매우 나쁨"

            if pm25 <= 15: status_pm25 = "좋음"
            elif pm25 <= 35: status_pm25 = "보통"
            elif pm25 <= 75: status_pm25 = "나쁨"
            else: status_pm25 = "매우 나쁨"

            if o3 <= 0.030: status_o3 = "좋음"
            elif o3 <= 0.090: status_o3 = "보통"
            elif o3 <= 0.150: status_o3 = "나쁨"
            else: status_o3 = "매우 나쁨"

            yellow_dust_status = "안심 (영향 없음)"
            if pm10 > 300:
                yellow_dust_status = "🚨 황사 경보 수준 (매우 위험)"
            elif pm10 > 150:
                yellow_dust_status = "⚠️ 황사 주의 수준 (위험)"
            elif pm10 > 80 and (pm10 / (pm25 + 1)) > 2.5:
                yellow_dust_status = "🟡 가벼운 황사 영향/약한 황사"

            return {
                "pm10": pm10,
                "status_pm10": status_pm10,
                "pm25": pm25,
                "status_pm25": status_pm25,
                "o3": o3,
                "status_o3": status_o3,
                "yellow_dust": yellow_dust_status,
                "temp": 24.5,
                "humi": 65,
                "traffic": "보통",
                "station": station_name,
                "sido": sido,
                "sigungu": sigungu,
                "umd": umd_name
            }
        except Exception as parse_e:
            print(f"❌ [대기질 JSON 파싱 예외]: {parse_e} | Response: {res_air_raw.text[:200]}")
            return get_fallback_data(station_name, sido, sigungu, umd_name)

    except Exception as e:
        print(f"⚠️ [{umd_name}] 대기질 수집 예외 발생: {e}")
        return get_fallback_data(sido=sido, sigungu=sigungu, umd=umd_name)


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
        time.sleep(0.5)

    return results


# =====================================================================
# [STEP 4] 대기질 + 황사 + 오존 데이터 기반 Gemini 최종 답변 생성
# =====================================================================
def generate_final_response(user_input: str, air_results: list, user_profile: dict = None) -> str:
    
    # 1. 프로필 정보 및 스타일별 엄격한 프롬프트 지침 구성
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

        # ✨ [개선된 템플릿 방식] 완전히 격식과 구조가 구분되도록 서식 지정
        if ai_style == "친절하고 세심한 설명":
            style_instruction = """
    [답변 출력 스타일: 친절하고 세심한 설명]
    반드시 아래의 구조 템플릿을 그대로 활용하여 따뜻하게 작성해 주세요.

    [작성 양식]
    안녕하세요! 😊 (상황에 맞는 친근한 인사말)

    🌿 **오늘의 공기 상태**
    (어려운 전문 수치 대신 '좋음', '보통' 등 등급 중심으로 쉽게 풀어서 설명하는 2~3문장)

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
    • 미세먼지(PM10): {수치}㎍/㎥ ({상태})
    • 초미세먼지(PM2.5): {수치}㎍/㎥ ({상태})
    • 오존(O3): {수치}ppm ({상태})
    • 황사 영향: {황사상태}

    🔍 **[데이터 종합 평가]**
    (수치 기반 대기 상태 및 오염 물질 축적/정체 요인 2문장 이내 분석)

    📋 **[행동 권고 기준]**
    1. 야외활동: (수치에 근거한 활동 가능 여부 판정)
    2. 환기 여부: (수치에 근거한 환기 적합성 판정)
    """
        else:  # 핵심만 3줄 요약 또는 기타 기본값
            style_instruction = """
    [답변 출력 스타일: 핵심만 3줄 요약]
    오직 아래 3줄 형태로만 출력하세요. 다른 서론/결론은 일절 작성하지 마세요.

    • **공기 상태:** (측정소 및 수치/상태 요약)
    • **활동 판정:** (산책/환기 가능 여부)
    • **주의 사항:** (핵심 주의사항 1가지)
    """

    # 2. Gemini 프롬프트 구성
    prompt = f"""
    당신은 친절하고 전문적인 대기질 및 호흡기/면역 건강 안내 AI 비서입니다.
    사용자 질문과 공공데이터 API로부터 수집된 실시간 대기질 데이터(미세먼지, 초미세먼지, 오존, 황사 영향 등)를 바탕으로 자연스럽고 명확하게 답변해 주세요.
    사용자가 입력한 환경정보에 따라 답변해 주세요. (예: 오산 미세먼지 -> 미세먼지 농도를 중점으로 안내, 시흥 오존농도 -> 오존 중점으로 안내)
    지역명만 써져 있는 경우에는 환경 정보를 묻는 의도로 생각해 주세요.

    [사용자 질문]
    "{user_input}"
    {profile_guide}

    [수집된 실시간 대기질 데이터 목록]
    {json.dumps(air_results, ensure_ascii=False, indent=2)}

    {style_instruction}

    [공통 필수 규칙]
    0. **다중지역:** 두 곳 이상 여러 곳에서 환경정보 값을 받았다면, 두 곳의 환경정보를 모두 표시해 주세요.
    1. **주요 대기질 항목 포함:** 요청된 지역의 미세먼지(PM10), 초미세먼지(PM2.5), 오존(O3) 수치 및 등급과 황사 영향도(`yellow_dust`)를 언급해 주세요.
    2. **오존(O3) 특화 안내:** 오존 수치가 '나쁨'(0.091ppm 이상) 이상일 경우, 가스형 독성 물질로 마스크로 차단되지 않음을 알리고 실외 활동 자제를 강조해 주세요.
    3. **측정소 정보 명시:** 어떤 측정소 데이터인지 밝혀 주세요.
    4. **질문 의도 확인:** 질문 내용이 대기질/환경정보 관련 질문이 아니라면 "잘못 입력하셨거나 환경질문이 아닙니다"라는 취지의 문장을 출력해 주세요.
    """.strip()

    try:
        result = call_gemini_api(prompt=prompt, output_type="text")

        if isinstance(result, str):
            return result
        elif isinstance(result, dict) and "text" in result:
            return result["text"]
        else:
            print(f"❌ [2차 Gemini API 응답 에러]: {result}")
    except Exception as e:
        print(f"❌ [2차 Gemini API 예외 발생]: {e}")

    return "죄송합니다. 대기질 정보를 바탕으로 답변을 생성하는 중 오류가 발생했습니다."


# =====================================================================
# 🧪 파이프라인 대화형 실행 테스트
# =====================================================================
if __name__ == "__main__":
    LOCATION_KEY = st.secrets.get("AIR_PORTAL_LOCATION_KEY", "")
    AIR_KEY = st.secrets.get("AIR_PORTAL_KEY", "")

    # API 키 존재 여부 검증 및 CMD 출력
    if not LOCATION_KEY or not AIR_KEY:
        print("🚨 [설정 에러] .streamlit/secrets.toml 에 API 키가 설정되지 않았습니다!")
        print(f" - LOCATION_KEY: {'설정됨' if LOCATION_KEY else '❌ 누락'}")
        print(f" - AIR_KEY: {'설정됨' if AIR_KEY else '❌ 누락'}")

    locations_df, h2b_map, valid_bjd_map = locations_upload()

    print("=" * 80)
    print("🚀 [대화형 파이프라인 테스트] 질문을 입력하세요. (종료: 'exit' 또는 'q')")
    print("=" * 80)

    test_cnt = 1
    key = True

    # 테스트용 즐겨찾기/프로필 설정 예시
    selected_location = "시흥시 정왕동"  # UI/즐겨찾기에서 넘어오는 위치값 예시
    user_profile = {
        'user_type': '일반 성인',
        'activity': '산책',
        'ai_style': '친절하고 세심한 설명'  # 또는 "전문 수치/데이터 중심 분석"
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

            # ✨ [핵심 적용] 즐겨찾기 선택 지역명 전처리 및 결합
            user_input = combine_user_input_with_location(raw_input_text, selected_location)
            print(f"📌 [최종 프롬프트 전달 문장]: {user_input}")

            # 1차 Gemini 호출
            gemini_res = process_user_request(user_input)
            is_query = gemini_res.get("is_location_query", False)
            location_sets = gemini_res.get("location_sets", [])

            print(f"  1️⃣ [1차 Gemini 추론] 추출된 행정구역: {location_sets}")

            if not is_query or not location_sets:
                print("  ⚠️ 환경/지명 질문이 아니거나 위치를 파악하지 못했습니다.")
                test_cnt += 1
                continue

            time.sleep(1.5)

            # 공공데이터 수집
            air_results = fetch_all_air_candidates(
                location_sets=location_sets,
                location_key=LOCATION_KEY,
                air_key=AIR_KEY,
                h2b_map=h2b_map,
                valid_bjd_map=valid_bjd_map
            )
            print(f"  2️⃣ [공공데이터 수집] 결과 데이터 {len(air_results)}건 준비 완료")

            # 2차 Gemini 호출
            final_answer = generate_final_response(user_input, air_results, user_profile)

            print("\n  3️⃣ [2차 Gemini] 최종 답변:")
            print("  " + "-" * 60)
            print(f"{final_answer}")
            print("  " + "-" * 60)

            test_cnt += 1
            time.sleep(1.5)

        except KeyboardInterrupt:
            print("\n\n👋 사용자 중단(Ctrl+C)으로 종료합니다.")
            key = False
            break
        except Exception as e:
            print(f"\n❌ [메인 루프 예외 발생]: {e}")
