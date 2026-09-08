from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "MayzCats_V1_Colab.ipynb"


def main() -> int:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4:
        raise SystemExit("Notebook must use nbformat 4")
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"{NOTEBOOK.name}:cell-{index}", "exec")
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "code"
    )
    required = (
        "drive.mount",
        "/content/drive/MyDrive/MayzCats-Automation",
        "RUNTIME_PROJECT / 'vendor' / 'MoneyPrinterTurbo'",
        "uv sync --frozen",
        "mayzcats.preflight",
        "mayzcats.pipeline",
    )
    missing = [marker for marker in required if marker not in code]
    if missing:
        raise SystemExit("Notebook is missing required markers: " + ", ".join(missing))
    forbidden = ("ELEVENLABS_API_KEYS=", "OPENAI_API_KEY=", "TAVILY_API_KEY=", "sk-")
    leaked = [marker for marker in forbidden if marker in code]
    if leaked:
        raise SystemExit("Notebook contains a credential-shaped value: " + ", ".join(leaked))
    print(f"Notebook contract OK: {NOTEBOOK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
