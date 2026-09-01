"""テスト用サンドボックス。本番の 個人予想/data/ には書かない・消さない。"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

SPORTS = ("jra", "nar", "kyotei")
TEST_DATE = "2026-09-01"
PRODUCTION_ROOT = Path(__file__).resolve().parents[1]


def is_under_production_data(path: Path) -> bool:
    prod = (PRODUCTION_ROOT / "data").resolve()
    try:
        path.resolve().relative_to(prod)
        return True
    except ValueError:
        return False


def snapshot_tree(
    root: Path, *, skip_dir_names: frozenset[str] | tuple[str, ...] = ()
) -> dict[str, dict[str, int | str]]:
    """root 配下の全ファイルを相対パス → size/sha256 で記録する。削除はしない。"""
    if not root.exists():
        return {}
    skip = frozenset(skip_dir_names)
    out: dict[str, dict[str, int | str]] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel_path = path.relative_to(root)
        if any(part in skip for part in rel_path.parts):
            continue
        data = path.read_bytes()
        rel = rel_path.as_posix()
        out[rel] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def write_canonical_states(root: Path, *, start_date: str) -> None:
    """テスト用ルートへ正規stateを置く。本番 data には使わない。"""
    if is_under_production_data(root / "data"):
        raise RuntimeError("テスト用 state は本番の 個人予想/data/ に置かないでください")
    for sport in SPORTS:
        sport_dir = root / "data" / sport
        sport_dir.mkdir(parents=True, exist_ok=True)
        (sport_dir / "state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "sport": sport,
                    "start_date": start_date,
                    "timezone": "Asia/Tokyo",
                    "records": [],
                    "processed": {},
                    "fetch_failures": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def seed_dummy_runtime(root: Path, *, target_date: str = TEST_DATE) -> None:
    """検証用ルートへダミーの state / 学習 / レース / 結果を置く。本番 data には使わない。"""
    if is_under_production_data(root / "data"):
        raise RuntimeError("ダミーデータは本番の 個人予想/data/ に置かないでください")
    data_root = root / "data"
    for sport in SPORTS:
        sport_dir = data_root / sport
        sport_dir.mkdir(parents=True, exist_ok=True)
        (sport_dir / "state.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "sport": sport,
                    "start_date": target_date,
                    "timezone": "Asia/Tokyo",
                    "records": [{"marker": f"keep-{sport}", "tickets": ["1-2-3"]}],
                    "processed": {},
                    "fetch_failures": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (sport_dir / "learning_report.json").write_text(
            json.dumps({"sport": sport, "marker": f"learn-{sport}"}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        source = {
            "jra": "netkeiba-jra",
            "nar": "netkeiba-nar",
            "kyotei": "boatrace.jp",
        }[sport]
        race_path = data_root / "races" / sport / f"{target_date}.json"
        race_path.parent.mkdir(parents=True, exist_ok=True)
        race_path.write_text(
            json.dumps(
                {
                    "date": target_date,
                    "source": source,
                    "races": [{"venue": "本番会場", "race": 1, "marker": f"official-{sport}"}],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result_path = data_root / "results" / sport / f"{target_date}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "date": target_date,
                    "source": "official",
                    "results": [{"marker": f"result-{sport}"}],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    keiba = data_root / "keiba"
    keiba.mkdir(parents=True, exist_ok=True)
    (keiba / "state.json").write_text(
        json.dumps({"sport": "keiba", "marker": "keep-keiba"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _link_or_copy_dir(src: Path, dest: Path) -> None:
    try:
        dest.symlink_to(src, target_is_directory=True)
    except OSError:
        shutil.copytree(src, dest)


def make_sandbox(src_root: Path, *, copy_excel: bool = True) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="personal-predict-test-"))
    (tmp / "data").mkdir()
    _link_or_copy_dir(src_root / "examples", tmp / "examples")
    _link_or_copy_dir(src_root / "config", tmp / "config")
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


def write_leftover_sample(
    root: Path, sport: str, source: str, venue: str, target_date: str = TEST_DATE
) -> Path:
    dest = root / "data" / "races" / sport / f"{target_date}.json"
    if is_under_production_data(dest):
        raise RuntimeError("テストの残りJSONも本番 data/ に置かないでください")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(
            {
                "source": source,
                "races": [{"venue": venue, "race": 11, "entries": [{"number": 1}]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return dest


class ProductionDataGuardMixin:
    """本番 個人予想/data/ の一覧・サイズ・ハッシュがテスト前後で一致することを確認する。"""

    _production_data_snapshot: dict[str, dict[str, int | str]]

    def setUp(self) -> None:
        self._production_data_snapshot = snapshot_tree(PRODUCTION_ROOT / "data")
        self._production_excel_snapshot = snapshot_tree(
            PRODUCTION_ROOT / "excel", skip_dir_names=frozenset({"_e2e_test"})
        )
        self.addCleanup(self._assert_production_data_untouched)
        super().setUp()

    def _assert_production_data_untouched(self) -> None:
        after_data = snapshot_tree(PRODUCTION_ROOT / "data")
        after_excel = snapshot_tree(
            PRODUCTION_ROOT / "excel", skip_dir_names=frozenset({"_e2e_test"})
        )
        if after_data != self._production_data_snapshot:
            raise AssertionError(
                "本番 個人予想/data/ がテスト中に変更されました: "
                f"before={self._production_data_snapshot} after={after_data}"
            )
        if after_excel != self._production_excel_snapshot:
            raise AssertionError(
                "本番 個人予想/excel/ がテスト中に変更されました: "
                f"before={self._production_excel_snapshot} after={after_excel}"
            )
