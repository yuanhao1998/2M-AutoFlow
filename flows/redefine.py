# @Create  : 2026/7/27 20:36
# @Author  : great
# @Remark  :
from __future__ import annotations

import re

from anchors.anchors import Anchor, ImageDir
from fsm.context import Ctx
from fsm.state import State, Signal, Goto, Done, Stay
from fsm.registry import StateRegistry
from target.target import Target


class RedefineImages(ImageDir):
    path = "images/redefine"


class BaseImages(ImageDir):
    path = "images/base"

base_img = BaseImages()
redefine_img = RedefineImages()


MenuButton = (4780, 196)  # 右上角主菜单按钮


class Home(State):
    name = "主界面"
    priority = 10
    signature = [Anchor(ref=base_img["挂机界面判断-齿轮"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        if ctx.click(Target.at(*MenuButton)):
            self.log.info("点击右上角主菜单按钮成功")
            return Goto(Menu)
        return Stay()


class Menu(State):
    name = "主菜单"
    priority = 15
    signature = [Anchor(text="연금술", ref=redefine_img["精炼菜单按钮"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        if ctx.click(Target.image(Anchor(text="연금술",
                   ref=redefine_img["精炼菜单按钮"]))):
            self.log.info("点击精炼菜单按钮成功")
            return Goto(RedefineWindow)
        return Stay()


class RedefineWindow(State):
    name = "精炼窗口"
    priority = 20
    signature = [Anchor(text="정련", ref=redefine_img["精炼窗口判断"])]

    # ---- 装备格子布局参数（从实际截图测量计算得出） ----
    GRID_LEFT = 3729     # 第一列左上角 X
    GRID_TOP = 679       # 第一行左上角 Y
    SLOT_W = 252         # 格子宽度
    SLOT_H = 244         # 格子高度
    COL_GAP = 289        # 水平间距：格左上角到下一格左上角
    ROW_GAP = 275        # 垂直间距：格左上角到下一行左上角
    COLS = 4             # 每行个数
    MAX_ROWS = 10        # 最大扫描行数（超过即停止）

    # 可填充装备标识：格子左上角的标记图，用来判断该格是否有装备
    MARKER_W = 40        # 标识搜索区域宽度
    MARKER_H = 40        # 标识搜索区域高度

    # 强化值识别区域（格子右下角，"+1"/"+5"/"+7" 出现的位置）
    ENHANCE_W = 40       # 区域宽度
    ENHANCE_H = 24       # 区域高度

    # 操作数量
    ENHANCED_COUNT = 2   # 先添加几件有强化值的装备
    NORMAL_COUNT = 3     # 再添加几件无强化值的装备

    def handle(self, ctx: Ctx) -> Signal:
        """扫描装备 → 识别强化值 → 双击添加。"""
        enhanced: list[tuple[int, int]] = []  # (cx, cy) 有强化值
        normal: list[tuple[int, int]] = []    # (cx, cy) 无强化值

        marker = Anchor(ref=redefine_img["可填充装备标识"])

        for row in range(self.MAX_ROWS):
            row_has_any = False
            for col in range(self.COLS):
                if not self._has_equipment(ctx, row, col, marker):
                    continue
                row_has_any = True
                cx = self.GRID_LEFT + col * self.COL_GAP + self.SLOT_W // 2
                cy = self.GRID_TOP + row * self.ROW_GAP + self.SLOT_H // 2
                value = self._read_enhance(ctx, row, col)
                if value is not None:
                    self.log.info("格子(%d,%d) 强化 +%d", row, col, value)
                    enhanced.append((cx, cy))
                else:
                    normal.append((cx, cy))
            # 整行都没装备 → 后面的行也不会有了，停止扫描
            if not row_has_any:
                break

        self.log.info("扫描完成：强化 %d 件，普通 %d 件",
                     len(enhanced), len(normal))

        # 阶段 1：添加有强化值的装备（双击）
        for i, (cx, cy) in enumerate(enhanced[:self.ENHANCED_COUNT]):
            self.log.info("双击强化装备 %d/%d", i + 1, self.ENHANCED_COUNT)
            self._double_click(ctx, cx, cy)
            ctx.wait(0.5)

        # 阶段 2：添加无强化值的装备（双击）
        for i, (cx, cy) in enumerate(normal[:self.NORMAL_COUNT]):
            self.log.info("双击普通装备 %d/%d", i + 1, self.NORMAL_COUNT)
            self._double_click(ctx, cx, cy)
            ctx.wait(0.5)

        self.log.info("装备添加完成")
        return Done()

    # ---- 内部方法 ----

    def _has_equipment(self, ctx: Ctx, row: int, col: int,
                       marker: Anchor) -> bool:
        """检测格子左上角是否有可填充装备标识。"""
        slot_left = self.GRID_LEFT + col * self.COL_GAP
        slot_top = self.GRID_TOP + row * self.ROW_GAP
        # 在格子左上角小区域内搜索标识
        search_region = (slot_left, slot_top,
                        slot_left + self.MARKER_W, slot_top + self.MARKER_H)
        result = ctx.find_anchor(Anchor(ref=marker.ref, region=search_region))
        return result.matched

    def _read_enhance(self, ctx: Ctx, row: int, col: int) -> int | None:
        """OCR 识别格子右下角的强化值 (+1/+5/+7)，无强化返回 None。"""
        slot_left = self.GRID_LEFT + col * self.COL_GAP
        slot_top = self.GRID_TOP + row * self.ROW_GAP
        slot_right = slot_left + self.SLOT_W
        slot_bottom = slot_top + self.SLOT_H
        left = slot_right - self.ENHANCE_W
        top = slot_bottom - self.ENHANCE_H

        screen_region = ctx.calibrator.to_screen_region(
            (left, top, slot_right, slot_bottom))
        text = ctx.read_text(screen_region, allowlist="+0123456789")
        m = re.search(r'\+(\d+)', text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _double_click(ctx: Ctx, x: int, y: int) -> None:
        """双击指定作图坐标位置。"""
        import pyautogui
        sx, sy = ctx.calibrator.to_screen(x, y)
        from core.input import _to_logical
        lx, ly = _to_logical(sx, sy)
        from core.input import _keep_cursor_visible
        pyautogui.moveTo(lx, ly, duration=0.1)
        pyautogui.doubleClick()
        _keep_cursor_visible()


def build_registry() -> StateRegistry:
    from flows.base import build_base_registry
    reg = build_base_registry()
    reg.flow_name = "精炼流程"
    reg.register(Home())
    reg.register(Menu())
    reg.register(RedefineWindow())
    return reg
