import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Day7 quality summary reports.")
    parser.add_argument("--baseline", required=True, help="Baseline summary json path")
    parser.add_argument("--candidate", required=True, help="Candidate summary json path")
    parser.add_argument("--output", default="reports/quality_comparison.md", help="Output markdown file")
    return parser.parse_args()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float) -> str:
    return f"{value:.1%}"


def render_table(base: Dict[str, Any], cand: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    lines.append("| Metric | Baseline | Candidate | Delta |")
    lines.append("|---|---:|---:|---:|")
    for key, label in [
        ("http_success_rate", "HTTP success rate"),
        ("format_ok_rate", "Format OK rate"),
        ("citation_compliance_rate", "Citation compliance rate"),
        ("expected_doc_cited_rate", "Expected doc cited rate"),
        ("avg_keyword_recall", "Avg keyword recall"),
    ]:
        b = float(base.get(key, 0.0))
        c = float(cand.get(key, 0.0))
        lines.append(f"| {label} | {pct(b)} | {pct(c)} | {c - b:+.1%} |")

    b_lat = float(base.get("avg_latency_ms", 0.0))
    c_lat = float(cand.get("avg_latency_ms", 0.0))
    lines.append(f"| Avg latency (ms) | {b_lat:.2f} | {c_lat:.2f} | {c_lat - b_lat:+.2f} |")
    return lines


def recommendation(base: Dict[str, Any], cand: Dict[str, Any]) -> str:
    base_success = float(base.get("http_success_rate", 0.0))
    cand_success = float(cand.get("http_success_rate", 0.0))
    base_format = float(base.get("format_ok_rate", 0.0))
    cand_format = float(cand.get("format_ok_rate", 0.0))
    base_cite = float(base.get("citation_compliance_rate", 0.0))
    cand_cite = float(cand.get("citation_compliance_rate", 0.0))
    base_kw = float(base.get("avg_keyword_recall", 0.0))
    cand_kw = float(cand.get("avg_keyword_recall", 0.0))

    if cand_success < base_success:
        return "Do not keep candidate: HTTP success rate regressed."
    if cand_format < base_format:
        return "Do not keep candidate: format compliance regressed."
    if cand_cite < base_cite:
        return "Do not keep candidate: citation compliance regressed."
    if cand_kw >= base_kw:
        return "Keep candidate: quality metrics improved or held with better keyword recall."
    return "Candidate is acceptable on structure/citation but keyword recall regressed; review detail CSV."


def main() -> None:
    args = parse_args()
    base_path = Path(args.baseline)
    cand_path = Path(args.candidate)
    out_path = Path(args.output)

    if not base_path.exists():
        raise SystemExit(f"Baseline summary not found: {base_path}")
    if not cand_path.exists():
        raise SystemExit(f"Candidate summary not found: {cand_path}")

    base = read_json(base_path)
    cand = read_json(cand_path)

    lines: List[str] = []
    lines.append("# Day7 Prompt Quality Comparison")
    lines.append("")
    lines.append(f"- Baseline: `{base_path}`")
    lines.append(f"- Candidate: `{cand_path}`")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.extend(render_table(base, cand))
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(f"- {recommendation(base, cand)}")
    lines.append("")
    lines.append("## Detail Files")
    lines.append("")
    lines.append(f"- Baseline detail: `{base.get('detail_csv', '')}`")
    lines.append(f"- Candidate detail: `{cand.get('detail_csv', '')}`")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    print("=== Day7 Quality Comparison Complete ===")
    print(f"Baseline : {base_path}")
    print(f"Candidate: {cand_path}")
    print(f"Report   : {out_path}")


if __name__ == "__main__":
    main()
