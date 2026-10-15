import io
import json
import zipfile

import pandas as pd

from .analysis import safe_cell, frames_excel
from .security import redact


def report_tables(report):
    metadata = {k: v for k, v in report.items() if not isinstance(v, list)}
    # Excel cells have a 32,767-character limit. Preserve long experiment
    # snapshots in ordered pieces, rather than silently truncating them.
    source_rows = []
    for key, value in metadata.items():
        content = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        for index, offset in enumerate(range(0, max(1,len(content)), 30000)):
            source_rows.append({"欄位": key, "分段順序": index + 1, "內容": safe_cell(content[offset:offset+30000])})
    result = {"報告來源與方法": pd.DataFrame(source_rows)}
    for key, value in report.items():
        if isinstance(value, list):
            result[key[:31]] = pd.DataFrame(value).map(safe_cell)
    return result


def report_exports(report):
    data = redact(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)).encode("utf-8")
    tables = report_tables(report)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", data)
        for name, df in tables.items():
            z.writestr(name + ".csv", df.to_csv(index=False).encode("utf-8-sig"))
    return {"JSON": data, "CSV ZIP": buffer.getvalue(), "Excel": frames_excel(tables)}
