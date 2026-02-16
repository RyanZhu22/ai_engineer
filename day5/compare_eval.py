import argparse
import csv
from pathlib import Path
from typing import Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two Day4 eval result CSV files (baseline vs candidate)."
    )
    parser.add_argument("--baseline", required=True, help="Baseline eval CSV path")
    parser.add_argument("--candidate", required=True, help="Candidate eval CSV path")
    parser.add_argument(
        "--output",
        default="comparison_report.md",
        help="Output markdown report path",
    )
    return parser.parse_args()


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def aggregate(rows: List[Dict[str, str]]) -> Dict[str, float]:
    total = len(rows)
    search_hits = sum(safe_int(r.get("search_hit_expected_doc", "")) for r in rows)
    ask_hits = sum(safe_int(r.get("ask_hit_expected_doc", "")) for r in rows)
    kw_sum = sum(safe_float(r.get("keyword_recall", "")) for r in rows)

    return {
        "total": float(total),
        "search_hit_rate": (search_hits / total) if total else 0.0,
        "ask_hit_rate": (ask_hits / total) if total else 0.0,
        "avg_keyword_recall": (kw_sum / total) if total else 0.0,
    }


def index_by_id(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for row in rows:
        row_id = row.get("id", "").strip()
        if row_id:
            result[row_id] = row
    return result


def calc_deltas(
    base_rows: List[Dict[str, str]], cand_rows: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    base_map = index_by_id(base_rows)
    cand_map = index_by_id(cand_rows)

    improved: List[Dict[str, str]] = []
    regressed: List[Dict[str, str]] = []
    unchanged: List[Dict[str, str]] = []

    common_ids = sorted(set(base_map.keys()) & set(cand_map.keys()), key=lambda x: int(x))
    for qid in common_ids:
        b = base_map[qid]
        c = cand_map[qid]
        b_kw = safe_float(b.get("keyword_recall", ""))
        c_kw = safe_float(c.get("keyword_recall", ""))
        delta = c_kw - b_kw

        item = {
            "id": qid,
            "query": c.get("query", ""),
            "baseline_kw": f"{b_kw:.3f}",
            "candidate_kw": f"{c_kw:.3f}",
            "delta_kw": f"{delta:+.3f}",
            "baseline_docs": b.get("ask_source_docs", ""),
            "candidate_docs": c.get("ask_source_docs", ""),
        }
        if delta > 1e-9:
            improved.append(item)
        elif delta < -1e-9:
            regressed.append(item)
        else:
            unchanged.append(item)

    return improved, regressed, unchanged


def render_report(
    baseline_path: Path,
    candidate_path: Path,
    base_metrics: Dict[str, float],
    cand_metrics: Dict[str, float],
    improved: List[Dict[str, str]],
    regressed: List[Dict[str, str]],
    unchanged: List[Dict[str, str]],
) -> str:
    def pct(v: float) -> str:
        return f"{v:.1%}"

    lines: List[str] = []
    lines.append("# Day5 Experiment Comparison Report")
    lines.append("")
    lines.append(f"- Baseline: `{baseline_path}`")
    lines.append(f"- Candidate: `{candidate_path}`")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Delta |")
    lines.append("|---|---:|---:|---:|")

    for key, label in [
        ("search_hit_rate", "Search hit@k"),
        ("ask_hit_rate", "Ask source hit@k"),
        ("avg_keyword_recall", "Avg keyword recall"),
    ]:
        b = base_metrics[key]
        c = cand_metrics[key]
        d = c - b
        lines.append(f"| {label} | {pct(b)} | {pct(c)} | {d:+.1%} |")

    lines.append("")
    lines.append("## Per-question Delta (keyword_recall)")
    lines.append("")
    lines.append(f"- Improved: {len(improved)}")
    lines.append(f"- Regressed: {len(regressed)}")
    lines.append(f"- Unchanged: {len(unchanged)}")
    lines.append("")

    def add_table(title: str, rows: List[Dict[str, str]]) -> None:
        lines.append(f"### {title}")
        lines.append("")
        if not rows:
            lines.append("None")
            lines.append("")
            return
        lines.append("| id | query | baseline | candidate | delta |")
        lines.append("|---:|---|---:|---:|---:|")
        for r in rows:
            lines.append(
                f"| {r['id']} | {r['query']} | {r['baseline_kw']} | {r['candidate_kw']} | {r['delta_kw']} |"
            )
        lines.append("")

    add_table("Improved", improved)
    add_table("Regressed", regressed)
    add_table("Unchanged", unchanged)

    lines.append("## Recommendation")
    lines.append("")
    lines.append("- If `avg_keyword_recall` improved and regressions are limited, keep this change.")
    lines.append("- Review regressed questions and inspect chunk/source differences before finalizing.")
    lines.append("- Continue with one-variable-at-a-time experiments for reliable iteration.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)
    output_path = Path(args.output)

    if not baseline_path.exists():
        raise SystemExit(f"Baseline CSV not found: {baseline_path}")
    if not candidate_path.exists():
        raise SystemExit(f"Candidate CSV not found: {candidate_path}")

    base_rows = read_csv_rows(baseline_path)
    cand_rows = read_csv_rows(candidate_path)
    if not base_rows or not cand_rows:
        raise SystemExit("One of the CSV files is empty")

    base_metrics = aggregate(base_rows)
    cand_metrics = aggregate(cand_rows)
    improved, regressed, unchanged = calc_deltas(base_rows, cand_rows)

    report = render_report(
        baseline_path,
        candidate_path,
        base_metrics,
        cand_metrics,
        improved,
        regressed,
        unchanged,
    )
    output_path.write_text(report, encoding="utf-8")

    print("=== Comparison Complete ===")
    print(f"Baseline : {baseline_path}")
    print(f"Candidate: {candidate_path}")
    print(f"Report   : {output_path}")


if __name__ == "__main__":
    main()
