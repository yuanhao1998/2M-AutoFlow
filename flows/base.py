# @Create  : 2026/7/20 01:11
# @Author  : great
# @Remark  : 存放所有高优先级的操作，例如：死亡复活、弹框消除等
from __future__ import annotations

import json
import sys
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fsm.registry import StateRegistry

sys.path.insert(0, str(Path(__file__).parent.parent))

from anchors.anchors import ImageDir, Anchor
from conf.env import get_env
from fsm.state import State, Signal, Back, Stay, Done
from target.target import Target


class BaseImages(ImageDir):
    path = "images/base"


base_img = BaseImages()


class Death(State):
    name = "死亡界面"
    priority = 1000
    signature = [Anchor(ref=base_img["复活按钮"])]

    # ---- 配置（按需修改） ----
    WECOM_WEBHOOK: str = ""          # 从 .env 读取，类属性可覆盖
    MAX_DEATH_PER_DAY: int = 5       # 单台云机每日复活上限
    # -----------------------

    on_revive: Callable | None = None   # 复活后回调，由业务流程设置

    @classmethod
    def _webhook(cls) -> str:
        return cls.WECOM_WEBHOOK or get_env("WECOM_WEBHOOK")

    def handle(self, ctx) -> Signal:
        self.log.info("检测到死亡界面")

        # 1. 识别云机名称
        device = self._read_device_name(ctx)
        self.log.info("当前云机: %s", device)

        # 2. 查询今日死亡次数
        death_file = Path("images/base") / f"death-{date.today().isoformat()}.json"
        count = self._get_death_count(death_file, device)
        self.log.info("今日已死亡 %d 次（上限 %d）", count, self.MAX_DEATH_PER_DAY)

        # 3. 判断是否复活
        if count < self.MAX_DEATH_PER_DAY:
            self._record_death(death_file, device)
            if ctx.click(Target.image(Anchor(ref=base_img["复活按钮"]))):
                self.log.info("点击复活按钮")
            ctx.wait(2)
            # 复活后重置流程状态（死亡 = 流程从头开始）
            if self.on_revive:
                self.on_revive(ctx)
        else:
            self.log.warning("已达今日复活上限，不再点击")
            self._send_wecom_alert(device, count)
            ctx.wait(5)

        return Back()

    # ---- 私有方法 ----

    def _read_device_name(self, ctx) -> str:
        """识别云机名称区域的文字。"""
        r = ctx.calibrator.to_screen_region(base_img["云机名称识别区域"].region)
        text = ctx.read_text(r)
        return text.strip() or "未知云机"

    @staticmethod
    def _get_death_count(death_file: Path, device: str) -> int:
        if not death_file.exists():
            return 0
        try:
            data = json.loads(death_file.read_text(encoding="utf-8"))
            return data.get(device, 0)
        except Exception:
            return 0

    @staticmethod
    def _record_death(death_file: Path, device: str) -> None:
        data: dict = {}
        if death_file.exists():
            try:
                data = json.loads(death_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        data[device] = data.get(device, 0) + 1
        death_file.parent.mkdir(parents=True, exist_ok=True)
        death_file.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def _send_wecom_alert(self, device: str, count: int) -> None:
        """通过企业微信 webhook 发送告警。"""
        webhook = self._webhook()
        if not webhook:
            self.log.warning("企业微信 webhook 未配置，跳过推送")
            return
        payload = json.dumps({
            "msgtype": "text",
            "text": {
                "content": f"⚠️ 云机 [{device}] 今日死亡已达 {count} 次，请人工处理！"
            }
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                webhook,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            self.log.info("企业微信告警已发送")
        except Exception as e:
            self.log.error("企业微信推送失败: %s", e)


class NetworkErrorWindow(State):
    name = "网络错误提示弹框"
    priority = 999
    signature = [
        Anchor(text="에러가 발생했습니다.", ref=base_img["网络错误提示文字"]),
        Anchor(text="100113", ref=base_img["网络错误代码"])
    ]

    def handle(self, ctx) -> Signal:
        for _ in range(5):
            if ctx.click(Target.image(Anchor(text="확인", ref=base_img["网络错误确认按钮"]))):
                self.log.info("关闭网络错误弹框成功")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.info("关闭网络错误弹框失败")

        return Back()


class TipsWindow(State):
    name = "左上角提示框"
    priority = 998
    signature = [Anchor(text="확인", ref=base_img["提示框确认按钮"])]

    def handle(self, ctx) -> Signal:
        for _ in range(5):
            if ctx.click(Target.image(Anchor(text="확인", ref=base_img["提示框确认按钮"]))):
                self.log.info("关闭左上角提示框成功")
                ctx.wait(2)
                break
            ctx.wait(2)
        else:
            self.log.info("关闭左上角提示框失败")

        return Back()


class LastDeviceWindow(State):
    name = "最后一台云机弹框"
    priority = 997
    # 用 capture_anchor.py 截取弹框中的文字区域，填入下方：
    signature = [Anchor(ref=base_img["最后一台云机提示文字"])]

    def handle(self, ctx) -> Signal:
        self.log.info("检测到最后一台云机，停止流程")
        ctx.run_state.stopped = True
        return Done()


def build_base_registry() -> StateRegistry:
    reg = StateRegistry()
    reg.register(Death())
    reg.register(NetworkErrorWindow())
    reg.register(TipsWindow())
    reg.register(LastDeviceWindow())
    return reg
