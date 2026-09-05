"""Optional screenshot/OCR experiment.

No credential is stored in this file. Set DEEPSEEK_API_KEY in the environment
only when you intentionally want to call DeepSeek.
"""

from __future__ import annotations

import os
import time

import pyautogui
import pytesseract
from openai import OpenAI
from PIL import Image


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.8


def ask_deepseek(question: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "未配置 DEEPSEEK_API_KEY，本次只演示截图和 OCR。"
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=[{"role": "user", "content": question}],
        temperature=0.3,
        max_tokens=200,
    )
    return response.choices[0].message.content or ""


def main() -> None:
    question = "复旦大学的校训是什么？"
    try:
        answer = ask_deepseek(question)
    except Exception as exc:
        answer = f"DeepSeek 调用失败：{type(exc).__name__}"

    time.sleep(1)
    screenshot_path = "deepseek_screenshot.png"
    pyautogui.screenshot().save(screenshot_path)
    try:
        ocr_text = pytesseract.image_to_string(Image.open(screenshot_path), lang="chi_sim+eng")
    except Exception as exc:
        ocr_text = f"OCR 失败：{type(exc).__name__}。请安装 Tesseract 并配置 TESSERACT_CMD。"

    print(f"问题：{question}\n回答：{answer}\n\nOCR：\n{ocr_text[:800]}")


if __name__ == "__main__":
    main()
