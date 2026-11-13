import pandas as pd
from pathlib import Path

def load(path):
    if path.suffix in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    for enc in ["utf-8-sig", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue

for folder in Path("data/raw").iterdir():
    files = [f for f in folder.rglob("*") if f.suffix in [".csv", ".xlsx", ".xls"]]
    print(f"\n===== {folder.name}: 파일 {len(files)}개 =====")

    dfs = []
    for f in files:
        d = load(f)
        print(f"  {f.name}: {len(d)}행, 컬럼 {list(d.columns)[:6]}...")
        d["source_file"] = f.name
        dfs.append(d)

    df = pd.concat(dfs, ignore_index=True)
    print("합계 행 수:", len(df))
    print(df.head(3))
    for col in df.columns:
        if "단속방법" in col or "단속구분" in col:
            print(f"[{col}] 비율:\n", df[col].value_counts(normalize=True).round(3))
