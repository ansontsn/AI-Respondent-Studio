from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .models import Persona, uid
from .personas import ARCHETYPES, TRAIT_LABELS, PersonaGenerator
from .providers import make_provider
from .ui import guarded, select_entity


def active_provider(rt):
    items = rt.db.list("provider")
    preferred = rt.setting("active_provider", "mock-default")
    order = sorted(items, key=lambda p: p.id != preferred)
    return select_entity("AI 設定檔", order)


def people_page(rt):
    tab1, tab2 = st.tabs(["建立人物", "查看與編輯"])
    with tab1:
        c = active_provider(rt)
        count_col, seed_col = st.columns(2)
        count = count_col.number_input("人物數量", min_value=1, max_value=10000, value=10)
        seed = seed_col.number_input("Random Seed", min_value=0, max_value=2_000_000_000, value=42)
        topic = st.text_input("問卷主題或生活情境", value="一般消費與生活")
        archetype = st.selectbox("人設類型", ARCHETYPES, index=1)
        custom = st.text_area("自訂人物描述或補充情境", placeholder="可加入金融、服務、教育等主題；保留差異與例外。")
        # The ONLYFRAME website flow is optional; its option is shown in advanced mode only.
        choose_tier = st.session_state.get("ui_mode") == "進階模式" and st.checkbox("生成時由 AI 選定 ONLYFRAME 方案，之後固定沿用", value=False)
        if choose_tier:
            st.caption("AI 依背景、興趣與偏好選 BASIC、CUSTOM 或 PREMIUM，保存方案與理由；不強制平均分配。真實模型每位人物會增加一次方案選擇請求。")
        from .ui_conditions import conditions_editor
        with st.expander("進階受訪者條件與分布"):
            conditions = conditions_editor("people_conditions")
            if conditions and st.button("預覽指定條件分布"):
                from .conditional_personas import condition_plan
                from .v2_models import PersonaConditions
                result = guarded(lambda: condition_plan(PersonaConditions.model_validate(conditions), count, seed))
                if result is not None:
                    st.dataframe(pd.DataFrame(result), hide_index=True, width="stretch")
        use_ratios = st.checkbox("混合不同類型及比例")
        ratios = {archetype: 1}
        if use_ratios:
            table = st.data_editor(pd.DataFrame({"類型": ARCHETYPES[2:9], "比例": [20., 20., 15., 15., 10., 10., 10.]}),
                disabled=["類型"], hide_index=True, key="persona_ratios")
            ratios = dict(zip(table["類型"], table["比例"]))
        st.caption("生成人物時會一併建立中文姓名，同一人物之後沿用。比例是自訂情境，不代表真實市場。相同 seed、設定及 Mock 版本可重現；真實 API 不保證逐字重現。")
        if conditions is False:
            st.caption("受訪者條件有格式錯誤，修正後才能生成。")
        if st.button("生成並儲存人物", type="primary", disabled=c is None or conditions is False):
            progress = st.progress(0.)
            status = st.empty()
            # Each click is a new batch: it adds people instead of overwriting earlier ones.
            batch_id = uid()
            def generate():
                engine = PersonaGenerator(make_provider(c, rt.secrets.get(c.id, c.provider), rt.db))
                existing_names = {person.id:person.name for person in rt.db.list("persona")}
                used_names = set(existing_names.values())
                def save(p, done, total):
                    from .persona_names import ensure_name, is_placeholder
                    previous_name = existing_names.get(p.id)
                    if previous_name and not is_placeholder(previous_name):
                        p.name = previous_name
                    else:
                        ensure_name(p, used_names)
                    rt.db.save("persona", p)
                    existing_names[p.id] = p.name
                    used_names.add(p.name)
                    progress.progress(done / total)
                    status.caption(f"已保存 {done} / {total} 位人物")
                if conditions:
                    from .conditional_personas import ConditionalPersonaGenerator
                    from .v2_models import PersonaConditions
                    controlled = PersonaConditions.model_validate({**conditions, "custom_background": custom + "\n" + conditions["custom_background"]})
                    return ConditionalPersonaGenerator(engine.provider).generate_batch(count, seed, topic, ratios, controlled, save, choose_website_tier=choose_tier, id_namespace=batch_id)
                return engine.generate_batch(count, seed, topic, ratios, custom, save, choose_website_tier=choose_tier, id_namespace=batch_id)
            result = guarded(generate)
            if result:
                st.success(f"已建立並保存 {len(result)} 位人物。每次生成都會新增一批人物，不會覆蓋既有人物或手動修改。")
                st.dataframe(pd.DataFrame([{"人物": p.name, "類型": p.archetype, "年齡": p.background.age,
                    "職業": p.background.occupation, "可用預算": p.background.disposable_budget,
                    "固定方案": p.onlyframe_tier or "未指定", "方案理由": p.onlyframe_tier_reason} for p in result]), hide_index=True)
                from .conditional_personas import distribution_check
                st.json(distribution_check(result))
        uploaded = st.file_uploader("匯入人物 JSON（完整 Persona 或陣列）", type="json")
        if uploaded and st.button("儲存匯入人物"):
            def import_people():
                data = json.loads(uploaded.getvalue().decode("utf-8-sig"))
                persons = [Persona.model_validate(p) for p in (data if isinstance(data, list) else [data])]
                for p in persons:
                    rt.db.save("persona", p)
                st.success(f"已匯入 {len(persons)} 人。")
            guarded(import_people)
    with tab2:
        persons = rt.db.list("persona")
        p = select_entity("人物", persons)
        if not p:
            return
        st.write(p.narrative)
        if p.onlyframe_tier:
            st.info(f"ONLYFRAME 固定方案：{p.onlyframe_tier} · {p.onlyframe_tier_reason}")
        st.caption(f"ID：{p.id} · 修訂 {p.revision}")
        with st.expander("完整人物資料"):
            st.json(p.model_dump())
            st.download_button("下載人物 JSON", p.model_dump_json(indent=2), file_name=f"persona-{p.id}.json")
        with st.form(f"edit_persona_{p.id}"):
            name = st.text_input("人物名稱", p.name)
            a, b, c = st.columns(3)
            age = a.number_input("年齡", 18, 100, p.background.age)
            occupation = b.text_input("職業", p.background.occupation)
            status = c.text_input("學生或就業狀態", p.background.status)
            gender = a.text_input("性別（可不指定）", p.background.gender)
            education = b.text_input("教育程度", p.background.education)
            lifestyle = st.text_input("生活型態", p.background.lifestyle)
            interests = st.text_input("主要興趣（以頓號分隔）", "、".join(p.background.interests))
            income = a.number_input("每月所得 / 生活費", min_value=0., value=p.background.monthly_income)
            budget = b.number_input("每月可支配預算", min_value=0., value=p.background.disposable_budget)
            spending = c.number_input("單次主題消費預算", min_value=0., value=p.behavior.spending_budget)
            values = {}
            columns = st.columns(2)
            for i, (key, label) in enumerate(TRAIT_LABELS.items()):
                values[key] = columns[i % 2].slider(label, 0., 1., getattr(p.traits, key), step=.01)
            narrative = st.text_area("生活情境敘述", p.narrative)
            motivations = st.text_input("購買動機（以頓號分隔）", "、".join(p.behavior.motivations))
            barriers = st.text_input("購買阻礙（以頓號分隔）", "、".join(p.behavior.barriers))
            habits = st.text_input("使用習慣", p.behavior.usage_habits)
            core = st.text_area("核心價值觀（每行一項）", "\n".join(p.core_values))
            topic = st.text_area("主題延伸屬性 JSON", json.dumps(p.topic_attributes, ensure_ascii=False, indent=2))
            saved = st.form_submit_button("儲存人物修改", type="primary")
        if saved:
            def update():
                data = p.model_dump()
                data.update(name=name, narrative=narrative, core_values=[x for x in core.splitlines() if x.strip()], topic_attributes=json.loads(topic), revision=p.revision + 1)
                data["background"].update(age=age, occupation=occupation, status=status, gender=gender, education=education,
                    lifestyle=lifestyle, interests=[s.strip() for s in interests.split("、") if s.strip()], monthly_income=income, disposable_budget=budget)
                data["traits"] = values
                data["behavior"]["spending_budget"] = spending
                data["behavior"].update(motivations=[s.strip() for s in motivations.split("、") if s.strip()],
                    barriers=[s.strip() for s in barriers.split("、") if s.strip()], usage_habits=habits)
                rt.db.save("persona", Persona.model_validate(data))
                st.success("修改已保存；歷史回答仍保留原人物快照。")
            guarded(update)
        with st.expander("進階完整編輯（教育、興趣、使用習慣等）"):
            complete = st.text_area("完整人物 JSON", p.model_dump_json(indent=2), height=400, key=f"pjson_{p.id}_{p.revision}")
            if st.button("儲存完整編輯"):
                def full_save():
                    edited = Persona.model_validate_json(complete)
                    edited.id, edited.revision = p.id, p.revision + 1
                    rt.db.save("persona", edited)
                    st.success("人物已更新。")
                guarded(full_save)
        col1, col2 = st.columns(2)
        if col1.button("複製人物"):
            new = p.model_copy(deep=True)
            new.id, new.name = uid(), p.name + "（複本）"
            rt.db.save("persona", new)
            st.rerun()
        if col2.button("刪除人物"):
            rt.db.delete("persona", p.id)
            st.rerun()
