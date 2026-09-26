"""Conservative text helpers shared by local extraction and ranking."""
from __future__ import annotations

import re
from datetime import date


DATE_TEXT = r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"


def field_value(text: str, labels: list[str]) -> str:
    for label in labels:
        # Horizontal whitespace only: an empty field must not eat the next line.
        match = re.search(rf"{re.escape(label)}[ \t]*[:：][ \t]*([^\n。；;]*)", text, re.I)
        if match:
            value = match.group(1).strip().rstrip("。；;，,").strip()
            return "" if value in {"未注明", "未提供", "未知", "暂无"} else value[:255]
    return ""


def is_information_only(text: str) -> bool:
    title = text.splitlines()[0] if text else ""
    if re.search(r"取消通知|活动取消|讲座取消", title):
        return True
    if re.search(r"(?:本次|本期|本场|原定)[^。\n]{0,25}(?:已取消|不再接受报名)", text):
        return True
    if re.search(r"不发布(?:任何|具体)?(?:岗位|机会)|本篇仅为回顾|没有新一届报名", text):
        return True
    if not re.search(r"攻略|指南|经验|回顾|总结|解读", title):
        return False
    # A guide embedded in a real invitation is still an opportunity. Generic
    # annual timelines and retrospective application instructions are not.
    current_invitation = re.search(
        r"欢迎[^。\n]{0,12}(?:报名|申请)|(?:现正|正在|现|即日起)[^。\n]{0,10}(?:招募|招收|招聘|接受申请)|"
        r"(?:报名|申请)(?:中|现已开放|通道已开启)|扫码(?:立即)?报名|(?:本次|本期)[^。\n]{0,12}报名截止",
        text,
    )
    return not bool(current_invitation)


def organizer(text: str) -> str:
    explicit = field_value(text, ["主办方", "主办单位", "组织方", "举办单位", "单位"])
    if explicit:
        return explicit
    # A team heading names the institution BEFORE the second colon. Do not
    # treat a laboratory's description as its name.
    heading = re.search(r"(?:团队介绍|团队名称)[ \t]*[:：][ \t]*([^：:\n。]{2,60}(?:实验室|研究院|中心|团队))[：:]", text)
    if heading:
        return heading.group(1).strip()
    for sentence in re.split(r"[。！？\n]", text):
        match = re.search(r"(?:^|[，,])\s*([^，,:：]{2,50}?(?:党委|学院|大学|基金|协会|实验室))(?=针对|(?:再次)?走进|主办|举办|发起|组织)", sentence)
        if match and re.search(r"主办|举办|发动|发起|走进|组织", sentence):
            return match.group(1).strip()
    return ""


def event_time(text: str) -> str:
    explicit = field_value(text, ["活动时间", "项目时间", "实习时间", "时间"])
    if explicit:
        return explicit
    for sentence in re.split(r"[。！？\n]", text):
        if any(word in sentence for word in ("截止", "报名", "成立", "创立", "自", "曾", "去年", "回顾")):
            continue
        match = re.search(rf"(?P<date>{DATE_TEXT})", sentence)
        if match and re.search(r"将|举行|举办|开讲", sentence):
            return match.group('date')
    return ""


def deadline(text: str) -> str:
    explicit = field_value(text, ["报名截止日期", "申请截止日期", "报名截止", "申请截止", "截止", "DDL"])
    if explicit:
        return explicit
    match = re.search(rf"(?:报名|申请)[^。\n]{{0,10}}?(?P<date>{DATE_TEXT})[前日]?截止", text)
    return match.group('date') if match else ""


def event_end_date(text: str, category: str) -> date | None:
    """Only expire a dated one-day event or an unambiguous date range.

    An internship start date, a yearless date and an open-ended range are not
    sufficient evidence that an opportunity has ended.
    """
    matches = list(re.finditer(rf"(?P<date>{DATE_TEXT})", text))
    if not matches:
        return None
    first = matches[0].group('date')
    year_match = re.match(r"(20\d{2})", first)
    if not year_match:
        return None
    year = int(year_match.group(1))
    dates = []
    for match in matches:
        numbers = [int(v) for v in re.findall(r"\d+", match.group('date'))]
        if len(numbers) == 3:
            year, month, day = numbers
        else:
            month, day = numbers
        try:
            dates.append(date(year, month, day))
        except ValueError:
            return None
    if len(dates) > 1:
        between = text[matches[0].end():matches[-1].start()]
        if not re.fullmatch(r"\s*(?:至|到|[-~～—–])\s*", between) or dates[-1] < dates[0]:
            return None
        return dates[-1]
    tail = text[matches[0].end():]
    if re.search(r"至|到|长期|起|开始|[-~～—–]\s*\d{1,2}(?:月|日)", tail):
        return None
    return dates[0] if category in {"讲座", "课程", "竞赛", "夏令营"} else None
