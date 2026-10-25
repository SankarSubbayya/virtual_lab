"""Fetch the public METABRIC cohort from cBioPortal: `python -m virtual_lab.data`.

Writes data/metabric.csv (one row per patient with expression data) and data/metabric_dictionary.md.
Source: Curtis et al. Nature 2012; Pereira et al. Nat Commun 2016; Rueda et al. Nature 2019.
"""

import json
import urllib.request
from collections import defaultdict

import pandas as pd

from .config import DATA_CSV, DATA_DICT, DATA_DIR

API = "https://www.cbioportal.org/api"
STUDY = "brca_metabric"
CLINICAL = {
    "AGE_AT_DIAGNOSIS": "Age at diagnosis (years)",
    "ER_STATUS": "Estrogen receptor status (Positive/Negative)",
    "PR_STATUS": "Progesterone receptor status (Positive/Negative)",
    "HER2_STATUS": "HER2 status (Positive/Negative)",
    "CLAUDIN_SUBTYPE": "PAM50 + claudin-low molecular subtype",
    "TUMOR_STAGE": "Tumor stage (0-4)",
    "GRADE": "Histologic grade (1-3)",
    "TUMOR_SIZE": "Tumor size (mm)",
    "LYMPH_NODES_EXAMINED_POSITIVE": "Number of positive lymph nodes",
    "CHEMOTHERAPY": "Received chemotherapy (YES/NO)",
    "HORMONE_THERAPY": "Received hormone therapy (YES/NO)",
    "RADIO_THERAPY": "Received radiotherapy (YES/NO)",
    "OS_MONTHS": "Overall survival time (months)",
    "OS_STATUS": "Overall survival status (raw cBioPortal label)",
    "RFS_MONTHS": "Relapse-free survival time (months)",
    "RFS_STATUS": "Relapse-free status (raw cBioPortal label)",
}
GENES = {
    "CD8A": "CD8+ T cell marker", "CD8B": "CD8+ T cell marker", "CD3E": "T cell marker",
    "CD4": "CD4+ T cell marker", "GZMA": "cytotoxic granzyme A", "GZMB": "cytotoxic granzyme B",
    "PRF1": "perforin (cytotoxicity)", "IFNG": "interferon gamma", "CXCL9": "T cell chemokine",
    "CXCL10": "T cell chemokine", "CXCL13": "TLS / Tfh chemokine", "CD274": "PD-L1",
    "PDCD1": "PD-1", "CTLA4": "CTLA-4", "LAG3": "LAG-3", "FOXP3": "regulatory T cell marker",
    "CD68": "macrophage marker", "MKI67": "proliferation (Ki-67)",
}


def _call(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def fetch() -> pd.DataFrame:
    rows = defaultdict(dict)
    for kind in ("PATIENT", "SAMPLE"):
        for r in _call(f"/studies/{STUDY}/clinical-data?clinicalDataType={kind}&pageSize=100000"):
            if r["clinicalAttributeId"] in CLINICAL:
                rows[r["patientId"]][r["clinicalAttributeId"]] = r["value"]

    genes = _call("/genes/fetch?geneIdType=HUGO_GENE_SYMBOL", list(GENES))
    symbol = {g["entrezGeneId"]: g["hugoGeneSymbol"] for g in genes}
    expr = _call(
        f"/molecular-profiles/{STUDY}_mrna/molecular-data/fetch",
        {"sampleListId": f"{STUDY}_mrna", "entrezGeneIds": list(symbol)},
    )
    for d in expr:
        rows[d["patientId"]][symbol[d["entrezGeneId"]]] = round(d["value"], 3)

    df = pd.DataFrame.from_dict(rows, orient="index").rename_axis("PATIENT_ID").reset_index()
    df = df.dropna(subset=list(GENES), how="all")
    for col in ("AGE_AT_DIAGNOSIS", "TUMOR_STAGE", "GRADE", "TUMOR_SIZE", "LYMPH_NODES_EXAMINED_POSITIVE", "OS_MONTHS", "RFS_MONTHS"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["OS_EVENT"] = df["OS_STATUS"].str.startswith("1").astype("Int64")
    df["RFS_EVENT"] = df["RFS_STATUS"].str.startswith("1").astype("Int64")
    return df[["PATIENT_ID", *CLINICAL, "OS_EVENT", "RFS_EVENT", *GENES]]


def dictionary(df: pd.DataFrame) -> str:
    tnbc = (df.ER_STATUS == "Negative") & (df.PR_STATUS == "Negative") & (df.HER2_STATUS == "Negative")
    lines = [
        "# METABRIC breast cancer cohort (cBioPortal `brca_metabric`)",
        "",
        "Curtis et al. Nature 2012; Pereira et al. Nat Commun 2016; Rueda et al. Nature 2019. Public data.",
        f"File: `metabric.csv`, {len(df)} patients (one row each), all with mRNA expression.",
        f"Triple-negative (ER, PR and HER2 all Negative): {int(tnbc.sum())} patients, "
        f"{int(df.loc[tnbc, 'OS_EVENT'].sum())} deaths.",
        "Expression values are log2 microarray intensities (Illumina HT-12), not z-scores.",
        "",
        "| Column | Meaning | Non-missing | Example |",
        "|---|---|---|---|",
    ]
    meaning = {
        "PATIENT_ID": "Patient identifier",
        **CLINICAL,
        "OS_EVENT": "1 = died, 0 = alive at last follow-up (from OS_STATUS)",
        "RFS_EVENT": "1 = relapsed, 0 = not (from RFS_STATUS)",
        **{g: f"{d} — mRNA expression" for g, d in GENES.items()},
    }
    for col in df.columns:
        example = df[col].dropna().iloc[0] if df[col].notna().any() else ""
        lines.append(f"| `{col}` | {meaning.get(col, '')} | {df[col].notna().sum()} | {example} |")
    return "\n".join(lines) + "\n"


def main():
    DATA_DIR.mkdir(exist_ok=True)
    df = fetch()
    df.to_csv(DATA_CSV, index=False)
    DATA_DICT.write_text(dictionary(df))
    print(f"wrote {DATA_CSV} ({len(df)} patients, {DATA_CSV.stat().st_size // 1024} KB) and {DATA_DICT}")


if __name__ == "__main__":
    main()
