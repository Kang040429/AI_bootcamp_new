import joblib
import pandas as pd
from fastmcp import FastMCP

# 1. MCP 서버 생성
mcp = FastMCP("PM10-Predictor")

# 2. 미리 저장해둔 LightGBM 모델 불러오기
model = joblib.load('lightgbm_pm10_model.pkl')

# 3. LLM이 호출할 도구(Tool) 정의
@mcp.tool()
def predict_pm10(
    region_scale: int,
    season_weight: float,
    so2: float,
    co: float,
    o3: float,
    no2: float
) -> float:
    """
    대기 오염물질 수치와 환경 지표를 바탕으로 미세먼지(PM10) 농도를 예측합니다.
    
    Args:
        region_scale: 지역 규모 (1: 소도시, 2: 중도시, 3: 대도시 등)
        season_weight: 계절 가중치 (여름/겨울=1.0, 봄/가을=0.0)
        so2: 아황산가스 농도 (ppm)
        co: 일산화탄소 농도 (ppm)
        o3: 오존 농도 (ppm)
        no2: 이산화질소 농도 (ppm)
    """
    # 입력 데이터를 모델 형식으로 변환
    input_data = pd.DataFrame([{
        '지역_규모': region_scale,
        '계절_가중치': season_weight,
        '아황산가스(SO2)': so2,
        '일산화탄소(CO)': co,
        '오존(O3)': o3,
        '이산화질소(NO2)': no2
    }])
    
    # 모델 예측 수행
    prediction = model.predict(input_data)[0]
    return float(round(prediction, 2))

if __name__ == "__main__":
    mcp.run()