"""执行上下文：把标定、匹配、截图、点击、运行状态串起来。"""

from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from anchors.anchors import Anchor
from calib.calibrator import Calibrator
from core.vision import Match, match_template, load_bgr, to_bgr
from target.target import Target

logger = logging.getLogger(__name__)


def _edit_distance_1(a: str, b: str) -> bool:
    """检查两个字符串的编辑距离是否 ≤1（替换/插入/删除各算 1）。"""
    if abs(len(a) - len(b)) > 1:
        return False
    # 等长 → 检查是否至多一个字符不同
    if len(a) == len(b):
        diff = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                diff += 1
                if diff > 1:
                    return False
        return True
    # a 比 b 长 1 → 检查是否删除 a 中某个字符可得 b
    if len(a) > len(b):
        longer, shorter = a, b
    else:
        longer, shorter = b, a
    i = j = 0
    while i < len(longer) and j < len(shorter):
        if longer[i] != shorter[j]:
            i += 1
            if i - j > 1:
                return False
        else:
            i += 1
            j += 1
    return True


class StopFlow(Exception):
    """请求立即终止流程。"""


class RunState:
    """运行状态标志，由热键线程写、执行线程读。"""

    def __init__(self) -> None:
        self.running = False
        self.paused = False
        self.stopped = False


class Ctx:
    """贯穿引擎的执行上下文。"""

    def __init__(self, calibrator, run_state: RunState, *,
                 capture=None, clicker=None, cache_templates: bool = True,
                 registry=None) -> None:
        self.calibrator: Calibrator = calibrator
        self.run_state = run_state
        self.registry = registry        # StateRegistry，供 State 间通信
        self.screen_bgr: np.ndarray | None = None
        self.device_name = ""
        self.account = 0
        self._capture = capture
        self._clicker = clicker
        self._matcher = match_template
        self._loader = load_bgr
        self._cache: dict[str, np.ndarray] = {} if cache_templates else None

    # -- 截图 --
    def refresh_screenshot(self) -> None:
        if self._capture is not None:
            self.screen_bgr = self._capture()
        else:
            from core.capture import fullscreen_screenshot
            self.screen_bgr = to_bgr(fullscreen_screenshot())

    # -- 匹配 --
    def _template(self, anchor: Anchor) -> np.ndarray:
        key = str(anchor.ref.path)
        if self._cache is None:
            return self._loader(anchor.ref.path)
        if key not in self._cache:
            self._cache[key] = self._loader(anchor.ref.path)
        return self._cache[key]

    def find_anchor(self, anchor: Anchor) -> Match:
        """在当前截图中匹配锚点（图像模板匹配或 OCR 文字定位）。"""
        if anchor.text is not None:
            return self._match_text(anchor)
        return self._match_image(anchor)

    def debug_anchor(self, anchor: Anchor) -> None:
        """调试用：打印 Anchor 在当前截图中的 OCR 识别结果。

        用法（在 State.handle/match 中调用）:
            ctx.debug_anchor(Anchor(text="안전", ref=base_img["地图安全区提示"]))
        """
        if anchor.text is None:
            logger.info("[debug_anchor] 仅支持文字锚点")
            return
        from core.ocr import _get_reader
        off_x, off_y = 0, 0
        if anchor.region is not None:
            r = self.calibrator.to_screen_region(anchor.region)
            left, top, right, bottom = r
            left, top = max(0, left), max(0, top)
            right = min(self.screen_bgr.shape[1], right)
            bottom = min(self.screen_bgr.shape[0], bottom)
            if right <= left or bottom <= top:
                logger.info("[debug_anchor] 区域无效")
                return
            sub = self.screen_bgr[top:bottom, left:right]
            off_x, off_y = left, top
        else:
            sub = self.screen_bgr
        reader = _get_reader()
        results = reader.readtext(sub, detail=1)
        detected = [(d, round(c, 3)) for _, d, c in results]
        logger.info("[debug_anchor] 查询=\"%s\" 识别=%s 区域=%s",
                   anchor.text, detected, anchor.region)

    def _match_image(self, anchor: Anchor) -> Match:
        """cv2.matchTemplate 模板匹配。"""
        region = None
        if anchor.region is not None:
            region = self.calibrator.to_screen_region(anchor.region)
        return self._matcher(self.screen_bgr, self._template(anchor),
                             region=region, threshold=anchor.threshold,
                             scales=[self.calibrator.scale])

    def _match_text(self, anchor: Anchor) -> Match:
        """EasyOCR 文字定位：在 region 内搜索 anchor.text。

        支持：
        - 空格分隔的多词跨块匹配
        - 编辑距离 ≤1 的模糊匹配（≥3 字符时生效，容忍 OCR 单字错误）
        """
        from core.ocr import _get_reader
        off_x, off_y = 0, 0
        if anchor.region is not None:
            r = self.calibrator.to_screen_region(anchor.region)
            left, top, right, bottom = r
            left, top = max(0, left), max(0, top)
            right = min(self.screen_bgr.shape[1], right)
            bottom = min(self.screen_bgr.shape[0], bottom)
            if right <= left or bottom <= top:
                return Match(False, 0.0, (0, 0, 0, 0), 1.0)
            sub = self.screen_bgr[top:bottom, left:right]
            off_x, off_y = left, top
        else:
            sub = self.screen_bgr

        reader = _get_reader()
        results = reader.readtext(sub, detail=1)
        query_compact = anchor.text.replace(" ", "").lower()

        best_conf = 0.0
        # 方式1：精确匹配 — 单个 OCR 结果包含完整 query
        for bbox, detected, conf in results:
            detected_clean = detected.replace(" ", "").lower()
            if query_compact in detected_clean:
                l = int(bbox[0][0]) + off_x
                t = int(bbox[0][1]) + off_y
                r = int(bbox[2][0]) + off_x
                b = int(bbox[2][1]) + off_y
                return Match(True, float(conf), (l, t, r, b), 1.0)
            best_conf = max(best_conf, float(conf))

        # 方式2：模糊匹配 — 编辑距离 ≤1（仅 ≥3 字符时生效）
        if len(query_compact) >= 3:
            for bbox, detected, conf in results:
                detected_clean = detected.replace(" ", "").lower()
                if _edit_distance_1(query_compact, detected_clean):
                    logger.info("模糊匹配: OCR=\"%s\" → 查询=\"%s\"",
                               detected, anchor.text)
                    l = int(bbox[0][0]) + off_x
                    t = int(bbox[0][1]) + off_y
                    r = int(bbox[2][0]) + off_x
                    b = int(bbox[2][1]) + off_y
                    return Match(True, float(conf), (l, t, r, b), 1.0)

        # 方式3：多词匹配 — query 含空格，OCR 分词了 → 跨块（含模糊）
        query_words = [w.strip().lower() for w in anchor.text.split() if w.strip()]
        if len(query_words) > 1:
            matched: list[list] = []
            seen_words: set[str] = set()
            for bbox, detected, conf in results:
                detected_clean = detected.replace(" ", "").lower()
                for w in query_words:
                    if w in seen_words:
                        continue
                    if w in detected_clean or (
                        len(w) >= 3 and _edit_distance_1(w, detected_clean)
                    ):
                        matched.append(bbox)
                        seen_words.add(w)
                        break
            if len(matched) >= len(query_words):
                all_x = [p[0] for b in matched for p in b]
                all_y = [p[1] for b in matched for p in b]
                l = int(min(all_x)) + off_x
                t = int(min(all_y)) + off_y
                r = int(max(all_x)) + off_x
                b = int(max(all_y)) + off_y
                return Match(True, best_conf, (l, t, r, b), 1.0)

        return Match(False, 0.0, (0, 0, 0, 0), 1.0)

    # -- 亮度采样 --
    def brightness(self, region: tuple[int, int, int, int], *,
                   debug_save: str | None = None,
                   refresh: bool = True) -> float:
        """采样指定区域的平均亮度（0=黑, 255=白），用于区分图标深浅态。

        Args:
            region: 屏幕像素区域 (left, top, right, bottom)。
            debug_save: 调试用，非空时将采样区域保存为此路径的图片。
            refresh: 采样前是否刷新截图，默认 True 确保读到最新画面。

        Returns:
            平均灰度值，暗→0，亮→255。
        """
        if refresh:
            self.refresh_screenshot()
        left, top, right, bottom = region
        h, w = self.screen_bgr.shape[:2]
        left = max(0, left)
        top = max(0, top)
        right = min(w, right)
        bottom = min(h, bottom)
        if right <= left or bottom <= top:
            return 0.0
        roi = self.screen_bgr[top:bottom, left:right]
        if debug_save:
            cv2.imwrite(debug_save, roi)
            logger.info("亮度采样区域已保存: %s (区域=%s 均值=%.1f)",
                       debug_save, region, cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).mean())
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    # -- 文字提取 --
    def read_text(self, region: tuple[int, int, int, int], *,
                  allowlist: str | None = None) -> str:
        """提取区域内所有文字，返回空格分隔的字符串。

        有 allowlist 时走 docTR（结构化文本精度更高），
        无 allowlist 时走 EasyOCR（支持韩文）。

        Args:
            region: 屏幕像素区域 (left, top, right, bottom)。
            allowlist: 限定可识别的字符集，如 "0123456789.-:" 用于 IP 地址。
                       省略时不做限制，使用 EasyOCR 识别韩文+英文。

        Returns:
            识别到的文字，空格分隔；无文字返回空字符串。
        """
        left, top, right, bottom = region
        h, w = self.screen_bgr.shape[:2]
        left, top = max(0, left), max(0, top)
        right, bottom = min(w, right), min(h, bottom)
        if right <= left or bottom <= top:
            return ""
        sub = self.screen_bgr[top:bottom, left:right]

        if allowlist is not None:
            # 结构化文本 → docTR（精度更高，. 不会识别为空格等）
            from core.ocr_doctr import readtext
            results = readtext(sub, detail=0, allowlist=allowlist)
        else:
            # 通用文本（含韩文）→ EasyOCR
            from core.ocr import _get_reader
            results = _get_reader().readtext(sub, detail=0)
        return " ".join(results)

    # -- 点击 --
    def click(self, target: Target, *, refresh: bool = True) -> bool:
        """点击目标，默认点击后刷新截图以捕获界面变化。

        Args:
            target: 待点击目标。
            refresh: 点击后是否刷新截图，默认 True。
        """
        pt = target.resolve(self)
        if pt is None:
            return False
        if self._clicker is not None:
            self._clicker(*pt)
        else:
            from core.input import click as real_click
            real_click(*pt)
        if refresh:
            self.refresh_screenshot()
        return True

    # -- 运行控制 --
    def check_state(self) -> None:
        while self.run_state.paused and not self.run_state.stopped:
            time.sleep(0.1)
        if self.run_state.stopped:
            raise StopFlow

    def wait(self, seconds: float, *, refresh: bool = True) -> None:
        """等待指定秒数，默认等待后刷新截图以捕获过渡完成后的画面。

        Args:
            seconds: 等待秒数。
            refresh: 等待后是否刷新截图，默认 True。
        """
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check_state()
            time.sleep(min(0.1, max(0.01, end - time.monotonic())))
        if refresh:
            self.refresh_screenshot()
