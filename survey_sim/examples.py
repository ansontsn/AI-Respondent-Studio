from .models import Questionnaire, Page, Question, QuestionType, Option, Route, Condition


def opts(*labels):
    return [Option(id=f"O{i+1}", label=l) for i, l in enumerate(labels)]


def onlyframe_example():
    return Questionnaire(id="onlyframe-demo-v1", title="ONLYFRAME 功能測試問卷", topic="ONLYFRAME 客製化小卡框",
        description="供功能測試自訂的範例；不是正式 ONLYFRAME 研究問卷。低、中、高自由度僅為情境示範。",
        audience="對收藏用品有不同程度興趣的虛擬成年人物", confirmed=True,
        pages=[Page(id="P1", title="背景及收藏情境", questions=[
            Question(id="Q01", title="您的年齡", type=QuestionType.SHORT, persona_field="background.age", concept="基本資料"),
            Question(id="Q02", title="目前主要職業", type=QuestionType.SHORT, persona_field="background.occupation"),
            Question(id="Q03", title="您目前是否收藏小卡？", type=QuestionType.SINGLE, options=[
                Option(id="yes", label="有", trait_weights={"topic_interest": 1}), Option(id="no", label="沒有", trait_weights={"topic_interest": -1, "rationality": .35})]),
            Question(id="Q04", title="常使用哪些購物管道？", type=QuestionType.MULTIPLE, options=opts("品牌官網", "實體門市", "社群商店", "網路商城"), max_choices=3),
        ], routes=[Route(when=Condition(question_id="Q03", value="no"), target="P3")]),
        Page(id="P2", title="收藏經驗", questions=[
            Question(id="Q05", title="收藏頻率", type=QuestionType.DROPDOWN, options=opts("很少", "每季", "每月", "每週")),
            Question(id="Q06", title="小卡框主要購買動機", type=QuestionType.MULTIPLE, options=opts("保護收藏", "展示外觀", "個人風格", "送禮"), max_choices=3),
            Question(id="Q07", title="我重視小卡框的保護品質", type=QuestionType.LINEAR, trait="quality_focus", concept="保護功能"),
        ]),
        Page(id="P3", title="產品情境與選擇", questions=[
            Question(id="Q08", title="我重視產品的外觀設計", type=QuestionType.LIKERT, trait="aesthetics", concept="外觀重視"),
            Question(id="Q09", title="我會認真比較價格", type=QuestionType.LIKERT, trait="price_sensitivity", concept="價格敏感"),
            Question(id="Q10", title="我喜歡具有個人特色的產品", type=QuestionType.LIKERT, trait="personalization", concept="客製化偏好"),
            Question(id="Q11", title="我願意支付較高價格購買客製化產品", type=QuestionType.LIKERT, trait="willingness_to_pay", concept="付費意願"),
            Question(id="Q12", title="目前的購買意願", type=QuestionType.LINEAR, trait="purchase_intention", concept="購買意願"),
            Question(id="Q13", title="偏好的客製化方案", type=QuestionType.SINGLE, options=[
                Option(id="low", label="低自由度：選擇既有樣式", trait_weights={"price_sensitivity": .8, "rationality": .3}),
                Option(id="mid", label="中自由度：調整部分樣式", trait_weights={"personalization": .4, "aesthetics": .4}),
                Option(id="high", label="高自由度：自由組合設計", trait_weights={"personalization": .9, "openness": .4, "price_sensitivity": -.3}),
                Option(id="none", label="目前沒有需求", trait_weights={"topic_interest": -1, "price_sensitivity": .5})]),
            Question(id="Q14", title="選擇高自由度方案的原因", type=QuestionType.PARAGRAPH,
                     display_if=[Condition(question_id="Q13", value="high")], max_length=500),
            Question(id="Q15", title="各使用情境的偏好", type=QuestionType.GRID, options=opts("不重視", "普通", "重視"), rows=opts("日常展示", "隨身攜帶", "送禮")),
            Question(id="Q16", title="各情境需要的功能", type=QuestionType.CHECK_GRID, options=opts("保護", "外觀", "個人化"), rows=opts("自用", "送禮"), max_choices=2),
            Question(id="Q17", title="其他考量或猶豫", type=QuestionType.PARAGRAPH, required=False, max_length=500),
        ])])


def general_example():
    return Questionnaire(id="service-demo-v1", title="數位服務體驗功能測試", topic="數位服務", confirmed=True,
        pages=[Page(id="P1", title="服務情境", questions=[
            Question(id="S01", title="我願意嘗試新的數位服務", type=QuestionType.LIKERT, trait="openness"),
            Question(id="S02", title="我會比較各服務的費用", type=QuestionType.LIKERT, trait="price_sensitivity"),
            Question(id="S03", title="我不喜歡嘗試新服務", type=QuestionType.LIKERT, trait="openness", reverse=True),
            Question(id="S04", title="選擇服務時的主要考量", type=QuestionType.MULTIPLE, options=opts("價格", "品質", "品牌", "朋友建議"), max_choices=3),
            Question(id="S05", title="請說明您的考量", type=QuestionType.SHORT),
        ])])
