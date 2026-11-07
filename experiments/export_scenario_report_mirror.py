"""Render a scenario preview into the table layout used by the thesis draft.

The output mirrors the Chapter 4 tables (Bảng 19, 20, 22, 23 and mục 4.6) so the
declared-assumption scenario can be compared side by side with the draft's
numbers.  Tables that the scenario does not model are emitted with explicit
"chưa mô phỏng" markers rather than plausible-looking placeholders.

Everything is derived from ``scenario_<n>_seed_<seed>.csv`` / ``_summary.json``.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denom
    spread = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - spread), min(1.0, centre + spread)


def pct(value: float, digits: int = 1) -> str:
    """Vietnamese-style percent: comma decimal separator."""
    return f"{value * 100:.{digits}f}".replace(".", ",") + "%"


def num(value: float, digits: int = 3) -> str:
    """Vietnamese-style decimal: comma separator."""
    return f"{value:.{digits}f}".replace(".", ",")


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def at(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        low, high = math.floor(position), math.ceil(position)
        if low == high:
            return ordered[int(position)]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "min": ordered[0],
        "q1": at(0.25),
        "median": at(0.50),
        "q3": at(0.75),
        "max": ordered[-1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "scenario_preview_3000")
    parser.add_argument("--stem", default="scenario_3000_seed_32849123")
    parser.add_argument("--stability-source", type=Path, default=None,
                        help="Optional stability CSV with a 'verdict_consistent' column.")
    args = parser.parse_args()

    summary = json.loads((args.source / f"{args.stem}_summary.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((args.source / f"{args.stem}.csv").open(encoding="utf-8", newline="")))

    m = summary["metrics_on_scored_samples"]
    counts = summary["counts"]
    samples = summary["samples_requested"]
    assumptions = summary["assumptions"]
    runtime_assumptions = summary["runtime_assumptions"]

    scored = m["scored"]
    tp, fp, tn, fn = m["true_positives"], m["false_positives"], m["true_negatives"], m["false_negatives"]

    fpr_lo, fpr_hi = wilson(fp, fp + tn)
    rec_lo, rec_hi = wilson(tp, tp + fn)

    # Refusal and error denominators mirror the draft's Bảng 19 rows.
    mal_total = counts["true_positives"] + counts["false_negatives"] + counts["refused_malicious"]
    ben_total = counts["true_negatives"] + counts["false_positives"] + counts["refused_benign"]
    refused_total = counts["refused_malicious"] + counts["refused_benign"]

    runtimes = [float(r["projected_runtime_min"]) for r in rows]
    rt = percentiles(runtimes)

    stage_keys = [k for k in rows[0] if k.startswith("projected_") and k != "projected_runtime_min"]
    stage_totals = {k: sum(float(r[k]) for r in rows) for k in stage_keys}
    grand = sum(stage_totals.values())

    lines: list[str] = []
    add = lines.append

    add("# Bản đối chiếu mô phỏng theo cấu trúc báo cáo")
    add("")
    add("> **CẢNH BÁO: ĐÂY LÀ SỐ LIỆU GIẢ ĐỊNH, KHÔNG PHẢI SỐ ĐO.**")
    add(">")
    add(f"> Seed `{summary['seed']}`; `{thousands(samples)}` mẫu mô phỏng.")
    add("> Mọi con số dưới đây là hệ quả của các giả định khai báo ở mục cuối file,")
    add("> không phải kết quả đo từ pipeline. Không đưa vào mục kết quả thực nghiệm.")
    add("")
    add("Mục đích: đối chiếu định lượng giữa bản mô phỏng và các số liệu đang có")
    add("trong bản thảo, để kiểm tra mô phỏng có nằm ở vùng hợp lý hay không.")
    add("")
    add("---")
    add("")

    # ---- Bảng 19 -------------------------------------------------------------
    add("## Bảng 19 (mô phỏng): Ma trận nhầm lẫn và các chỉ số ở cấu hình đầy đủ")
    add("")
    add("| Chỉ số | Giá trị mô phỏng | Ghi chú |")
    add("| --- | --- | --- |")
    add(f"| TP, độc hại kết luận độc hại | {tp} | Ma trận nhầm lẫn |")
    add(f"| FN, độc hại kết luận lành tính | {fn} | |")
    add(f"| FP, lành tính kết luận độc hại | {fp} | |")
    add(f"| TN, lành tính kết luận lành tính | {tn} | |")
    add(f"| Số mẫu được chấm điểm | {thousands(scored)} | trên {thousands(samples)} mẫu |")
    add(f"| Precision | {num(m['precision'])} | |")
    add(f"| Recall | {num(m['recall'])} | Đọc kèm dòng tỉ lệ từ chối |")
    add(f"| F1-score | {num(m['f1'])} | |")
    add(f"| Accuracy | {num(m['accuracy'])} | |")
    add(f"| Tỉ lệ dương tính giả | {pct(m['false_positive_rate'])} "
        f"(Wilson 95%: {pct(fpr_lo)} – {pct(fpr_hi)}) | Kèm khoảng tin cậy 95% |")
    add(f"| Tỉ lệ lỗi | {pct(ratio(refused_total, samples))} | |")
    add(f"| Tỉ lệ từ chối, mẫu độc hại | {pct(ratio(counts['refused_malicious'], mal_total))} | |")
    add(f"| Tỉ lệ từ chối, mẫu lành tính | {pct(ratio(counts['refused_benign'], ben_total))} | |")
    add("")
    add(f"Khoảng tin cậy Wilson 95% cho Recall: {pct(rec_lo)} – {pct(rec_hi)}.")
    add("")

    # ---- Bảng 20 -------------------------------------------------------------
    add("## Bảng 20 (mô phỏng): So sánh ba cấu hình về chất lượng phát hiện")
    add("")
    add("| Cấu hình | Precision | Recall | F1 | Tỉ lệ FP | Tỉ lệ không kết luận được |")
    add("| --- | --- | --- | --- | --- | --- |")
    add(f"| FULL | {num(m['precision'])} | {num(m['recall'])} | {num(m['f1'])} "
        f"| {pct(m['false_positive_rate'])} | {pct(ratio(refused_total, samples))} |")
    add("| A1, không phân tích tĩnh | — | — | — | — | — |")
    add("| A2, không phân tích động | — | — | — | — | — |")
    add("")
    add("> A1 và A2 **chưa được mô phỏng**. Cần khai báo giả định riêng cho từng cấu")
    add("> hình (mức suy giảm kỳ vọng khi bỏ một nguồn bằng chứng) rồi chạy lại script")
    add("> với tham số tương ứng. Không suy ra A1/A2 từ chênh lệch trong bản thảo, vì")
    add("> làm vậy chỉ tái tạo lại chính con số đang muốn kiểm tra.")
    add("")

    # ---- Bảng 21 -------------------------------------------------------------
    add("## Bảng 21 (chưa mô phỏng): So sánh theo cặp giữa hai lượt phân tích tĩnh")
    add("")
    add("| Chỉ số so sánh | Lượt một | Lượt hai | Chênh lệch trung vị |")
    add("| --- | --- | --- | --- |")
    add("| Số phát hiện được xác nhận | — | — | — |")
    add("| Số hàm nhập giải quyết được | — | — | — |")
    add("| Số chuỗi có ý nghĩa trích được | — | — | — |")
    add("| Số kỹ thuật ATT&CK ánh xạ được | — | — | — |")
    add("")
    add("> Bảng này đếm artifact tĩnh (hàm nhập, chuỗi, kỹ thuật ATT&CK) từ hai lượt")
    add("> phân tích trên cùng mẫu. Bản mô phỏng hiện tại chỉ sinh nhãn và runtime, không")
    add("> sinh nội dung artifact, nên không có gì để điền. Muốn mô phỏng cần bổ sung")
    add("> giả định về mức tăng bằng chứng sau khi có artifact khôi phục.")
    add("")

    # ---- Bảng 22 -------------------------------------------------------------
    add("## Bảng 22 (chưa mô phỏng): So sánh chi phí có và không có cache")
    add("")
    add("| Cấu hình | Token vào tính giá đầy đủ | Token đọc từ đệm | Chi phí quy đổi | Mức giảm |")
    add("| --- | --- | --- | --- | --- |")
    add("| FULL | — | — | — | - |")
    add("| A4, không cache | — | — | — | — |")
    add("")
    add("> Bản mô phỏng không sinh token hay chi phí, chỉ sinh runtime. Cần chạy một")
    add("> biến thể có giả định riêng về token và tỉ lệ cache.")
    add("")

    # ---- 4.6.1 ---------------------------------------------------------------
    add("## Mục 4.6.1 (mô phỏng): Phân bổ theo giai đoạn")
    add("")
    add("| Giai đoạn | Tỉ trọng trong bản mô phỏng |")
    add("| --- | --- |")
    for key, total in sorted(stage_totals.items(), key=lambda kv: -kv[1]):
        stage = key.replace("projected_", "")
        add(f"| {stage} | {pct(total / grand)} |")
    add("")
    add("> **Lưu ý quan trọng về vòng lặp logic.** Tỉ trọng giai đoạn ở đây là **input**,")
    add("> không phải output: script mô phỏng đã nhận thẳng tỉ trọng từ mục 4.6.1 của bản")
    add("> thảo rồi dùng nó để chia runtime. Vì vậy bảng này khớp với bản thảo **theo thiết")
    add("> kế**, không phải bằng chứng mô phỏng tái lập được số liệu. Nó chỉ xác nhận phép")
    add("> chia tỉ lệ chạy đúng.")
    add(">")
    add("> Ngoài ra có một điểm không nhất quán cần sửa: bản thảo dùng hai bộ tỉ trọng khác")
    add("> nhau cho cùng giai đoạn 05-dynamic — **26,8%** cho chi phí token (mục 4.6.1) và")
    add("> **42,3%** cho thời gian (mục 4.6.3). Bản mô phỏng này dùng bộ token, nên runtime")
    add("> chia theo token, và do đó **không** tái hiện được con số 42,3%.")
    add("")

    # ---- 4.6.3 ---------------------------------------------------------------
    add("## Mục 4.6.3 (mô phỏng): Thời gian thực thi")
    add("")
    add(f"Trên mỗi mẫu, thời gian thực thi có trung vị **{num(rt['median'], 1)} phút**, "
        f"tứ phân vị thứ nhất và thứ ba lần lượt là {num(rt['q1'], 1)} và {num(rt['q3'], 1)} phút, "
        f"nhỏ nhất {num(rt['min'], 1)} phút và lớn nhất {num(rt['max'], 1)} phút.")
    add("")
    add("| Chỉ số runtime | Giá trị mô phỏng (phút) |")
    add("| --- | --- |")
    add(f"| Trung vị | {num(rt['median'], 1)} |")
    add(f"| Tứ phân vị 1 | {num(rt['q1'], 1)} |")
    add(f"| Tứ phân vị 3 | {num(rt['q3'], 1)} |")
    add(f"| Nhỏ nhất | {num(rt['min'], 1)} |")
    add(f"| Lớn nhất | {num(rt['max'], 1)} |")
    add("")
    add(f"> Runtime được sinh trực tiếp từ giả định "
        f"`mean_runtime_min = {runtime_assumptions['mean_runtime_min']}` và "
        f"`runtime_sigma = {runtime_assumptions['runtime_sigma']}`. Phân bố log-normal")
    add("> là lựa chọn của người mô hình hoá, không phải phân bố quan sát được.")
    add("")

    # ---- 4.7 stability -------------------------------------------------------
    add("## Mục 4.7 (chưa mô phỏng): Độ ổn định của kết quả")
    add("")
    add("| Chỉ số | Giá trị mô phỏng |")
    add("| --- | --- |")
    add("| Tỉ lệ mẫu cho phán quyết đồng nhất qua 5 lần chạy | — |")
    add("| Hệ số biến thiên của token vào | — |")
    add("| Hệ số biến thiên của thời gian thực thi | — |")
    add("")
    add("> Cần chạy lặp: mô phỏng phải sinh nhiều lượt cho cùng một mẫu rồi đo tính nhất")
    add("> quán của phán quyết giữa các lượt. Bản hiện tại sinh mỗi mẫu một lần.")
    add("")

    # ---- Bảng 23 -------------------------------------------------------------
    add("## Bảng 23 (mô phỏng): Tổng hợp kết quả theo từng câu hỏi nghiên cứu")
    add("")
    add("| Mã | Câu hỏi | Kết quả chính | Kết luận |")
    add("| --- | --- | --- | --- |")
    add("| RQ1 | Đóng góp của phân tích động | — | Chưa mô phỏng (cần giả định cho A2) |")
    add("| RQ2 | Giá trị của vòng lặp khôi phục | — | Chưa mô phỏng (cần giả định cho Bảng 21) |")
    add("| RQ3 | Ảnh hưởng của mốc cắt tri thức | — | Chưa mô phỏng (cần nhãn theo thời gian) |")
    add(f"| RQ4 | Chi phí và khả năng tối ưu | Trung vị runtime {num(rt['median'], 1)} phút/mẫu "
        f"| Mô phỏng theo giả định khai báo; chưa có token/cache |")
    add("")

    # ---- comparison ----------------------------------------------------------
    add("---")
    add("")
    add("## Đối chiếu trực tiếp với bản thảo")
    add("")
    add("| Chỉ số | Bản thảo (Bảng 19) | Bản thảo (Bảng 20) | Mô phỏng | Chênh lệch so với Bảng 20 |")
    add("| --- | --- | --- | --- | --- |")
    draft19 = {"precision": 0.917, "recall": 0.917, "f1": 0.917}
    draft20 = {"precision": 0.881, "recall": 0.890, "f1": 0.885}
    for key, label in (("precision", "Precision"), ("recall", "Recall"), ("f1", "F1")):
        delta = m[key] - draft20[key]
        sign = "+" if delta >= 0 else ""
        add(f"| {label} | {num(draft19[key])} | {num(draft20[key])} | {num(m[key])} "
            f"| {sign}{num(delta, 3)} |")
    add(f"| Tỉ lệ FP | 6,7% | 6,7% | {pct(m['false_positive_rate'])} | "
        f"{'+' if m['false_positive_rate'] - 0.067 >= 0 else ''}{pct(m['false_positive_rate'] - 0.067)} |")
    add(f"| Từ chối, độc hại | 6,7% | 3,7% (chung) | "
        f"{pct(ratio(counts['refused_malicious'], mal_total))} | — |")
    add(f"| Từ chối, lành tính | 0,0% | 3,7% (chung) | "
        f"{pct(ratio(counts['refused_benign'], ben_total))} | — |")
    add("")
    add("**Đọc bảng này thế nào.** Bản thảo đang có hai bộ số cho cùng cấu hình FULL:")
    add("Bảng 19 ghi F1 = 0,917 còn Bảng 20 ghi F1 = 0,885. Cả hai đều nằm trong khoảng")
    add("75–90% hoặc sát trên nó. Bản mô phỏng cho F1 = " + num(m["f1"]) + ", thấp hơn cả hai.")
    add("")
    add("Điều đó có nghĩa là: **các con số trong bản thảo vốn đã không phải loại \"quá đẹp\"**")
    add("như lo ngại. Mức 1.0 chỉ xuất hiện ở dữ liệu thô `baseline_30` trong repo, nơi còn")
    add("6/30 mẫu dùng verdict tái sử dụng và còn rò rỉ nhãn qua đường dẫn. Bản thảo đã")
    add("không dùng mức đó.")
    add("")
    add("Nếu muốn mô phỏng khớp hơn với bản thảo, tăng `--sensitivity` lên khoảng 0,89–0,92")
    add("và giảm `--false-positive-rate` xuống khoảng 0,067. Nhưng cần nhớ: làm vậy là đang")
    add("**chỉnh giả định cho khớp kết luận**, không phải kiểm tra kết luận bằng mô phỏng.")
    add("")

    # ---- assumptions ---------------------------------------------------------
    add("---")
    add("")
    add("## Giả định đã khai báo (điền kèm khi trích dẫn)")
    add("")
    add("| Tham số | Giá trị | Ý nghĩa |")
    add("| --- | --- | --- |")
    notes = summary["assumption_notes"]
    for key, value in assumptions.items():
        add(f"| `{key}` | {value} | {notes.get(key, '')} |")
    add(f"| `mean_runtime_min` | {runtime_assumptions['mean_runtime_min']} | "
        f"{notes.get('mean_runtime_min', '')} |")
    add(f"| `runtime_sigma` | {runtime_assumptions['runtime_sigma']} | "
        f"{notes.get('runtime_sigma', '')} |")
    add("")
    add("Nguồn duy nhất lấy từ số đo thật: tỉ trọng 9 giai đoạn (mục 4.6.1 bản thảo).")
    add("Mọi tham số còn lại là giả định do người mô hình hoá chọn.")
    add("")
    add("## Tái lập")
    add("")
    add("```bash")
    add(f"py -3.11 experiments/simulate_scenario_preview.py --samples {samples} "
        f"--seed {summary['seed']} \\")
    add(f"  --sensitivity {assumptions['sensitivity']} "
        f"--false-positive-rate {assumptions['false_positive_rate']} \\")
    add(f"  --refusal-malicious {assumptions['refusal_malicious']} "
        f"--refusal-benign {assumptions['refusal_benign']} \\")
    add(f"  --mean-runtime-min {runtime_assumptions['mean_runtime_min']} "
        f"--runtime-sigma {runtime_assumptions['runtime_sigma']}")
    add("```")
    add("")

    out = args.source / f"report_mirror_{samples}_seed_{summary['seed']}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"F1 simulated={num(m['f1'])}  draft B19=0,917  draft B20=0,885")


if __name__ == "__main__":
    main()