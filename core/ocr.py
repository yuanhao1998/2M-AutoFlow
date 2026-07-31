"""OCR 识别模块：图像预处理 + EasyOCR 韩文识别。"""

import logging
import re
import time
import warnings
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

warnings.filterwarnings("ignore", message=".*pin_memory.*not supported on MPS.*")

import easyocr

logger = logging.getLogger(__name__)

DEBUG_DIR = Path("debug_failures")

_reader: easyocr.Reader | None = None


def _get_reader() -> easyocr.Reader:
    """懒加载 EasyOCR Reader（仅韩文，避免英文模型干扰韩文识别）。"""
    global _reader
    if _reader is None:
        logger.info("正在加载 EasyOCR 模型（仅韩文）...")
        try:
            _reader = easyocr.Reader(["ko"], gpu=True)
            logger.info("EasyOCR 模型加载完成（GPU 模式，仅韩文）")
        except Exception:
            logger.warning("GPU 不可用，降级为 CPU 模式")
            _reader = easyocr.Reader(["ko"], gpu=False)
            logger.info("EasyOCR 模型加载完成（CPU 模式，仅韩文）")
    return _reader


def preprocess(image: Image.Image) -> Image.Image:
    """小文字放大提升识别率。"""
    w, h = image.size
    if h < 30:
        return image.resize((w * 3, h * 3), Image.LANCZOS)
    return image


def extract_digits(image: Image.Image) -> str:
    """提取数字：EasyOCR 白名单识别 + 空间聚类兜底。"""
    reader = _get_reader()
    img_array = np.array(image)
    raw_results = reader.readtext(img_array, allowlist="0123456789", detail=0)
    raw = "".join(raw_results)
    segments = re.findall(r"\d+", raw)
    string_result = max(segments, key=len) if segments else ""

    # 宽图触发聚类验证，过滤图标等远端噪点
    aspect = image.width / max(image.height, 1)
    if aspect <= 5 or len(string_result) <= 4:
        return string_result

    cluster_result = _extract_by_cluster(image)
    if len(cluster_result) >= 2:
        return cluster_result
    return string_result


def _extract_by_cluster(image: Image.Image, gap_ratio: float = 0.30) -> str:
    """用 EasyOCR bounding box 获取字符位置，数字聚类后返回最大簇。"""
    reader = _get_reader()
    img_array = np.array(image)
    results = reader.readtext(img_array, allowlist="0123456789", detail=1)

    chars: list[tuple[float, str]] = []
    for bbox, text, _ in results:
        for ch in text:
            if ch.isdigit():
                center_x = (bbox[0][0] + bbox[2][0]) / 2
                chars.append((center_x, ch))

    if not chars:
        return ""

    chars.sort(key=lambda c: c[0])
    gap_threshold = image.width * gap_ratio

    clusters: list[list[tuple[float, str]]] = []
    current = [chars[0]]
    for c in chars[1:]:
        if c[0] - current[-1][0] <= gap_threshold:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)

    best = max(clusters, key=lambda cl: (len(cl), cl[0][0]))
    return "".join(c[1] for c in best)


def extract_text(image: Image.Image) -> str:
    """提取文字，用于云机名称识别。"""
    reader = _get_reader()
    results = reader.readtext(np.array(image), detail=0)
    return " ".join(results)


def recognize_diamond(image: Image.Image) -> str:
    """单次识别：放大 + EasyOCR 数字识别。"""
    w, h = image.size
    if h < 30:
        image = image.resize((w * 3, h * 3), Image.LANCZOS)
    return extract_digits(image)


def recognize_diamond_stable(capture: Callable[[], Image.Image],
                              max_attempts: int = 6,
                              account_index: int = 0,
                              device_name: str = "") -> tuple[str, bool]:
    """多次截图比对，确保钻石数量识别稳定。

    连续截图两次比对；不一致则继续采样，最终投票决定。
    识别困难时自动保存截图到 debug_failures/ 供排查。

    Args:
        capture: 无参回调，返回钻石区域截图。
        max_attempts: 最大采样次数。
        account_index: 当前账户序号（用于调试文件命名）。
        device_name: 云机名称（用于调试文件命名）。

    Returns:
        (识别结果, 是否不稳定)，全失败返回 ("", False)。
    """
    captures: list[Image.Image] = []
    samples: list[str] = []

    def _sample() -> str:
        img = capture()
        captures.append(img)
        return recognize_diamond(img)

    # 第一张
    v1 = _sample()
    if not v1:
        return "", False
    samples.append(v1)

    # 第二张
    time.sleep(1)
    v2 = _sample()
    if not v2:
        return v1, False
    samples.append(v2)

    if v1 == v2:
        return v1, False

    logger.info("两次识别不一致 (%s vs %s)，追加采样...", v1, v2)

    for _ in range(max_attempts - 2):
        time.sleep(1)
        v = _sample()
        if v:
            samples.append(v)
            if len(samples) >= 2 and samples[-1] == samples[-2]:
                logger.info("连续两次一致 (%s)，采信", v)
                return v, False

    # 未达成一致 → 投票并保存调试图片
    best = Counter(samples).most_common(1)[0][0] if samples else ""
    _save_debug(captures, samples, best, account_index, device_name)
    return best, True


def _save_debug(captures: list[Image.Image], samples: list[str],
                _best: str, index: int, device_name: str = "") -> None:
    """保存识别困难的截图到 debug_failures/ 目录。

    命名: 时间_云机名称_序号_采样号_识别值.png
    """
    DEBUG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    logger.warning("识别不稳定，截图已保存到 %s/", DEBUG_DIR)

    label = device_name or f"acct{index}"
    for i, (img, val) in enumerate(zip(captures, samples)):
        filename = f"{ts}_{label}_{i}_{val}.png"
        img.save(DEBUG_DIR / filename)

    for i, img in enumerate(captures):
        processed = preprocess(img)
        filename = f"{ts}_{label}_{i}_proc.png"
        processed.save(DEBUG_DIR / filename)
