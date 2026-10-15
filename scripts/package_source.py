"""Package the current source; exclude credentials, runtime data and old evidence."""
import argparse
import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", action="store_true", help="Build the V2 integrated source archive")
    args = parser.parse_args()
    folders = ("survey_sim", "tests", "scripts", "docs", "examples", ".streamlit")
    files = [p for folder in folders for p in (ROOT / folder).rglob("*")
             if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}
             and p.name != ".env"]
    files += [ROOT / name for name in ("app.py", "README.md", "ACCEPTANCE.md", "requirements.txt",
              "requirements-tested.txt", ".env.example", ".gitignore", ".gitattributes", "pytest.ini",
              "start.ps1", "start.bat", "啟動系統.bat", "install-browser.bat", "安裝瀏覽器.bat", "test.bat")]
    payloads = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in sorted(files)}
    assert all(not ({"data", ".git", ".venv", ".tmp", "outputs", "backups"} & set(Path(name).parts)) for name in payloads)
    assert all(not name.endswith((".sqlite3", ".db", ".log")) for name in payloads)
    manifest = {"snapshot_date": date.today().isoformat(), "files": len(payloads),
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}
    name = f"AI問卷自動填寫-V2整合版-{date.today().isoformat()}.zip" if args.v2 else "AI問卷自動填寫-原始碼.zip"
    output = ROOT / "outputs"
    output.mkdir(exist_ok=True)
    archive = output / name
    prefix = "AI問卷自動填寫/"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for filename, data in payloads.items():
            bundle.writestr(prefix + filename, data)
        bundle.writestr(prefix + "SOURCE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for filename, data in payloads.items():
            assert bundle.read(prefix + filename) == data == (ROOT / filename).read_bytes()
    result = {"file": str(archive), "files": len(payloads) + 1, "bytes": archive.stat().st_size,
              "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "excludes": [".env", "data", ".venv", ".git", ".tmp", "outputs", "browser binaries"]}
    (output / "source-package.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
