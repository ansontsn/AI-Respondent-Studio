import re
from collections import Counter

from .errors import AppError

CATEGORIES = {"價格與預算": ["價格", "預算", "折扣", "費用", "支付", "便宜"],
              "購買需求": ["需求", "需要", "購買", "已有", "使用頻率"],
              "外觀偏好": ["外觀", "美觀", "風格", "設計"],
              "實用與品質": ["品質", "耐用", "保護", "實用", "可靠", "功能"],
              "個人化": ["客製", "個人化", "個人特色", "自由度"],
              "品牌與社群": ["品牌", "社群", "朋友", "推薦"],
              "使用情境": ["收藏", "自用", "送禮", "展示", "日常", "工作", "生活情境"],
              "猶豫與不確定": ["猶豫", "不確定", "觀望", "普通", "等待", "評估", "比較"]}
REFUSAL_TERMS = {"缺少需求": ["沒有需求", "沒有購買需求", "不需要", "尚未形成明確需求"],
                 "價格或預算阻礙": ["預算有限", "價格太高", "太貴", "超出預算", "等待折扣"],
                 "已有替代用品": ["已經有", "已有其他", "替代用品"],
                 "仍在觀望": ["不確定", "猶豫", "尚未決定", "等待"]}


def segments(responses, intention_question=None):
    records = []
    for r in responses:
        qmap = {q.id: q for q in r.questionnaire_snapshot.questions}
        target = intention_question or next((q.id for q in qmap.values() if q.trait == "purchase_intention"), None)
        a = next((a for a in r.answers if a.question_id == target), None)
        group = "未指定 / 未作答"
        if a and a.validation not in {"skipped", "error"} and type(a.value) in {int, float}:
            q = qmap[target]
            norm = (a.value - q.scale_min) / (q.scale_max - q.scale_min)
            if q.reverse: norm = 1 - norm
            group = "高購買意願" if norm >= .6 else "低購買意願" if norm <= .4 else "中等購買意願"
        for answer in r.answers:
            if answer.validation in {"skipped", "error"} or qmap[answer.question_id].persona_field:
                continue
            text = answer.rationale
            if answer.other_text:
                text += " " + answer.other_text
            if qmap[answer.question_id].type.value in {"short_text", "paragraph"} and not qmap[answer.question_id].persona_field and isinstance(answer.value, str):
                text += " " + answer.value
            if text.strip():
                records.append({"response_id": r.id, "persona_id": r.persona_id, "人物類型": r.persona_snapshot.archetype,
                    "購買意願群": group, "question_id": answer.question_id, "text": text.strip(), "categories": []})
    return records


def motivation_report(db, task_id, intention_question=None, provider=None):
    records = segments(db.responses(task_id), intention_question)
    if provider:
        by_id = {(r["response_id"], r["question_id"]): r for r in records}
        for start in range(0, len(records), 40):
            chunk = records[start:start + 40]
            result = provider.generate("classify_motivations", {"items": [{"response_id": r["response_id"], "question_id": r["question_id"], "text": r["text"]} for r in chunk],
                "categories": list(CATEGORIES) + ["其他"], "output_example": {"items": [{"response_id": "原ID", "question_id": "原ID", "categories": ["價格與預算"]}]}},
                "只依提供的模擬理由 / 文字分類，可複選主題。不得新增理由、人物、證據或未知 ID。依 output_example 輸出 JSON。")
            items = result.data.get("items")
            expected = {(r["response_id"], r["question_id"]) for r in chunk}
            if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                raise AppError("AI 動機分類結構不完整，未產生報告。")
            actual = [(i.get("response_id"), i.get("question_id")) for i in items]
            if set(actual) != expected or len(actual) != len(expected):
                raise AppError("AI 動機分類有遺漏、重複或未知 ID，未套用。")
            for item in items:
                labels = item.get("categories")
                if not isinstance(labels, list) or not labels or any(c not in list(CATEGORIES) + ["其他"] for c in labels):
                    raise AppError("AI 回傳無效主題分類。")
                by_id[item["response_id"], item["question_id"]]["categories"] = sorted(set(labels))
    else:
        for row in records:
            row["categories"] = [label for label, words in CATEGORIES.items() if any(w in row["text"] for w in words)] or ["其他"]
    expanded = [{**r, "主題": label} for r in records for label in r["categories"]]
    frequencies = Counter(r["主題"] for r in expanded)
    themes = [{"主題": theme, "理由片段數": count, "人物數": len({r["persona_id"] for r in expanded if r["主題"] == theme})} for theme, count in frequencies.most_common()]
    def grouped(field):
        counts = Counter((r[field], r["主題"]) for r in expanded)
        groups = {r[field] for r in records}
        population = {g: len({r["persona_id"] for r in records if r[field] == g}) for g in groups}
        return [{field: g, "主題": theme, "理由片段數": count, "群體人物數": population[g],
                 "提及人物數": len({r["persona_id"] for r in expanded if r[field] == g and r["主題"] == theme}),
                 "每人平均片段數": count / population[g]} for (g, theme), count in counts.items()]
    refusals = []
    for r in records:
        if r["購買意願群"] == "低購買意願":
            for label, words in REFUSAL_TERMS.items():
                if any(w in r["text"] for w in words):
                    refusals.append({"response_id": r["response_id"], "persona_id": r["persona_id"], "question_id": r["question_id"], "拒絕考量": label, "原文字": r["text"]})
    refusal_counts = Counter(r["拒絕考量"] for r in refusals)
    refusal_summary = [{"拒絕考量": reason, "提及片段數": count,
        "人物數": len({r["persona_id"] for r in refusals if r["拒絕考量"] == reason})} for reason, count in refusal_counts.most_common()]
    return {"dataset": db.metadata(), "task_id": task_id, "method": "AI 輔助分類" if provider else "可重現的關鍵詞多標籤分類",
            "analysis_provider": provider.config.model_dump() if provider else None,
            "interpretation": "分類的是 AI 生成的理由片段；多標籤次数不等於受訪者比例，也不是對真人動機的觀察證據。拒絕原因只列原文明確訊號，不能憑低分推定原因。",
            "summary": f"已分類 {len(records)} 個理由 / 文字片段；主要主題：{'、'.join(t['主題'] for t in themes[:3]) or '尚無'}。",
            "segments": records, "themes": themes, "by_persona_type": grouped("人物類型"), "by_intention": grouped("購買意願群"),
            "refusal_reasons": refusals, "refusal_summary": refusal_summary, "intention_question": intention_question,
            "intention_rule": "指定量表標準化至 0–1：≤0.4 低、≥0.6 高，其他中等；缺少適用答案單獨列出。"}
