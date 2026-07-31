# @Create  : 2026/7/20 02:56
# @Author  : great
# @Remark  :
from enum import Enum

from anchors.anchors import ImageDir
from flows.base import build_base_registry, Death
from fsm.context import Ctx
from fsm.registry import StateRegistry
from fsm.state import *
from target.target import Target

GoHome = (1129, 2502)  # 点击回城按钮
SupplyWindowExit = (4843, 210)  # 退出补给窗口
OpenNPCList = (995, 715)  # 打开NPC列表
OpenTPList = (992, 444)  # 打开传送列表
FirstTPClick = (536, 921)  # 第一个传送地址
AutoAttack = (4087, 1455)  # 开启自动攻击


class SupplyImages(ImageDir):
    path = "images/supply"


class BaseImages(ImageDir):
    path = "images/base"

base_img = BaseImages()
supply_img = SupplyImages()

class HomeStateEnum(int, Enum):
    default = 0       # 刚回城，需要打开 NPC 列表
    after_supply = 1  # 补给完毕，需要打开传送列表


class Home(State):
    name = "主城界面"
    priority = 10
    signature = []
    state = HomeStateEnum.default

    def match(self, ctx: Ctx) -> bool:
        """安全区提示 或 补给商人名称 任一命中即为首页。"""
        a1 = ctx.find_anchor(Anchor(text="안전", ref=base_img["地图区域提示"]))
        a2 = ctx.find_anchor(Anchor(text="격전의 섬", ref=base_img["地图名称"]))
        a3 = ctx.find_anchor(Anchor(text="잡화 상인", ref=supply_img["补给商人名称"]))
        return (a1.matched and not a2.matched) or a3.matched

    def handle(self, ctx) -> Signal:
        self.log.info("当前State： %s" % self.state)
        if self.state == HomeStateEnum.default:
            if ctx.find_anchor(Anchor(text="안전", ref=base_img["地图区域提示"])).matched or not ctx.find_anchor(Anchor(text="잡화 상인", ref=supply_img["补给商人名称"])).matched:
                ctx.click(Target.at(*OpenNPCList))
                self.log.info("打开 NPC 列表")
                ctx.wait(2)
                return Goto(NPCList)

        elif self.state == HomeStateEnum.after_supply:
            if not ctx.find_anchor(Anchor(text="저장", ref=supply_img["传送列表标题文字"])).matched:
                ctx.click(Target.at(*OpenTPList))
                self.log.info("打开传送列表")
                ctx.wait(2)
                return Goto(TPList)

        return Stay()


class AFK(State):
    name = "野外挂机"
    signature = [Anchor(ref=base_img["金币图案判断"])]
    auto_attack = False  # True=传送到达后开启自动攻击，False=正常回城

    def match(self, ctx: Ctx) -> bool:
        print(ctx.find_anchor(Anchor(ref=base_img["金币图案判断"])).confidence)
        return super().match(ctx)

    def handle(self, ctx) -> Signal:
        if self.auto_attack:
            ctx.click(Target.at(*AutoAttack))
            self.log.info("开启自动攻击")
            ctx.wait(2)
            self.auto_attack = False
            return Done()

        for _ in range(3):
            if ctx.click(Target.at(*GoHome)):
                self.log.info("点击回城")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.error("无法点击回城")
            return Done()

        return Goto(Home)


class TPList(State):
    name = "传送列表"
    priority = 15
    signature = [Anchor(text="개인", ref=supply_img["传送列表标题文字"])]

    def handle(self, ctx) -> Signal:
        self.log.info("进入传送列表")
        for _ in range(3):
            ctx.click(Target.at(*FirstTPClick))
            ctx.wait(2)
            if ctx.find_anchor(Anchor(ref=supply_img["传送点击按钮"])).matched:
                self.log.info("点击第一个传送地点成功")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.error("无法点击传送地点")
            return Done()

        return Goto(TPConfirm)


class TPConfirm(State):
    name = "传送确认"
    signature = [Anchor(ref=supply_img["传送点击按钮"])]

    def handle(self, ctx) -> Signal:

        for _ in range(3):
            if ctx.click(Target.image(Anchor(ref=supply_img['传送点击按钮']))):
                self.log.info("点击传送确认按钮成功")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.error("点击传送确认按钮失败")

        # 告知 AFK 传送到野外后开启自动攻击
        afk = ctx.registry.get_instance(AFK)
        afk.auto_attack = True
        return Goto(AFK)


class NPCList(State):
    name = "NPC列表"
    priority = 15
    signature = [Anchor(text="잡화 상인", ref=supply_img["补给商人名称"])]

    def handle(self, ctx) -> Signal:

        if ctx.click(Target.image(Anchor(text="잡화 상인", ref=supply_img["补给商人名称"]))):  # 点击补给商人
            self.log.info("点击补给商人")
            ctx.wait(2)
        return Goto(SupplyWindow)


class SupplyWindow(State):
    name = "补给弹框"
    priority = 20
    signature = [Anchor(text="체력 회복제", ref=supply_img["耐力药水名称"])]
    is_supply = False     # 是否已进入过补给流程
    supply_done = False   # 补给是否已成功完成

    def supply(self, ctx: Ctx) -> bool:
        """
        补给流程：自动添加 → 判断按钮 → 购买。
        返回 True 表示购买成功，False 表示失败（已关窗）。
        """
        self.log.info("已打开补给弹框")
        self.is_supply = True

        for _ in range(3):
            if ctx.click(Target.image(Anchor(text="자동 담기", ref=supply_img["自动添加按钮"]))):
                self.log.info("点击自动添加")
                ctx.wait(5)
                break
            ctx.wait(2)
        else:
            self.log.error("无法找到自动添加按钮")
            return False

        brightness = ctx.brightness(ctx.calibrator.to_screen_region(
            Anchor(ref=supply_img["补给购买按钮"]).region))
        self.log.info(str(brightness))
        if brightness > 100:
            self.log.info("已添加补给，购买按钮可用")

            for _ in range(3):
                if ctx.click(Target.image(Anchor(ref=supply_img["补给购买按钮"]))):
                    self.log.info("点击补给购买按钮")
                    self.supply_done = True
                    break
                ctx.wait(2)
            else:
                ctx.click(Target.at(*SupplyWindowExit))
                self.log.error("无法点击购买按钮，退出补给弹框")
                return False
        else:
            ctx.click(Target.at(*SupplyWindowExit))
            self.log.warning("未添加补给，购买按钮不可用")
            return False

        return True

    @staticmethod
    def close_supply(ctx: Ctx) -> bool:
        """关闭补给窗口。"""
        if ctx.click(Target.at(*SupplyWindowExit)):
            return True
        return False

    def handle(self, ctx) -> Signal:
        # 补给已完成（被弹框中断后再次进入）→ 只关窗
        if self.supply_done:
            self.close_supply(ctx)
            self.log.info("补给已完成，关闭窗口")
            home = ctx.registry.get_instance(Home)
            home.state = HomeStateEnum.after_supply
            return Goto(Home)

        # 重入（弹框打断了流程）→ 关窗但不重试补给
        if self.is_supply:
            self.close_supply(ctx)

        self.supply(ctx)

        # 告知 Home 下一步是打开传送列表
        home = ctx.registry.get_instance(Home)
        home.state = HomeStateEnum.after_supply
        return Goto(Home)


class SupplyBuyConfirmWindow(State):
    name = "补给购买确认弹框"
    priority = 900
    signature = [Anchor(text="확인", ref=supply_img['补给确认按钮文字'])]

    def handle(self, ctx) -> Signal:

        for _ in range(3):
            if ctx.click(Target.image(Anchor(text="확인", ref=supply_img["补给确认按钮文字"]))):
                self.log.info("点击补给确认按钮")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.error("无法找到补给确认按钮")
            return Back()

        return Back()


def build_registry() -> StateRegistry:
    reg = build_base_registry()
    reg.flow_name = "补给流程"
    reg.register(Home())
    reg.register(AFK())
    reg.register(TPList())
    reg.register(TPConfirm())
    reg.register(NPCList())
    reg.register(SupplyWindow())
    reg.register(SupplyBuyConfirmWindow())

    # 每轮开始 / 死亡复活后重置流程状态
    def _reset_flow(_ctx=None):
        reg.get_instance(Home).state = HomeStateEnum.default
        reg.get_instance(AFK).auto_attack = False
        reg.get_instance(SupplyWindow).is_supply = False
        reg.get_instance(SupplyWindow).supply_done = False

    reg.reset_flow = _reset_flow
    reg.get_instance(Death).on_revive = _reset_flow

    return reg