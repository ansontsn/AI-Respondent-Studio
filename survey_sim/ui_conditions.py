import pandas as pd
import streamlit as st

from .errors import AppError
from .personas import TRAIT_LABELS


def weights_from_text(text, label="比例"):
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if "|" not in line:
            raise AppError(f"{label}第 {number} 行「{line.strip()}」缺少「|」，請寫成「名稱|比例」，例如「工程師|50」。")
        name, value = line.rsplit("|", 1)
        try:
            weight = float(value)
        except ValueError:
            raise AppError(f"{label}第 {number} 行的比例「{value.strip()}」不是數字，請使用阿拉伯數字，例如 50。") from None
        if not name.strip():
            raise AppError(f"{label}第 {number} 行缺少名稱。")
        if name.strip() in result:
            raise AppError(f"{label}第 {number} 行的「{name.strip()}」重複，條件名稱不可重複。")
        result[name.strip()] = weight
    return result


def conditions_editor(key):
    enabled = st.checkbox("啟用受訪者條件與分布控制", key=key + "_enabled")
    if not enabled:
        return None
    st.caption("指定比例是模擬情境。各欄位比例以完整人數分配，不能視為真實人口分布。")
    bands = []
    if st.checkbox("指定年齡分布", value=True, key=key + "_ages"):
        table = st.data_editor(pd.DataFrame({"下界": [18,25,40], "上界": [24,39,65], "比例": [20.,50.,30.]}),
            hide_index=True, num_rows="dynamic", key=key + "_age_table")
        bands = [{"minimum": int(row["下界"]), "maximum": int(row["上界"]), "weight": float(row["比例"])} for _, row in table.iterrows()]
    genders = {}
    if st.checkbox("指定性別分布", key=key + "_genders"):
        table = st.data_editor(pd.DataFrame({"性別": ["女性","男性","不指定"], "比例": [45.,45.,10.]}), hide_index=True, num_rows="dynamic", key=key + "_gender_table")
        genders = dict(zip(table["性別"], table["比例"]))
    education = st.text_area("教育程度與比例（每行名稱|比例；空白不限制）", key=key + "_educations", placeholder="大學|70\n研究所|30")
    occupations = st.text_area("職業與比例（每行名稱|比例；空白不限制）", key=key + "_occupations", placeholder="行政職員|50\n工程師|50")
    income = budget = None
    if st.checkbox("指定每月所得範圍", key=key + "_income"):
        a, b = st.columns(2)
        income = (a.number_input("所得下界", min_value=0., value=20000., key=key + "_income_min"), b.number_input("所得上界", min_value=0., value=70000., key=key + "_income_max"))
    if st.checkbox("指定每月可支配預算", key=key + "_budget"):
        a, b = st.columns(2)
        budget = (a.number_input("預算下界", min_value=0., value=1000., key=key + "_budget_min"), b.number_input("預算上界", min_value=0., value=6000., key=key + "_budget_max"))
    interests = st.text_input("共同興趣與偏好（以頓號分隔；空白不限制）", key=key + "_interests")
    core_values = st.text_input("核心價值觀（以頓號分隔；空白依背景推導）", key=key + "_values")
    familiarity = st.slider("產品熟悉程度範圍", 0., 1., (0.,1.), step=.05, key=key + "_familiarity")
    chosen = st.multiselect("指定決策傾向範圍", list(TRAIT_LABELS), format_func=TRAIT_LABELS.get, key=key + "_traits")
    ranges = {field: st.slider(TRAIT_LABELS[field] + "範圍", 0., 1., (.2,.8), step=.05, key=key + field) for field in chosen}
    custom = st.text_area("自訂背景條件（自然語言）", key=key + "_custom")
    try:
        educations, occupation_weights = weights_from_text(education, "教育程度"), weights_from_text(occupations, "職業")
    except AppError as exc:
        # False (not None) means "enabled but invalid": callers must not run unconditioned.
        st.error(str(exc))
        return False
    return {"age_bands": bands, "genders": genders, "educations": educations, "occupations": occupation_weights,
        "income_range": income, "budget_range": budget, "interests": [v.strip() for v in interests.split("、") if v.strip()],
        "core_values": [v.strip() for v in core_values.split("、") if v.strip()], "familiarity_range": familiarity,
        "trait_ranges": ranges, "custom_background": custom}
