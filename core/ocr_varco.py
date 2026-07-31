"""VARCO-VISION OCR 引擎封装：接口对齐 EasyOCR 的 Reader.readtext()。

模型: NCSOFT/VARCO-VISION-2.0-1.7B-OCR (1.7B 参数)
韩文识别准确率 95.6%（CORD），远超 EasyOCR 77.8%。
首次运行自动下载模型（约 3.4 GB）。
"""

from __future__ import annotations

import logging
import re
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_model = None
_processor = None


def _load_model():
    """懒加载 VARCO-VISION 模型和处理器。"""
    global _model, _processor
    if _model is None:
        import torch
        from transformers import AutoProcessor
        from transformers import LlavaOnevisionForConditionalGeneration

        model_name = "NCSOFT/VARCO-VISION-2.0-1.7B-OCR"
        logger.info("正在加载 VARCO-VISION OCR 模型（首次需下载约 3.4 GB）...")
        _model = LlavaOnevisionForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch.float16,
            attn_implementation="sdpa",
            device_map="mps",
        )
        _processor = AutoProcessor.from_pretrained(model_name)
        logger.info("VARCO-VISION OCR 模型加载完成")
    return _model, _processor


def readtext(image: np.ndarray, *, detail: int = 0,
             allowlist: str | None = None) -> list:
    """识别图像中的文字。

    Args:
        image: BGR numpy 数组（与 EasyOCR 输入一致）。
        detail: 0 返回纯文本列表，1 返回 [(bbox, text, confidence), ...]。
        allowlist: 字符白名单，对结果做后处理过滤。

    Returns:
        detail=0: ["text1", "text2", ...]
        detail=1: [([[x1,y1],...], "text", confidence), ...]
    """
    model, processor = _load_model()
    import torch

    # BGR numpy → PIL Image
    if image.ndim == 3 and image.shape[2] == 3:
        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    else:
        pil = Image.fromarray(image)

    h, w = pil.height, pil.width

    # VARCO 建议长边至少 2304 以获得最佳 OCR 效果
    target_size = 2304
    scale = 1.0
    if max(w, h) < target_size:
        scale = target_size / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        pil = pil.resize((new_w, new_h), Image.LANCZOS)

    # 构造对话
    conversation = [{
        "role": "user",
        "content": [
            {"type": "image", "image": pil},
            {"type": "text", "text": "<ocr>"},
        ],
    }]

    inputs = processor.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device, torch.float16)

    with torch.no_grad():
        generate_ids = model.generate(**inputs, max_new_tokens=1024)

    generate_ids_trimmed = [
        out_ids[len(in_ids):]
        for in_ids, out_ids in zip(inputs.input_ids, generate_ids)
    ]
    output = processor.decode(
        generate_ids_trimmed[0], skip_special_tokens=False)

    # 解析 VARCO 输出: <char>X</char><bbox>x1,y1,x2,y2</bbox>
    # 将缩放后的坐标映射回原始图像坐标
    chars_with_bbox = _parse_varco_output(output, scale)

    # 应用 allowlist 过滤
    if allowlist:
        chars_with_bbox = [
            (ch, bb) for ch, bb in chars_with_bbox if ch in allowlist
        ]

    if detail == 0:
        text = "".join(ch for ch, _ in chars_with_bbox).strip()
        return [text] if text else []

    # detail=1: 将相邻字符合并为"词"，返回词级 bbox
    words = _group_into_words(chars_with_bbox)
    return words


def _parse_varco_output(output: str, scale: float) -> list[tuple[str, list]]:
    """解析 VARCO 的 <char>X</char><bbox>x1,y1,x2,y2</bbox> 格式。

    Returns:
        [(char, [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]), ...]
    """
    results: list[tuple[str, list]] = []
    # 匹配 <char>X</char><bbox>num,num,num,num</bbox>
    pattern = r"<char>(.*?)</char><bbox>(\d+),\s*(\d+),\s*(\d+),\s*(\d+)</bbox>"
    for m in re.finditer(pattern, output):
        char = m.group(1)
        x1, y1, x2, y2 = map(int, m.groups()[1:])
        # 映射回原始坐标
        if scale != 1.0:
            x1, y1 = int(x1 / scale), int(y1 / scale)
            x2, y2 = int(x2 / scale), int(y2 / scale)
        bbox = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        results.append((char, bbox))
    return results


def _group_into_words(chars: list[tuple[str, list]]) -> list:
    """将字符合并成词（空格或大间隙分割），返回 EasyOCR 格式。"""
    if not chars:
        return []

    words = []
    current_chars: list[str] = []
    current_bboxes: list[list] = []

    for i, (ch, bbox) in enumerate(chars):
        if ch == " " or ch == "\n":
            if current_chars:
                words.append(_make_word(current_chars, current_bboxes))
                current_chars = []
                current_bboxes = []
            continue

        # 检测大间隙（字符间距 > 平均字符宽度的 1.5 倍）
        if current_bboxes and i > 0:
            prev_right = current_bboxes[-1][1][0]  # 上一个字符右边界
            curr_left = bbox[0][0]                  # 当前字符左边界
            avg_w = sum(
                bb[1][0] - bb[0][0] for bb in current_bboxes
            ) / len(current_bboxes)
            if curr_left - prev_right > avg_w * 1.5:
                words.append(_make_word(current_chars, current_bboxes))
                current_chars = []
                current_bboxes = []

        current_chars.append(ch)
        current_bboxes.append(bbox)

    if current_chars:
        words.append(_make_word(current_chars, current_bboxes))

    return words


def _make_word(chars: list[str], bboxes: list[list]) -> tuple:
    """合并字符列表为一个词条目。"""
    text = "".join(chars)
    all_x = [p[0] for bb in bboxes for p in bb]
    all_y = [p[1] for bb in bboxes for p in bb]
    l, r = min(all_x), max(all_x)
    t, b = min(all_y), max(all_y)
    bbox = [[l, t], [r, t], [r, b], [l, b]]
    conf = 0.99  # VARCO 不提供逐字置信度，统一给高置信度
    return (bbox, text, conf)
