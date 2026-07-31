# @Create  : 2026/7/25 15:27
# @Author  : great
# @Remark  : 签到
from __future__ import annotations

from anchors.anchors import Anchor, ImageDir
from fsm.context import Ctx
from fsm.state import State, Signal, Goto, Done, Stay, Back
from fsm.registry import StateRegistry
from target.target import Target


class SignImages(ImageDir):
    path = "images/sign"


class BaseImages(ImageDir):
    path = "images/base"

base_img = BaseImages()
sign_img = SignImages()

MenuButton = (4780, 196)       # 右上角主菜单按钮
SignWindowClose = (4843, 210)  # 签到窗口关闭按钮


class Home(State):
    name = "主界面"
    priority = 10
    signature = [Anchor(ref=base_img["挂机界面判断-齿轮"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        if ctx.click(Target.at(*MenuButton)):
            self.log.info("点击右上角菜单按钮")
            return Goto(Menu)
        return Stay()


class Menu(State):
    name = "主菜单"
    priority = 15
    signature = [Anchor(text="출석")]

    def handle(self, ctx: Ctx) -> Signal:
        for _ in range(3):
            if ctx.click(Target.image(Anchor(text="출석"))):
                self.log.info("点击签到按钮")
                ctx.wait(2)
                return Goto(SignWindow)
            ctx.wait(2)
        else:
            self.log.warning("无法找到签到按钮")
        return Stay()


class SignWindow(State):
    name = "签到窗口"
    priority = 20
    signature = [Anchor(text="출석 체크")]

    has_claimed: bool = False  # 是否已领取签到奖励

    def handle(self, ctx: Ctx) -> Signal:
        # 已领取过奖励后再次进入（如被确认弹框中断后回到此窗口）→ 直接关闭
        if self.has_claimed:
            self.log.info("签到奖励已领取，关闭窗口")
            ctx.click(Target.at(*SignWindowClose))
            ctx.wait(2)
            return Done()

        # 尝试领取签到奖励：依次尝试常用按钮文字
        claim_texts = ["수령", "받기", "출석 체크"]
        for text in claim_texts:
            for _ in range(2):
                if ctx.click(Target.image(Anchor(text=text))):
                    self.log.info("点击签到领取按钮（%s）", text)
                    self.has_claimed = True
                    ctx.wait(2)
                    return Goto(SignConfirm)
                ctx.wait(1)

        # 没有可领取的奖励（已签到过 / 奖励已领完）
        self.log.warning("未找到签到领取按钮，可能已签到")
        ctx.click(Target.at(*SignWindowClose))
        ctx.wait(2)
        return Done()


class SignConfirm(State):
    name = "签到确认弹框"
    priority = 900
    signature = [Anchor(text="확인", ref=sign_img["签到确认按钮"])]

    def handle(self, ctx: Ctx) -> Signal:
        for _ in range(3):
            if ctx.click(Target.image(Anchor(text="확인"))):
                self.log.info("点击签到确认按钮")
                ctx.wait(2)
                return Back()
            ctx.wait(2)
        self.log.warning("无法找到签到确认按钮")
        return Back()


def build_registry() -> StateRegistry:
    from flows.base import build_base_registry
    reg = build_base_registry()
    reg.flow_name = "签到流程"
    reg.register(Home())
    reg.register(Menu())
    reg.register(SignWindow())
    reg.register(SignConfirm())

    # 每轮开始重置流程状态
    def _reset_flow(_ctx=None):
        reg.get_instance(SignWindow).has_claimed = False

    reg.reset_flow = _reset_flow

    return reg
