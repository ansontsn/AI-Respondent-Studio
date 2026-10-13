from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = []
    for folder in ["survey_sim", "tests", "scripts", "examples", ".streamlit"]:
        files += [p for p in (ROOT / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [ROOT / name for name in ["app.py", "README.md", "ACCEPTANCE.md", "requirements.txt", "requirements-tested.txt",
              ".env.example", ".gitignore", "pytest.ini", "start.ps1", "start.bat", "啟動系統.bat", "install-browser.bat", "安裝瀏覽器.bat", "test.bat"]]
    files += [ROOT / "outputs" / "pytest-results.xml", ROOT / "outputs" / "ui" / "verification.json"]
    path = ROOT / "outputs" / "AI問卷自動填寫-原始碼.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files):
            if not p.exists():
                raise FileNotFoundError(p)
            z.write(p, Path("AI問卷自動填寫") / p.relative_to(ROOT))
    with zipfile.ZipFile(path) as z:
        if z.testzip():
            raise RuntimeError("ZIP integrity check failed")
        count = len(z.namelist())
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT / "outputs" / "source-package.json").write_text(json.dumps({"file": str(path), "files": count, "sha256": checksum,
        "excludes": [".venv", ".git", ".env", "data", ".tmp", "browser binaries"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Source package: {count} files; {path.stat().st_size} bytes; SHA256 {checksum}")


if __name__ == "__main__":
    main()
