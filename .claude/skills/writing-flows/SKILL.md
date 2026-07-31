---
name: writing-flows
description: Use when the user asks to create a new game automation flow, write a flow file, add a business process, or implement game UI automation. Triggers on requests like "写一个xxx流程", "新增一个流程", "create a flow for...", or when working in flows/ directory.
---

# 编写游戏自动化流程

## 概述

本 skill 编码了 `game-auto` 项目中编写业务流程（flow）的全部约定、模式和样板代码。遵循此 skill 可生成风格一致、符合架构契约、可直接运行的流程文件。

核心原则：**所有坐标和区域都是作图坐标，运行时的屏幕像素换算由 Calibrator 自动完成。**

## 使用时机

- 用户要求新增一个游戏自动化流程
- 用户在 `flows/` 目录下编写新文件
- 用户描述了游戏中的一系列界面操作需要自动化
- 补全未完成的 flow 文件

## 前置信息收集

在生成代码之前，必须向用户确认以下信息（如果用户没有提供）：

1. **流程名称**（中文，如"补给流程"）和对应的英文模块名（如 `supply`）
2. **涉及的游戏界面**及其识别方式（截图中的哪个图标/文字能唯一标识该界面）
3. **操作步骤**：每个界面上做什么操作（点击哪个按钮、等待多久）
4. **锚点图来源**：哪些图已存在于 `images/` 下，哪些需要新采集
5. **是否有特殊状态**：需要跨状态传递的信息、需要在多轮间重置的状态

## 完整文件模板

```python
# @Create  : YYYY/M/D HH:MM
# @Author  : great
# @Remark  : 流程的一句话描述
from __future__ import annotations

from anchors.anchors import Anchor, ImageDir
from fsm.context import Ctx
from fsm.state import State, Signal, Goto, Back, Done, Stay
from fsm.registry import StateRegistry
from target.target import Target


# ---- 1. 声明参考图目录 ----
class XxxImages(ImageDir):
    path = "images/xxx"          # 本流程专用锚点图目录

class BaseImages(ImageDir):
    path = "images/base"

base_img = BaseImages()
xxx_img = XxxImages()


# ---- 2. 坐标常量（作图坐标） ----
# 命名：PascalCase，注释说明用途
SomeButton = (1234, 567)


# ---- 3. 枚举（如有需要） ----
from enum import Enum

class SomeEnum(int, Enum):
    state_a = 0
    state_b = 1


# ---- 4. 各界面 State ----
class Home(State):
    name = "首页"
    priority = 10
    signature = [Anchor(ref=base_img["某个锚点图"])]

    def handle(self, ctx: Ctx) -> Signal:
        # 操作逻辑
        return Goto(NextState)


class SomePopup(State):
    name = "某弹框"
    priority = 900          # 弹框：900+
    signature = [Anchor(text="확인", ref=xxx_img["某按钮区域"])]

    def handle(self, ctx: Ctx) -> Signal:
        # 关闭弹框
        return Back()


# ---- 5. 组装注册表 ----
def build_registry() -> StateRegistry:
    from flows.base import build_base_registry
    reg = build_base_registry()
    reg.flow_name = "流程中文名称"
    reg.register(Home())
    reg.register(SomePopup())
    # ... 注册所有 State

    # 多轮重置（如有可变状态）
    def _reset_flow(_ctx=None):
        reg.get_instance(Home).some_attr = default_value

    reg.reset_flow = _reset_flow
    reg.get_instance(Death).on_revive = _reset_flow

    return reg
```

## 模式目录

### ImageDir 声明

```python
class XxxImages(ImageDir):
    path = "images/xxx"

class BaseImages(ImageDir):
    path = "images/base"

base_img = BaseImages()
xxx_img = XxxImages()
```

注意：`images/base/` 是通用锚点图（齿轮图标、金币图标、复活按钮等），始终声明 `BaseImages`。

### Anchor（签名锚点）的写法

```python
# 1. 图像全屏匹配 — 最常用，搜索区域从 regions.yaml 自动继承
Anchor(ref=img["图名"])

# 2. 文字 OCR 匹配 — 在 regions.yaml 限定的区域内搜索韩文
Anchor(text="한글", ref=img["区域名"])

# 3. 文字 + 显式区域 — 不用 regions.yaml，直接写区域
Anchor(text="확인", region=[100, 200, 300, 400])

# 4. 自定义阈值
Anchor(ref=img["图名"], threshold=0.9)
```

**⚠️ 文字锚点必须限定搜索区域！** `Anchor(text="출석")` 不带 ref/region 会触发全屏 OCR，速度极慢且容易误匹配。始终通过 `ref=img["区域名"]`（走 regions.yaml）或显式 `region=[l,t,r,b]` 限定范围。

### Target（点击目标）的三种写法

```python
# 1. 图像锚点定位 — 匹配锚点图，点击其中心（首选）
Target.image(Anchor(ref=img["按钮"]))

# 2. 相对偏移 — 匹配锚点后点击锚点中心 + (dx,dy)×scale
Target.rel(Anchor(ref=img["参考点"]), dx=10, dy=-5)

# 3. 绝对作图坐标 — 仅用于位置完全固定的按钮
Target.at(x, y)         # 引用上面定义的坐标常量
```

### State.handle() 常用模式

#### 模式 A：简单导航（点击 → 等待 → 跳转）

```python
def handle(self, ctx: Ctx) -> Signal:
    ctx.click(Target.at(*ButtonCoord))
    self.log.info("点击了某按钮")
    ctx.wait(2)
    return Goto(NextState)
```

#### 模式 B：图像锚点点击（带重试）

```python
def handle(self, ctx: Ctx) -> Signal:
    for _ in range(3):
        if ctx.click(Target.image(Anchor(ref=img["按钮"]))):
            self.log.info("点击成功")
            ctx.wait(2)
            break
        ctx.wait(2)
    else:
        self.log.error("点击失败")
        return Done()
    return Goto(NextState)
```

#### 模式 C：文字锚点点击（带重试）

```python
def handle(self, ctx: Ctx) -> Signal:
    for _ in range(3):
        if ctx.click(Target.image(Anchor(text="한글", ref=img["区域"]))):
            self.log.info("点击成功")
            ctx.wait(2)
            break
        ctx.wait(2)
    else:
        self.log.error("点击失败")
        return Done()
    return Goto(NextState)
```

#### 模式 D：弹框关闭（高 priority，返回 Back）

```python
class SomePopup(State):
    name = "某弹框"
    priority = 900
    signature = [Anchor(text="확인", ref=img["弹框确认按钮"])]

    def handle(self, ctx: Ctx) -> Signal:
        for _ in range(5):
            if ctx.click(Target.image(Anchor(text="확인", ref=img["弹框确认按钮"]))):
                self.log.info("关闭弹框")
                ctx.wait(2)
                break
            ctx.wait(2)
        return Back()
```

#### 模式 E：自定义 match（OR 逻辑匹配）

```python
def match(self, ctx: Ctx) -> bool:
    """A 或 B 任一命中即为当前界面。"""
    a = ctx.find_anchor(Anchor(text="안전", ref=base_img["地图区域提示"]))
    b = ctx.find_anchor(Anchor(text="잡화 상인", ref=img["商人名称"]))
    return a.matched or b.matched

# 此时 signature 设为空列表
signature = []
```

#### 模式 F：亮度判断（检测按钮是否可用）

```python
brightness = ctx.brightness(
    ctx.calibrator.to_screen_region(Anchor(ref=img["按钮"]).region)
)
if brightness > 100:
    # 按钮可用（亮色）
    ctx.click(Target.image(Anchor(ref=img["按钮"])))
else:
    # 按钮不可用（暗色）
    self.log.warning("按钮不可用")
```

#### 模式 G：OCR 读取文字

```python
r = ctx.calibrator.to_screen_region(img["某区域"].region)
text = ctx.read_text(r)
self.log.info("识别结果: %s", text)

# 带白名单的精确识别（数字和符号）
text = ctx.read_text(region, allowlist="+0123456789")
```

#### 模式 H：跨 State 修改属性

```python
other = ctx.registry.get_instance(OtherState)
other.some_attr = new_value
```

#### 模式 I：带状态枚举的复杂界面

```python
class Home(State):
    name = "主城"
    priority = 10
    signature = []
    state = HomeStateEnum.default    # 可变状态属性

    def match(self, ctx: Ctx) -> bool:
        a = ctx.find_anchor(Anchor(text="안전", ref=base_img["地图提示"]))
        b = ctx.find_anchor(Anchor(text="상인", ref=img["商人名称"]))
        return a.matched or b.matched

    def handle(self, ctx: Ctx) -> Signal:
        if self.state == HomeStateEnum.default:
            # 第一次进入的行为
            ...
            return Goto(A)
        elif self.state == HomeStateEnum.after_something:
            # 第二次进入的行为
            ...
            return Goto(B)
        return Stay()
```

#### 模式 J：点击后验证（等锚点出现）

```python
def handle(self, ctx: Ctx) -> Signal:
    for _ in range(3):
        ctx.click(Target.at(*Coord))
        ctx.wait(2)
        if ctx.find_anchor(Anchor(ref=img["期望出现的界面元素"])).matched:
            self.log.info("操作成功，已进入目标界面")
            break
        ctx.wait(2)
    else:
        self.log.error("操作失败")
        return Done()
    return Goto(NextState)
```

### build_registry 标准模式

```python
def build_registry() -> StateRegistry:
    from flows.base import build_base_registry, Death   # Death 必须导入！
    reg = build_base_registry()       # 1. 先拿基础注册表（含 Death、弹框等）
    reg.flow_name = "流程中文名称"     # 2. 设置流程名（用于日志文件分离）

    # 3. 注册所有 State（顺序无关，priority 决定识别优先级）
    reg.register(Home())
    reg.register(SomePopup())
    reg.register(OtherState())

    # 4. 多轮重置（如有可变状态）—— 两行缺一不可！
    def _reset_flow(_ctx=None):
        reg.get_instance(Home).state = HomeStateEnum.default
        reg.get_instance(SomeState).some_attr = False

    reg.reset_flow = _reset_flow
    reg.get_instance(Death).on_revive = _reset_flow   # ⚠️ 必须！死亡复活后也要重置

    return reg
```

**关键规则：**
- 只要定义了 `_reset_flow`，就必须同时设置 `reg.reset_flow` 和 `Death.on_revive`
- `Death` 必须从 `flows.base` 导入（不是 `from flows.base import Death`，而是在 build_registry 内部 import）
- 没有可变状态的简单流程可省略这两行

## 锚点图依赖规则

`img["key"]` 能正常工作的前提是以下二者之一成立：

1. `images/xxx/key.png`（或 .jpg/.bmp）文件存在
2. `images/xxx/regions.yaml` 中有 `key: [...]` 条目（此时即使没有对应图片文件，也会生成一个占位 ImageRef）

**注意**：条件 2 仅对**文字锚点**有意义（文字锚点只需 region，不读图片文件）。图像锚点必须有实际图片文件。

**生成代码时的约束**：
- 如果流程引用了尚未采集的图片 → **先提醒用户需要采集**，代码中仍可写引用
- 如果 `images/xxx/` 目录尚不存在 → **同时创建目录和一个空的 `regions.yaml`**，在其中预填所有需要的 key
- 文字锚点尽量走 `regions.yaml` 管理区域，比硬编码 `region=[...]` 更易维护

```bash
# 创建新流程的图片目录和初始 regions.yaml
mkdir -p images/新流程名
touch images/新流程名/regions.yaml
```

## 坐标系契约（必须遵守）

- **flows 中所有坐标都是"作图坐标"**（采集锚点图时的屏幕分辨率）
- 坐标换算由 `Calibrator.to_screen()` / `to_screen_region()` 自动完成
- `Anchor.region` 是作图坐标，`Ctx.find_anchor()` 内部已做转换
- `Target.at(x, y)` 是作图坐标，`Target.resolve()` 内部已做转换
- **严禁**在 flows 中手动做坐标换算或使用非等比缩放

## Priority 约定

| 范围 | 用途 | 示例 |
|------|------|------|
| 0 | 默认，普通界面 | Home, Menu, Shop |
| 10-20 | 子界面/窗口 | SupplyWindow, TPList |
| 100-200 | 轻量弹框/提示 | TipsWindow |
| 900-999 | 重要弹框 | NetworkErrorWindow, SupplyBuyConfirm |
| 1000+ | 最关键异常 | Death（死亡复活） |

## 变量命名约定

- 坐标常量：`PascalCase`，如 `GoHome`、`SupplyWindowExit`、`OpenNPCList`
- State 类：`PascalCase`，如 `Home`、`AFK`、`SupplyWindow`
- 图片实例：`snake_case`，如 `base_img`、`supply_img`、`redefine_img`
- State 属性：`snake_case`，如 `auto_attack`、`is_supply`、`supply_done`

## 日志约定

- State 内使用 `self.log.info()` / `self.log.error()` / `self.log.warning()`（自动带 `[StateName]` 前缀）
- 消息用简体中文
- 关键节点（点击、跳转、错误）都要打日志

## 常见错误

| 错误 | 正确做法 |
|------|---------|
| 忘记 `from __future__ import annotations` | 始终写在文件第一行 import 之前 |
| 忘记导入 `build_base_registry` | build_registry() 第一行 `from flows.base import build_base_registry` |
| 忘记设置 `reg.flow_name` | 始终设中文流程名，用于日志分文件 |
| 忘记 `reset_flow` | 有可变属性的 State 必须定义 reset_flow 并绑定到 Death.on_revive |
| 坐标混用（在 flows 里写屏幕 px） | flows 里只写作图坐标，换算由引擎完成 |
| `Anchor.ref` 引用不存在的图片 | 检查 `images/xxx/` 下是否有对应文件，或 regions.yaml 中是否有对应 key |
| priority 设置不当 | 弹框/异常 ≥ 900，死亡 1000+，普通界面 0-20 |
| 使用 `logging.info()` 而非 `self.log.info()` | State 内一律用 `self.log`（会自动注入 State 名） |
| click 后忘记 wait | 界面过渡需要时间，click 后至少 `ctx.wait(1-2)` |
| `Target.at()` 传入的是屏幕坐标 | `Target.at()` 接收作图坐标，由引擎换算 |

## 参考实现

- `flows/supply.py` — 最完整的参考：含 OR 匹配、状态枚举、亮度判断、跨 State 通信、多重试
- `flows/redefine.py` — 网格扫描 + OCR 强化值识别 + 双击
- `flows/base.py` — 高优先级异常处理模板（死亡复活、弹框关闭、企业微信告警）
- `docs/flows.md` — 概念详解和快速开始指南

## 完成前强制检查清单

生成流程文件后，逐项验证：

1. ☐ `from __future__ import annotations` 在第一行
2. ☐ `build_registry()` 内部 `from flows.base import build_base_registry, Death`
3. ☐ `reg.flow_name = "中文名称"` 已设置
4. ☐ 有可变 State 属性？→ `reg.reset_flow = _reset_flow` **且** `reg.get_instance(Death).on_revive = _reset_flow`
5. ☐ 所有 `Anchor(text=...)` 都有 `ref` 或 `region`（禁止无约束全屏 OCR）
6. ☐ 所有 `img["xxx"]` 引用的 key 在 `images/xxx/` 下存在对应图片文件或 `regions.yaml` 条目
7. ☐ State 内日志使用 `self.log.info()` 而非 `logging.info()`
8. ☐ Priority：弹框 900+，死亡 1000+，普通界面 0-20
9. ☐ 每个 click 后都有 `ctx.wait()`
10. ☐ `Target.at()` 传入的是作图坐标，非屏幕像素
