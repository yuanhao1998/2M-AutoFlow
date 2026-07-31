"""game-auto 统一入口。

用法:
    python run.py [flow_name] [--repeat N]

示例:
    python run.py                # 默认跑冒烟流程
    python run.py delegate       # 跑委托流程
    python run.py supply --repeat 73   # 跑补给流程，73 个账户
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ruamel.yaml import YAML

from conf.log import register_log
from anchors.anchors import Anchor, ImageDir
from calib.calibrator import Calibrator
from fsm.context import Ctx, RunState
from fsm.engine import Engine
from runner.runner import FlowRunner
from target.target import Target

logger = logging.getLogger(__name__)

# ---- 云机切换 ----
SWITCH_CLICK = (5075, 1227)
SWITCH_WAIT = 5.0


def _load_cfg() -> dict:
    return YAML(typ="safe").load(open("conf/config.yaml", encoding="utf-8"))


def main() -> None:
    register_log()

    parser = argparse.ArgumentParser(description="game-auto 视觉自动化引擎")
    parser.add_argument("flow", nargs="?", default="smoke",
                        help="流程名称（对应 flows/ 下的模块，默认 smoke）")
    parser.add_argument("--repeat", type=int, default=None,
                        help="循环轮数（覆盖 config.yaml 中 stats.total_accounts）")
    args = parser.parse_args()

    cfg = _load_cfg()

    # ---- 标定 ----
    c = cfg["calib"]
    calib_img = ImageDir("images/base")

    # 手动标定：config 中 manual_scale 和 manual_origin 均非 null 时跳过自动标定
    manual_scale = c.get("manual_scale")
    manual_origin = c.get("manual_origin")
    if manual_origin is not None:
        manual_origin = tuple(manual_origin)

    calibrator = Calibrator(
        Anchor(ref=calib_img["标定区域"]),
        tuple(c["anchor_authoring_topleft"]),
        threshold=float(c.get("threshold", 0.80)),
        manual_scale=manual_scale,
        manual_origin=manual_origin,
    )

    # ---- 加载流程模块 ----
    flow = __import__(f"flows.{args.flow}", fromlist=["build_registry"])
    registry = flow.build_registry()

    # ---- 装配 ----
    run_state = RunState()
    ctx = Ctx(calibrator, run_state)
    eng_cfg = cfg.get("engine", {})
    engine = Engine(registry, ctx,
                    max_steps=int(eng_cfg.get("max_steps", 200)),
                    max_unknown=int(eng_cfg.get("max_unknown", 5)))

    # ---- 切换云机 ----
    def switch_device() -> None:
        logger.info("切换云机 → 点击 %s", SWITCH_CLICK)
        ctx.click(Target.at(*SWITCH_CLICK))
        ctx.wait(SWITCH_WAIT)

    # ---- 单轮 = 跑完一个账户 ----
    def one_round() -> None:
        ctx.refresh_screenshot()
        if not calibrator.is_valid():
            if not calibrator.calibrate(ctx.screen_bgr):
                logger.error("标定失败，跳过本轮")
                return
        ok = engine.run_until(goal=None)
        logger.info("本轮结果: %s", "完成" if ok else "未完成")

    # repeat: 命令行指定 > config 配置 > 默认无限（靠 LastDeviceWindow 弹框停止）
    repeat = args.repeat
    if repeat is None:
        repeat = int(cfg.get("stats", {}).get("total_accounts", 0)) or 9999
    runner = FlowRunner(run_state, repeat=repeat,
                        hotkeys=cfg.get("hotkeys"),
                        switch=switch_device)
    runner.run(one_round)


if __name__ == "__main__":
    main()
