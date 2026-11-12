"""시설 위치 DB: 정제된 CSV를 서버 시작 시 1번 읽어 메모리에 올리고, 주변 검색을 빠르게 처리"""
import os
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree                        # 위경도 공간 색인

R = 6371000                                                   # 지구 반지름 (m)
BASE = os.path.dirname(os.path.abspath(__file__))             # 이 파일이 있는 폴더 (= source)

class FacilityDB:
    def __init__(self, csv_path, name=""):
        self.name = name
        path = os.path.join(BASE, csv_path)                   # 실행 위치와 상관없이 source 기준 경로
        self.df = pd.read_csv(path, encoding="utf-8-sig")     # prepare_facilities.py가 만든 파일
        self.tree = BallTree(np.radians(self.df[["lat", "lon"]].values), metric="haversine")  # 색인 생성
        print(f"시설 DB 로드: {name} {len(self.df)}개")

    def nearby(self, lat, lon, radius_m):
        """(lat, lon) 반경 radius_m 안의 시설을 가까운 순으로 반환"""
        idx, dist = self.tree.query_radius(np.radians([[lat, lon]]), r=radius_m / R,
                                           return_distance=True, sort_results=True)
        rows = self.df.iloc[idx[0]].copy()                    # 찾은 행만 복사
        rows["dist_m"] = dist[0] * R                          # 라디안 → 미터
        return rows.to_dict("records")                        # [{"id","lat","lon","dist_m",…}, …]