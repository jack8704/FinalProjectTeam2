import pandas as pd
from pathlib import Path

for f in sorted(Path("data/raw/seoul_report").glob("*.csv")):
    for enc in ["utf-8-sig", "cp949"]:
        try:
            d = pd.read_csv(f, encoding=enc, nrows=5)
            break
        except UnicodeDecodeError:
            continue
    print(f.name, "→", list(d.columns))
print(d.head())
