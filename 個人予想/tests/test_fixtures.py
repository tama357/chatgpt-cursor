"""テスト用サンドボックス。本番の 個人予想/data/ には書かない。"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

SPORTS = ("jra", "nar", "kyotei")
TEST_DATE = "2026-09-01"
PRODUCTION_ROOT = Path(__file__).resolve().parents[1]


def production_race_json(root: Path, sport: str, target_date: str) -> Path:
    return root / "data" / "races" / sport / f"{target_date}.json"


def production_result_json(root: Path, sport: str, target_date: str) -> Path:
    return root / "data" / "results" / sport / f"{target_date}.json"


def is_under_production_data(path: Path) -> bool:
    prod = (PRODUCTION_ROOT / "data").resolve()
    try:
        path.resolve().relative_to(prod)
        return True
    except ValueError:
        return False


def cleanup_production_runtime_files(
    root: Path = PRODUCTION_ROOT, target_date: str = TEST_DATE
) -> None:
    """テストが本番 data に残したレースJSON・結果JSON・state を削除する。"""
    for sport in SPORTS:
        for path in (
            production_race_json(root, sport, target_date),
            production_result_json(root, sport, target_date),
            root / "data" / sport / "state.json",
            root / "data" / sport / "learning_report.json",
        ):
            if path.exists():
                path.unlink()
    for leftover_dir in (
        root / "data" / "_e2e_test",
        root / "excel" / "_e2e_test",
    ):
        if leftover_dir.exists():
            shutil.rmtree(leftover_dir)


def leftover_production_race_paths(
    root: Path = PRODUCTION_ROOT, target_date: str = TEST_DATE
) -> list[Path]:
    return [
        p
        for sport in SPORTS
        if (p := production_race_json(root, sport, target_date)).exists()
    ]


def make_sandbox(src_root: Path, *, copy_excel: bool = True) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="personal-predict-test-"))
    (tmp / "data").mkdir()
    (tmp / "examples").symlink_to(src_root / "examples", target_is_directory=True)
    (tmp / "config").symlink_to(src_root / "config", target_is_directory=True)
    if copy_excel:
        shutil.copytree(
            src_root / "excel",
            tmp / "excel",
            ignore=shutil.ignore_patterns("_e2e_test", ".drive"),
        )
    else:
        (tmp / "excel").mkdir()
    return tmp


def install_test_races(root: Path, sport: str, target_date: str) -> Path:
    """examples を root 配下へ置く。本番 data/ へは置けない。"""
    dest = root / "data" / "races" / sport / f"{target_date}.json"
    if is_under_production_data(dest):
        raise RuntimeError("テストデータは本番の 個人予想/data/ に置かないでください")
    src = PRODUCTION_ROOT / "examples" / f"{sport}_races.sample.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    data["source"] = "test_fixture"
    data["note"] = "テストデータ使用。本番の当日レースではない。"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
