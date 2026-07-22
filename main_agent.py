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
                continue
                
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
    3. 지역명만 써져 있는 경우에는 환경 정보를 묻든 질문으로 취급해주세요.

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
def generate_final_response(user_input: str, air_results: list) -> str:
    prompt = f"""
    당신은 친절하고 전문적인 대기질 및 호흡기/면역 건강 안내 AI 비서입니다.
    사용자 질문과 공공데이터 API로부터 수집된 실시간 대기질 데이터(미세먼지, 초미세먼지, 오존, 황사 영향 등)를 바탕으로 자연스럽고 명확하게 답변해 주세요.
    사용자가 입력한 환경정보에 따라 답변해주세요. (예: 오산 미세먼지 -> 미세먼지 농도를 중점으로 알려준다, 시흥 오존농도 : 오존 중점으로 알려준다)
    지역명만 써져 있는 경우에는 환경 정보를 묻는 의도로 생각해주세요.

    [사용자 질문]
    "{user_input}"

    [수집된 실시간 대기질 데이터 목록]
    {json.dumps(air_results, ensure_ascii=False, indent=2)}

    [답변 작성 가이드]
    0. **다중지역**
       -두 곳 이상 여러 곳에서 환경정보 값을 {air_results}로 받았다면, 두 곳의 환경정보를 모두 표시해주세요. 
    1. **주요 대기질 항목 포함 (미세먼지, 초미세먼지, 오존, 황사):**
       - 요청된 지역의 **미세먼지(PM10)**, **초미세먼지(PM2.5)**, **오존(O3)** 수치 및 등급을 명확히 안내하세요.
       - **황사 영향도(`yellow_dust`)** 수치나 경고가 있을 경우 함께 언급하세요.
    2. **오존(O3) 특화 안내 (중요):**
       - 오존 수치가 '나쁨'(0.091ppm 이상) 이상일 경우: "오존은 가스형 독성 오염물질이라 KF94 마스크로도 걸러지지 않으므로, 햇빛이 강한 시간대 야외 활동 자체를 줄이는 것이 유일한 예방법"임을 알리고 천식 및 알레르기 환자의 실외 활동 자제를 강력 권고하세요.
    3. **측정소 정보 명시:**
       - 어떤 측정소에서 가져온 데이터인지 명시해 주세요.
    4. **맞춤형 행동 요령:**
       - 미세먼지/황사에 따른 마스크 착용 가이드 및 실내 환기 팁을 첨언하세요.
    5. **어조:** 
       - 친절하고 다정한 어조(~해요, ~입니다)를 사용하고 가독성 좋게 정돈된 문단이나 불렛포인트로 작성하세요.

    6. **분량:**
       - 5줄 이내로 작성하세요.

    7. **의도:**
       - 질문 내용이 환경정보를 물어보는 것 외의 내용으로 판단된다면, "잘못입력하셨습니다"라는 느낌의 문장 출력
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

    while key:
        try:
            user_input = input(f"\n[{test_cnt:02d}] 💬 질문 입력 >> ").strip()

            if user_input.lower() in ["exit", "q", "quit", "종료"]:
                print("\n👋 테스트를 종료합니다.")
                key = False
                break

            if not user_input:
                print("⚠️ 질문을 입력해 주세요.")
                continue

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
            final_answer = generate_final_response(user_input, air_results)

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