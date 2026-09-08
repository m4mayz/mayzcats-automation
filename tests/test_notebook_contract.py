from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_colab_notebook_is_run_all_ready_and_contains_no_credentials() -> None:
    notebook_path = ROOT / "MayzCats_V1_Colab.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    for index, cell in enumerate(notebook["cells"], start=1):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"cell-{index}", "exec")
    code_cells = [cell for cell in notebook["cells"] if cell.get("cell_type") == "code"]
    assert all(cell.get("execution_count") is None for cell in code_cells)
    assert all(not cell.get("outputs") for cell in code_cells)

    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    assert notebook["nbformat"] == 4
    assert "drive.mount" in code
    assert "/content/drive/MyDrive/MayzCats-Automation" in code
    assert "https://github.com/m4mayz/mayzcats-automation.git" in code
    assert "PROJECT_SOURCE" not in code
    assert "DRIVE_ROOT / 'project'" not in code
    assert "harry0703/MoneyPrinterTurbo.git" not in code
    assert "RUNTIME_PROJECT / 'vendor' / 'MoneyPrinterTurbo'" in code
    assert "uv sync --frozen" in code
    assert "mayzcats.pipeline" in code
    assert "load_credentials" in code
    assert code.index("load_credentials") < code.index("mayzcats.pipeline")
    assert "RERENDER_ON_RESUME" in code
    assert "privacyStatus" not in code or '"private"' in code
    assert "sk-" not in code
    assert "ELEVENLABS_API_KEYS=" not in code

    assert (ROOT / "vendor" / "MoneyPrinterTurbo" / "cli.py").is_file()
    assert (ROOT / "vendor" / "MoneyPrinterTurbo" / "LICENSE").is_file()
    assert len(list((ROOT / "src" / "music").glob("*.mp3"))) == 29
