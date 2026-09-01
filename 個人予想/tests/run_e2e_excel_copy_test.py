#!/usr/bin/env python3
"""実Excelコピーを使った1日分通しテスト（元ファイルは変更しない）。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
from common.constants import EXCEL_FILENAMES, SPORTS  # noqa: E402
from test_fixtures import (  # noqa: E402
    TEST_DATE,
    make_sandbox,
    seed_dummy_runtime,
    snapshot_tree,
)

SHEET = "202609"
ORIGINALS = {key: ROOT / "excel" / name for key, name in EXCEL_FILENAMES.items()}


def load_workflow():
    path = ROOT / "tools" / "workflow.py"
    spec = importlib.util.spec_from_file_location("personal_workflow", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_copies(sandbox: Path) -> dict[str, Path]:
    return {key: sandbox / "excel" / name for key, name in EXCEL_FILENAMES.items()}


def patch_workflow(workflow, copies: dict[str, Path], sandbox: Path) -> None:
    def test_workbooks(_base: Path) -> dict[str, Path]:
        return dict(copies)

    workflow.ensure_workbooks = test_workbooks  # type: ignore[method-assign]
    workflow.ROOT = sandbox


def snapshot_formulas(path: Path, sheet: str, rows: range, cols: range) -> dict[tuple[int, int], str]:
    wb = load_workbook(path, data_only=False)
    ws = wb[sheet]
    out: dict[tuple[int, int], str] = {}
    for r in rows:
        for c in cols:
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.startswith("="):
                out[(r, c)] = v
    wb.close()
    return out


def snapshot_merges_and_dv(path: Path, sheet: str) -> tuple[int, int]:
    wb = load_workbook(path)
    ws = wb[sheet]
    merges = len(list(ws.merged_cells.ranges))
    dvs = len(ws.data_validations.dataValidation)
    wb.close()
    return merges, dvs


def read_entry_rows(path: Path, start: int = 3, end: int = 7) -> list[dict]:
    wb = load_workbook(path, data_only=True)
    ws = wb[SHEET]
    rows = []
    for r in range(start, end + 1):
        rows.append({chr(64 + c): ws.cell(r, c).value for c in range(1, 15)})
    wb.close()
    return rows


def read_summary_pt(path: Path) -> dict[str, list]:
    wb = load_workbook(path, data_only=True)
    ws = wb[SHEET]
    data = {
        "row12_P-T": [ws.cell(12, c).value for c in range(16, 21)],
        "row13_P-T": [ws.cell(13, c).value for c in range(16, 21)],
        "row14_P-T": [ws.cell(14, c).value for c in range(16, 21)],
    }
    wb.close()
    return data


def has_formula_errors(path: Path) -> bool:
    wb = load_workbook(path)
    ws = wb[SHEET]
    for row in ws.iter_rows(min_row=1, max_row=20, min_col=1, max_col=20):
        for cell in row:
            if cell.data_type == "e":
                wb.close()
                return True
    wb.close()
    return False


def main() -> int:
    import tempfile

    workflow = load_workflow()
    orig_root = workflow.ROOT
    production_before = snapshot_tree(ROOT / "data")
    frozen_report = ROOT / "tests" / "e2e_excel_test_report.json"
    frozen_report_before = frozen_report.read_bytes() if frozen_report.exists() else None
    original_hashes = {k: file_hash(p) for k, p in ORIGINALS.items()}
    sandbox = make_sandbox(ROOT, copy_excel=True)
    verify = Path(tempfile.mkdtemp(prefix="personal-e2e-verify-"))
    seed_dummy_runtime(verify)
    verify_before = snapshot_tree(verify)
    failed: list[str] = []
    report: dict[str, object] = {
        "date": TEST_DATE,
        "data_mode": "テストデータ使用",
        "note": "一時ディレクトリで allow_sample=True。本番 data は削除も変更もしない。",
        "checks": [],
        "sports": list(SPORTS),
    }
    try:
        copies = setup_copies(sandbox)
        patch_workflow(workflow, copies, sandbox)

        predict_check: dict[str, object] = {"step": "predict-all"}
        apply_check: dict[str, object] = {"step": "apply-results"}
        for sport in SPORTS:
            entry = copies[f"{sport}_entry"]
            summary = copies[f"{sport}_summary"]
            before = read_entry_rows(entry)
            formula_before = snapshot_formulas(summary, SHEET, range(12, 15), range(2, 16))
            merge_before = snapshot_merges_and_dv(entry, SHEET)

            pred = workflow.run_predict(
                sport,
                TEST_DATE,
                force=True,
                sync_drive=False,
                allow_sample=True,
                try_auto=False,
            )
            report[f"predict_{sport}_head"] = pred.splitlines()[:5]
            after = read_entry_rows(entry)
            merge_after = snapshot_merges_and_dv(entry, SHEET)
            ab_ok = all(
                after[i]["A"] == before[i]["A"] and after[i]["B"] == before[i]["B"]
                for i in range(5)
            )
            filled = sum(
                1 for i in range(5) if any(after[i][c] not in (None, "") for c in "CDEFGHIJK")
            )
            predict_check[f"{sport}_AB_preserved"] = ab_ok
            predict_check[f"{sport}_filled_rows"] = filled
            predict_check[f"{sport}_max5"] = filled <= 5
            predict_check[f"{sport}_merges_unchanged"] = merge_before[0] == merge_after[0]
            predict_check[f"{sport}_rows_3_7"] = after
            if not ab_ok:
                failed.append(f"{sport} AB changed")
            if filled < 1:
                failed.append(f"{sport} no predictions written")
            if filled > 5:
                failed.append(f"{sport} more than 5 races")

            workflow.apply_results_from_file(
                sport,
                TEST_DATE,
                ROOT / "examples" / f"{sport}_results.sample.json",
                sync_drive=False,
            )
            after_res = read_entry_rows(entry)
            summary_pt = read_summary_pt(summary)
            formula_after = snapshot_formulas(summary, SHEET, range(12, 15), range(2, 16))
            ln = [{k: after_res[i][k] for k in "LMN"} for i in range(min(3, filled))]
            apply_check[f"{sport}_L-N_sample"] = ln
            apply_check[f"{sport}_summary_PT"] = summary_pt
            apply_check[f"{sport}_B-O_formulas_unchanged"] = formula_before == formula_after
            apply_check[f"{sport}_formula_errors"] = has_formula_errors(summary)
            if any(not row.get("L") for row in ln):
                failed.append(f"{sport} results L empty")
            statuses = summary_pt.get("row12_P-T") or []
            if not any(s in {"的中", "ハズレ"} for s in statuses):
                failed.append(f"{sport} summary P-T not updated")
            if formula_before != formula_after:
                failed.append(f"{sport} summary formulas changed")
            if apply_check[f"{sport}_formula_errors"]:
                failed.append(f"{sport} formula errors")

            review_state = workflow.load_json(workflow.state_path(sport))
            reviewed = [r for r in review_state.get("records", []) if r.get("review")]
            apply_check[f"{sport}_review_count"] = len(reviewed)
            if not reviewed:
                failed.append(f"{sport} review missing")

        report["checks"].append(predict_check)
        report["checks"].append(apply_check)

        dup_ok = True
        for sport in SPORTS:
            dup = workflow.run_predict(
                sport,
                TEST_DATE,
                force=False,
                sync_drive=False,
                allow_sample=True,
                try_auto=False,
            )
            if "二重登録防止" not in dup:
                dup_ok = False
                failed.append(f"{sport} idempotency failed")
        report["checks"].append({"step": "idempotency", "all_blocked": dup_ok})

        unchanged = all(file_hash(ORIGINALS[k]) == original_hashes[k] for k in ORIGINALS)
        report["checks"].append({"step": "isolation", "originals_unchanged": unchanged})
        if not unchanged:
            failed.append("originals modified")

        src = (ROOT / "tools" / "workflow.py").read_text()
        chatwork = "send_chatwork" in src or "chatwork_request" in src
        report["checks"].append({"step": "chatwork", "workflow_calls_chatwork": chatwork})
        if chatwork:
            failed.append("chatwork referenced")

        jra_state = workflow.load_json(workflow.state_path("jra"))
        nar_state = workflow.load_json(workflow.state_path("nar"))
        jra_venues = {r.get("venue") for r in jra_state.get("records", []) if r.get("tickets")}
        nar_venues = {r.get("venue") for r in nar_state.get("records", []) if r.get("tickets")}
        separated = bool(jra_venues) and bool(nar_venues) and not (jra_venues & nar_venues)
        report["checks"].append(
            {
                "step": "learning_separated",
                "jra_venues": sorted(jra_venues),
                "nar_venues": sorted(nar_venues),
                "no_overlap": separated,
            }
        )
        if not separated:
            failed.append("jra/nar learning mixed")
    finally:
        workflow.ROOT = orig_root
        shutil.rmtree(sandbox, ignore_errors=True)

    production_after = snapshot_tree(ROOT / "data")
    verify_after = snapshot_tree(verify)
    frozen_report_after = frozen_report.read_bytes() if frozen_report.exists() else None
    report["production_data_snapshot_match"] = production_before == production_after
    report["dummy_verify_root_snapshot_match"] = verify_before == verify_after
    report["legacy_report_file_untouched"] = frozen_report_before == frozen_report_after
    report["production_data_files"] = sorted(production_before)
    report["dummy_verify_files"] = sorted(verify_before)
    if production_before != production_after:
        failed.append("production data files changed")
    if verify_before != verify_after:
        failed.append("dummy verification root changed")
    if frozen_report_before != frozen_report_after:
        failed.append("legacy e2e report file changed")
    shutil.rmtree(verify, ignore_errors=True)

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if failed:
        print("FAILED:", failed, file=sys.stderr)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
