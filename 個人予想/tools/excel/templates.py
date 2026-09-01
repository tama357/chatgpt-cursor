from __future__ import annotations

from pathlib import Path

from common.constants import EXCEL_FILENAMES, MONTH_SHEETS
from excel.mapping import write_mapping_cache


def ensure_workbooks(base_dir: Path) -> dict[str, Path]:
    excel_dir = base_dir / "excel"
    files = {key: excel_dir / name for key, name in EXCEL_FILENAMES.items()}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Excelファイルが見つかりません。Drive実ファイルを excel/ に配置してください:\n"
            + "\n".join(missing)
        )
    for path in files.values():
        wb_sheets = __import__("openpyxl").load_workbook(path, read_only=True)
        for month in MONTH_SHEETS:
            if month not in wb_sheets.sheetnames:
                raise ValueError(f"{path.name} にシート {month} がありません")
        wb_sheets.close()
    return files


def init_excel(base_dir: Path) -> str:
    files = ensure_workbooks(base_dir)
    cache = write_mapping_cache(base_dir)
    lines = ["Excel実ファイルを確認しました（中央競馬・地方競馬・競艇）:", ""]
    for key, path in files.items():
        lines.append(f"- {key}: {path.name}")
    lines.append(f"- 列マッピング: {cache.name}")
    return "\n".join(lines)
