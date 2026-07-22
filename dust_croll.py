import re
import urllib.parse
import requests
from bs4 import BeautifulSoup


def get_naver_weather_with_numbers(location_name: str) -> dict:
    """
    네이버 검색을 통해 [현재 온도, 미세먼지 수치, 초미세먼지 수치, 자외선 수치]를 
    상태(글자)와 수치(숫자/단위)로 나누어 파싱합니다.
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

        # -----------------------------------------------------------------
        # 🌡️ 1. 현재 온도 (수치만 추출)
        # -----------------------------------------------------------------
        temp_val = None
        temp_elem = soup.select_one(".temperature_text strong, .weather_graph .temperature_text strong")
        if temp_elem:
            temp_raw = temp_elem.get_text().replace("현재 온도", "").replace("°", "").strip()
            # 숫자/소수점만 추출
            match = re.search(r"[-+]?\d*\.\d+|\d+", temp_raw)
            if match:
                temp_val = float(match.group())

        # -----------------------------------------------------------------
        # 😷☀️ 2. 하단 카드 영역 (미세먼지, 초미세먼지, 자외선, 오존)
        # -----------------------------------------------------------------
        chart_items = soup.select(".today_chart_box .item_today, .item_today")

        metrics = {
            "미세먼지": {"status": "정보없음", "value": None, "unit": "㎍/㎥"},
            "초미세먼지": {"status": "정보없음", "value": None, "unit": "㎍/㎥"},
            "자외선": {"status": "정보없음", "value": None, "unit": "지수"},
            "오존": {"status": "정보없음", "value": None, "unit": "ppm"}
        }

        for item in chart_items:
            title_elem = item.select_one(".title, .item_title")
            # 네이버는 .txt 안에 '보통 35㎍/㎥' 형태로 들어있거나, .num / .value 태그에 수치가 분리되어 있음
            txt_elem = item.select_one(".txt, .item_txt, .value")

            if title_elem and txt_elem:
                title = title_elem.get_text().strip()
                full_text = txt_elem.get_text().strip()  # 예: "보통 35㎍/㎥" 또는 "높음 6"

                # 1. 수치(숫자) 추출
                num_match = re.search(r"\d+(\.\d+)?", full_text)
                num_val = float(num_match.group()) if num_match else None

                # 2. 상태(글자: 보통, 좋음, 높음 등) 추출
                status_text = re.sub(r"[\d\.\s㎍/㎥ppm]", "", full_text).strip()
                if not status_text:
                    status_text = full_text

                # 3. 매핑
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

        # -----------------------------------------------------------------
        # 3. 데이터 정리 및 LightGBM 입력용 수치 보정
        # (네이버에서 수치가 텍스트로만 제공될 경우를 대비한 안전 수치 생성)
        # -----------------------------------------------------------------
        pm10_num = metrics["미세먼지"]["value"]
        if pm10_num is None:
            # 상태 문자열 기반 추정 수치 (LightGBM 모델 입력용)
            status_map = {"좋음": 20, "보통": 45, "나쁨": 90, "매우나쁨": 160}
            pm10_num = status_map.get(metrics["미세먼지"]["status"], 45)

        pm25_num = metrics["초미세먼지"]["value"]
        if pm25_num is None:
            status_map = {"좋음": 10, "보통": 23, "나쁨": 55, "매우나쁨": 85}
            pm25_num = status_map.get(metrics["초미세먼지"]["status"], 23)

        uv_num = metrics["자외선"]["value"]

        return {
            "location": location_name,
            "temperature": temp_val,                     # 예: 18.5 (float)
            "pm10_num": pm10_num,                        # 예: 35 (float 또는 int)
            "pm10_status": metrics["미세먼지"]["status"],  # 예: "보통"
            "pm25_num": pm25_num,                        # 예: 18 (float 또는 int)
            "pm25_status": metrics["초미세먼지"]["status"],# 예: "좋음"
            "uv_num": uv_num,                            # 예: 6.0 (float) 또는 None
            "uv_status": metrics["자외선"]["status"],      # 예: "높음"
            "o3_status": metrics["오존"]["status"]
        }

    except Exception as e:
        print(f"❌ 수치 크롤링 실패: {e}")
        return None


# =====================================================================
# 🧪 테스트 실행
# =====================================================================
if __name__ == "__main__":
    target = "시흥시 정왕동"
    data = get_naver_weather_with_numbers(target)

    print("\n" + "="*50)
    print(f"📌 [{target}] 수치 포함 크롤링 결과")
    print("="*50)
    if data:
        print(f"🌡️ 현재 기온   : {data['temperature']} °C")
        print(f"😷 미세먼지   : {data['pm10_num']} ㎍/㎥ ({data['pm10_status']})")
        print(f"💨 초미세먼지 : {data['pm25_num']} ㎍/㎥ ({data['pm25_status']})")
        
        uv_str = f"{data['uv_num']} ({data['uv_status']})" if data['uv_num'] else f"{data['uv_status']}"
        print(f"☀️ 자외선 지수 : {uv_str}")
    print("="*50 + "\n")