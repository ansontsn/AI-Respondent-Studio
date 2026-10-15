"""Reproducible fictional Chinese names, assigned when personas are generated."""
import hashlib
import re

from .errors import AppError

SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝洪郭邱曾廖賴徐周葉蘇莊呂江何蕭羅高潘朱")
FIRST = list("宇品子柏冠承奕思宥沛庭書以昀孟安靖若亦予映允文詠祐知育羽晨秉心家")
SECOND = list("辰涵晴恩妍軒廷瑄甯睿萱澄維希寧彤瑜然均妤言綺諺昕霖潔雅佑儒穎喬恆")
SIZE = len(SURNAMES) * len(FIRST) * len(SECOND)


def is_placeholder(name):
    return not name.strip() or bool(re.fullmatch(r"(?:虛擬人物|模擬人物|人物|Persona|Respondent)[\s_\-]*\d*", name.strip(), re.I))


def name_for_id(persona_id, used=()):
    used = set(used)
    offset = int.from_bytes(hashlib.sha256(persona_id.encode()).digest()[:8], "big") % SIZE
    for attempt in range(SIZE):
        index = (offset + attempt) % SIZE
        surname, index = divmod(index, len(FIRST) * len(SECOND))
        first, second = divmod(index, len(SECOND))
        name = SURNAMES[surname] + FIRST[first] + SECOND[second]
        if name not in used:
            return name
    raise AppError("可用姓名組合已用完；請使用自訂姓名或減少人物數量。")


def ensure_name(persona, used=()):
    if is_placeholder(persona.name) or persona.name in set(used):
        persona.name = name_for_id(persona.id, used)
        persona.topic_attributes["name_source"] = "seeded_fictional_name_v1"
    return persona
