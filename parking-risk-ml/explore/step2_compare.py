import pandas as pd

seoul = pd.read_parquet("data/processed/seoul.parquet")
seoul = seoul.dropna(subset=["dt", "경도", "위도"])
s = seoul[(seoul["gu"] == "강남구") &
          (seoul["dt"] >= "2021-10-01") & (seoul["dt"] < "2024-03-14")]

g = pd.read_csv("data/raw/gangnam/서울특별시 강남구_주정차위반단속위치현황_20240320.csv",
                encoding="cp949", low_memory=False)
g["dt"] = pd.to_datetime(g["단속일시"], errors="coerce")

print("같은 기간 건수 → 서울:", len(s), "/ 강남파일:", len(g))

cnt = g["단속구분"].value_counts()
print("\n강남 단속구분별 건수:\n", cnt)
print("CCTV+PDA+주행형:", cnt.get("CCTV",0)+cnt.get("PDA",0)+cnt.get("주행형CCTV",0))
print("PDA+주행형:", cnt.get("PDA",0)+cnt.get("주행형CCTV",0))
print("CCTV만:", cnt.get("CCTV",0))

h = pd.DataFrame({
    "서울통합": s["dt"].dt.hour.value_counts(normalize=True).sort_index(),
    "강남_CCTV": g[g["단속구분"]=="CCTV"]["dt"].dt.hour.value_counts(normalize=True).sort_index(),
    "강남_PDA": g[g["단속구분"]=="PDA"]["dt"].dt.hour.value_counts(normalize=True).sort_index(),
}).fillna(0).round(3)
print("\n시간대별 비율:\n", h)
