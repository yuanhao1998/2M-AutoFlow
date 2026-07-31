# @Create  : 2026/7/30 08:11
# @Author  : great
# @Remark  : 地牢
from anchors.anchors import ImageDir, Anchor
from flows.base import build_base_registry
from fsm.context import Ctx
from fsm.registry import StateRegistry
from fsm.state import State, Signal, Goto, Stay, Done
from target.target import Target


class BaseImages(ImageDir):
    path = "images/base"

class DungeonImages(ImageDir):
    path = "images/dungeon"

base_img = BaseImages()
dungeon_img = DungeonImages()

MenuButton = (4780, 196)       # 右上角主菜单按钮
Battle = (2911, 693)  # 战斗之岛


class Home(State):
    name = "主界面"
    signature = [Anchor(ref=base_img["金币图案判断"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        if ctx.click(Target.at(*MenuButton)):
            self.log.info("点击右上角菜单按钮")
            return Goto(Menu)
        return Stay()


class Menu(State):
    name = "主菜单"
    priority = 15
    signature = [Anchor(text="던전",  ref=dungeon_img["地牢菜单文字"])]

    def handle(self, ctx: Ctx) -> Signal:
        for _ in range(3):
            if ctx.click(Target.image(Anchor(text="던전",  ref=dungeon_img["地牢菜单文字"]))):
                self.log.info("点击地牢按钮")
                ctx.wait(2)
                return Goto(DungeonWindow)
            ctx.wait(2)
        else:
            self.log.warning("无法找到副本按钮")
        return Stay()


class DungeonWindow(State):
    name = "地牢列表"
    signature = [Anchor(text="즐겨찾기", ref=dungeon_img["地牢收藏夹页签文字"])]

    def handle(self, ctx: Ctx) -> Signal:

        ctx.wait(2)
        if ctx.click(Target.image(Anchor(text="즐겨찾기", ref=dungeon_img["地牢收藏夹页签文字"]))):
            self.log.info("点击地牢收藏夹成功")
            return Goto(CollectionDungeon)

        return Stay()


class CollectionDungeon(State):
    name = "地牢收藏夹页签"
    signature = [Anchor(text="격전의 섬", ref=dungeon_img["收藏夹卷本名称"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        if ctx.click(Target.image(Anchor(text="입장하기", ref=dungeon_img["地牢确认按钮文字"]))):
            self.log.info("点击地牢确认按钮成功")

        return Stay()


class LevelSelectWindow(State):
    name = "等级选择弹框"
    signature = [Anchor(ref=dungeon_img["60级确认按钮"])]

    def handle(self, ctx: Ctx) -> Signal:
        ctx.wait(2)
        ctx.click(Target.image(Anchor(ref=dungeon_img["60级确认按钮"])))
        ctx.wait(3)
        return Done()


def build_registry() -> StateRegistry:
    reg = build_base_registry()
    reg.flow_name = "地牢卷本流程"
    reg.register(Home())
    reg.register(Menu())
    reg.register(DungeonWindow())
    reg.register(CollectionDungeon())
    reg.register(LevelSelectWindow())

    return reg