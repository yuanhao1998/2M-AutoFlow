"""参考图管理器：通过 img["key"] 获取 ImageRef；Anchor 声明匹配条件。

region 约定：每个图片目录可含一个 regions.yaml 来集中管理搜索区域，
ImageRef 自动从中读取，Anchor 默认继承 ref.region。显式传参则覆盖。

regions.yaml 格式:
    # images/xxx/regions.yaml
    图片名: [left, top, right, bottom]   # 作图坐标搜索区域（图像锚点）
    文字锚点key: [left, top, right, bottom]  # 文字锚点也可通过 yaml 管理区域
    全屏搜的图: null                     # null = 全屏搜索
    不必声明: 跳过                        # 等同于 null = 全屏搜索

用法:
    class MyImages(ImageDir):
        path = "images/xxx"
    img = MyImages()

    # 图像锚点：img["key"] → ImageRef
    Anchor(ref=img["home_sig"])

    # 文字锚点：regions.yaml 中的 key 也可通过 img["key"] 获取 region
    # regions.yaml: 确认按钮: [100, 200, 300, 400]
    Anchor(text="확인", ref=img["确认按钮"])

    # 等同于手写:
    Anchor(text="확인", region=[100, 200, 300, 400])

    # 也可直接实例化:
    d = ImageDir("images/store")
    d["store_icon"]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ImageRef:
    """对参考图片文件的轻量引用，自动从同目录 regions.yaml 读取搜索区域。"""

    __slots__ = ("path", "_regions")

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._regions: dict | None = None  # 懒加载同目录 regions.yaml

    def __repr__(self) -> str:
        return f"ImageRef({self.path})"

    def __fspath__(self) -> str:
        return str(self.path)

    @property
    def region(self) -> tuple[int, int, int, int] | None:
        """从同目录 regions.yaml 读取的搜索区域，未声明则返回 None（全屏搜索）。"""
        if self._regions is None:
            self._regions = _load_regions(self.path.parent)
        v = self._regions.get(self.path.stem)
        return tuple(int(x) for x in v) if v is not None else None


def _load_regions(directory: Path) -> dict:
    """加载目录下的 regions.yaml，不存在或损坏则返回空 dict。"""
    yf = directory / "regions.yaml"
    if not yf.is_file():
        return {}
    try:
        from ruamel.yaml import YAML
        yaml = YAML(typ="safe")
        # 编码回退：UTF-8 → GBK → GB2312（Windows 中文环境可能产生 GBK 文件）
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                data = yaml.load(yf.read_text(encoding=enc)) or {}
                return dict(data)
            except (UnicodeDecodeError, LookupError):
                continue
        return {}
    except Exception:
        return {}


def _write_regions(yf: Path, data: dict) -> None:
    """写入 regions.yaml，固定格式: key: [v1, v2, v3, v4] 或 key: null。"""
    lines: list[str] = []
    for k, v in data.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, list):
            inner = ", ".join(str(x) for x in v)
            lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {v}")
    yf.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ImageDir:
    """参考图管理器：扫描目录下所有图片和 regions.yaml，通过 img["key"] 获取 ImageRef。

    子类声明:
        class StoreImages(ImageDir):
            path = "images/store"
        img = StoreImages()
        img["store_icon"]  # → ImageRef("images/store/store_icon.png")

    直接实例化:
        d = ImageDir("images/store")
        d["store_icon"]
    """

    path: str = ""

    def __init__(self, path: str = "") -> None:
        self._refs: dict[str, ImageRef] = {}
        dir_path = path or self.__class__.path
        if dir_path:
            self._discover(dir_path)

    def _discover(self, dir_path: str) -> None:
        base = Path(dir_path)
        if not base.is_dir():
            return
        # 1. 图片文件 → ImageRef
        for f in sorted(base.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
                self._refs[f.stem] = ImageRef(f)
        # 2. regions.yaml 中无对应图片的 key → ImageRef（供文字锚点用）
        regions = _load_regions(base)
        for key in regions:
            if key not in self._refs:
                self._refs[key] = ImageRef(base / f"{key}.png")

    def __getitem__(self, key: str) -> ImageRef:
        return self._refs[key]

    def __contains__(self, key: str) -> bool:
        return key in self._refs

    def __len__(self) -> int:
        return len(self._refs)

    def __iter__(self):
        return iter(self._refs)

    def __repr__(self) -> str:
        return f"ImageDir({len(self._refs)} refs)"

    def list_all(self) -> list[ImageRef]:
        return list(self._refs.values())

    def validate(self) -> list[str]:
        missing: list[str] = []
        for ref in self._refs.values():
            if not ref.path.exists():
                missing.append(str(ref.path))
        return missing


def _append_region(save_path: Path, region: tuple[int, int, int, int]) -> None:
    """在 save_path 所在目录的 regions.yaml 中追加一行。供 capture_anchor 调用。"""
    yf = save_path.parent / "regions.yaml"

    if yf.is_file():
        data = _load_regions(save_path.parent)
    else:
        data = {}

    data[save_path.stem] = list(region)
    _write_regions(yf, data)


def _append_text_region(save_dir: Path, key: str,
                        region: tuple[int, int, int, int]) -> None:
    """仅写入 regions.yaml，不保存图片文件（供文字锚点用）。供 capture_anchor 调用。"""
    yf = Path(save_dir) / "regions.yaml"

    data = _load_regions(Path(save_dir)) if yf.is_file() else {}
    data[key] = list(region)
    _write_regions(yf, data)


@dataclass(frozen=True)
class Anchor:
    """匹配锚点：图像模板匹配 或 OCR 文字定位。

    图像模式（默认）：ref 指向参考图，通过 cv2.matchTemplate 匹配。
    文字模式：设置 text 为非空字符串，通过 EasyOCR 在 region 内定位文字。

    region 未显式传入时自动从 ref.region（regions.yaml）继承。
    显式传 region 则覆盖 yaml 值。两者均为 None = 全屏搜索。
    """

    ref: ImageRef | None = None
    region: tuple[int, int, int, int] | None = None
    threshold: float = 0.85
    text: str | None = None

    def __post_init__(self) -> None:
        if self.ref is not None and self.region is None:
            object.__setattr__(self, "region", self.ref.region)
