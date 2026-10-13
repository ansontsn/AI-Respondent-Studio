import os
import subprocess
import sys
import urllib.request
import webbrowser

from dotenv import load_dotenv
from .runtime import ROOT


def main():
    load_dotenv(ROOT / ".env")
    port = int(os.getenv("APP_PORT", "8501"))
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(url + "/_stcore/health", timeout=1) as response:
            if response.read().strip() == b"ok":
                print(f"本機服務已啟動：{url}")
                webbrowser.open(url)
                return
    except (OSError, TimeoutError):
        pass
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
        "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=false",
        "--browser.gatherUsageStats=false"], cwd=ROOT))


if __name__ == "__main__":
    main()
