# METABRIC breast cancer cohort (cBioPortal `brca_metabric`)

Curtis et al. Nature 2012; Pereira et al. Nat Commun 2016; Rueda et al. Nature 2019. Public data.
File: `metabric.csv`, 1980 patients (one row each), all with mRNA expression.
Triple-negative (ER, PR and HER2 all Negative): 320 patients, 168 deaths.
Expression values are log2 microarray intensities (Illumina HT-12), not z-scores.

| Column | Meaning | Non-missing | Example |
|---|---|---|---|
| `PATIENT_ID` | Patient identifier | 1980 | MB-0000 |
| `AGE_AT_DIAGNOSIS` | Age at diagnosis (years) | 1980 | 75.65 |
| `ER_STATUS` | Estrogen receptor status (Positive/Negative) | 1980 | Positive |
| `PR_STATUS` | Progesterone receptor status (Positive/Negative) | 1980 | Negative |
| `HER2_STATUS` | HER2 status (Positive/Negative) | 1980 | Negative |
| `CLAUDIN_SUBTYPE` | PAM50 + claudin-low molecular subtype | 1980 | claudin-low |
| `TUMOR_STAGE` | Tumor stage (0-4) | 1466 | 2.0 |
| `GRADE` | Histologic grade (1-3) | 1892 | 3.0 |
| `TUMOR_SIZE` | Tumor size (mm) | 1954 | 22.0 |
| `LYMPH_NODES_EXAMINED_POSITIVE` | Number of positive lymph nodes | 1904 | 10.0 |
| `CHEMOTHERAPY` | Received chemotherapy (YES/NO) | 1980 | NO |
| `HORMONE_THERAPY` | Received hormone therapy (YES/NO) | 1980 | YES |
| `RADIO_THERAPY` | Received radiotherapy (YES/NO) | 1980 | YES |
| `OS_MONTHS` | Overall survival time (months) | 1980 | 140.5 |
| `OS_STATUS` | Overall survival status (raw cBioPortal label) | 1980 | 0:LIVING |
| `RFS_MONTHS` | Relapse-free survival time (months) | 1980 | 140.5 |
| `RFS_STATUS` | Relapse-free status (raw cBioPortal label) | 1979 | 0:Not Recurred |
| `OS_EVENT` | 1 = died, 0 = alive at last follow-up (from OS_STATUS) | 1980 | 0 |
| `RFS_EVENT` | 1 = relapsed, 0 = not (from RFS_STATUS) | 1979 | 0 |
| `CD8A` | CD8+ T cell marker — mRNA expression | 1980 | 6.439 |
| `CD8B` | CD8+ T cell marker — mRNA expression | 1980 | 5.429 |
| `CD3E` | T cell marker — mRNA expression | 1980 | 5.641 |
| `CD4` | CD4+ T cell marker — mRNA expression | 1980 | 6.004 |
| `GZMA` | cytotoxic granzyme A — mRNA expression | 1980 | 6.53 |
| `GZMB` | cytotoxic granzyme B — mRNA expression | 1980 | 6.445 |
| `PRF1` | perforin (cytotoxicity) — mRNA expression | 1980 | 6.194 |
| `IFNG` | interferon gamma — mRNA expression | 1980 | 5.351 |
| `CXCL9` | T cell chemokine — mRNA expression | 1980 | 6.381 |
| `CXCL10` | T cell chemokine — mRNA expression | 1980 | 7.543 |
| `CXCL13` | TLS / Tfh chemokine — mRNA expression | 1980 | 5.4 |
| `CD274` | PD-L1 — mRNA expression | 1980 | 5.142 |
| `PDCD1` | PD-1 — mRNA expression | 1980 | 5.495 |
| `CTLA4` | CTLA-4 — mRNA expression | 1980 | 5.964 |
| `LAG3` | LAG-3 — mRNA expression | 1980 | 6.12 |
| `FOXP3` | regulatory T cell marker — mRNA expression | 1980 | 5.381 |
| `CD68` | macrophage marker — mRNA expression | 1980 | 6.143 |
| `MKI67` | proliferation (Ki-67) — mRNA expression | 1980 | 5.494 |
