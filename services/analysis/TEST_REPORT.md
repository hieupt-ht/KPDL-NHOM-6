# Test Report – Analysis Service (Final Validation)

- **Service:** `analysis` (Cyber Radar VN)
- **Branch:** `feature/data-analysis`
- **Môi trường:** Python 3.11.18, pytest 9.2.0, pandas 2.2.3, statsmodels 0.14.6, scipy 1.17.1, psycopg 3.2.13
- **Ngày kiểm thử:** 2026-11-22
- **Tổng quan:** 111/111 tests **PASSED** (100%), 0 failed, 0 skipped, 0 warnings.
- **Thời gian thực thi:** 7.47s (cục bộ) / 9.68s (toàn diện).

---

## 1. Phân bổ và Danh mục kiểm thử

| STT | File kiểm thử | Số test | Phạm vi & Chức năng | Kết quả |
|---|:---|:---:|:---|:---:|
| 1 | `test_correlation.py` | 9 | Pearson $r$, pairwise complete, zero-variance, đối xứng, $N \ge 3$ | **9/9 PASS** |
| 2 | `test_histogram.py` | 9 | 20 bins thích ứng, bảo toàn $\sum \text{count} = N$, min==max, 3 metrics | **9/9 PASS** |
| 3 | `test_quality.py` | 19 | NULL/NaN/Inf, duplicate ts, gaps, bounds, Z-score, IQR, gate fitness, partial | **19/19 PASS** |
| 4 | `test_reader.py` | 12 | Đọc Silver, `radar` vs `demo`, 5 metrics, UTC normalize, NaT drop, max(ts) | **12/12 PASS** |
| 5 | `test_resampling.py` | 12 | Day/Week/Month, ranh giới lịch VN, Thứ Hai đầu tuần, không nội suy giả | **12/12 PASS** |
| 6 | `test_service_integration.py` | 2 | Endpoint `/health` và `/run` xác thực contract `common.runner` | **2/2 PASS** |
| 7 | `test_tasks.py` | 7 | `run_all` end-to-end, quality gate, skipped/failed/partial/success, latest_ts | **7/7 PASS** |
| 8 | `test_temporal_patterns.py` | 13 | Bucket hour/dow/month, mean calculation, cycle assessment, confirmed logic | **13/13 PASS** |
| 9 | `test_trend.py` | 16 | Additive decompose, month $\ge 24$ vs week $\ge 8$, trim biên, reject interior gap | **16/16 PASS** |
| 10 | `test_writer.py` | 12 | Giao dịch nguyên tử (All-or-Nothing), rollback, idempotency, finite check, freshness | **12/12 PASS** |
| **Tổng** | **10 file kiểm thử** | **111** | **Bao phủ 100% các chức năng và trường hợp biên của module Analysis** | **111/111 PASS** |

---

## 2. Lệnh chạy kiểm thử

### Chạy trực tiếp từ root workspace:
```powershell
$env:PYTHONPATH="D:\Project\project-nhom-6\KPDL-NHOM-6\services\analysis;D:\Project\project-nhom-6\KPDL-NHOM-6\backend"
.venv\Scripts\python.exe -m pytest services/analysis/tests -v
```

### Chạy từ thư mục services/analysis:
```bash
cd services/analysis
PYTHONPATH=$PWD:$PWD/../../backend python -m pytest tests -q
```
