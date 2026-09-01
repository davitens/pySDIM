"""Download all groundwater piezometer (level) data for comarca Baix Empordà.

The target is the piezometry network (after_2007:0005:0011 — "Nivells
piezomètrics"); the comarca filter restricts it to the 46 stations located in
Baix Empordà. Every level series at those stations is downloaded.

Run:  python3 examples/download_piezometers_baix_emporda.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdim import SDIM

if __name__ == "__main__":
    aca = SDIM(delay=0.5)
    try:
        parsed = aca.get_data(
            water_type="levels",          # after_2007 groundwater piezometry
            comarcas=["Baix Empordà"],    # spatial filter -> ambit=comarques
            start="2006-01-01",
            end="2008-12-31",
        )
    finally:
        aca.close()

    df = parsed["quality"]
    if df.empty:
        print("No groundwater level data for comarca Baix Empordà in the period.")
        raise SystemExit(1)

    stations = df["station_code"].nunique()
    print(df[["date", "station_code", "mass_name", "variable", "value", "unit"]]
          .head(8).to_string(index=False))
    print(f"\n{len(df)} level readings | {stations} stations/masses "
          f"{df['mass_name'].nunique()} water bodies")
    print("Variable(s):", ", ".join(sorted(df["variable"].unique())))

    # Save a tidy CSV beside the example.
    out = Path(__file__).resolve().parent / "baix_emporda_piezometria.csv"
    df.to_csv(out, index=False)
    print(f"Saved -> {out}")
