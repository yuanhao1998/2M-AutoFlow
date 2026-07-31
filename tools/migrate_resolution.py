"""分辨率迁移工具：引导式重新采集所有锚点图到新分辨率目录。

用法:
    uv run tools/migrate_resolution.py <新目录>  [--source-dir images]

工作流程:
    1. 读取源目录下所有 images/*/regions.yaml，提取锚点列表
    2. 逐个引导：显示名称 → 手动切到对应界面 → 按 Enter 截图
       → 框选区域 → 弹窗确认名称（已预填）→ Enter 保存
    3. 全部完成后，新目录中即有完整的锚点图和 regions.yaml

    运行前请先退出全屏应用或确保能正常截屏。

快捷键:
    Enter  = 截图 / 确认保存
    R      = 保存当前框选
    ESC    = 跳过当前锚点 / 退出
    C      = 复制坐标
    Space  = 生成代码片段
"""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageGrab, ImageTk
from ruamel.yaml import YAML

# ---- 全局 F5 热键（与 capture_anchor.py 相同） ----
_F5_KEYCODE = 96
_tap_instance: "MigrateTool | None" = None


def _tap_callback(_proxy, event_type, event, _refcon):
    import Quartz
    if event_type == Quartz.kCGEventKeyDown:
        code = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode)
        if code == _F5_KEYCODE and _tap_instance is not None:
            _tap_instance.root.event_generate("<<Capture>>", when="tail")
    return event


def _run_event_tap():
    import Quartz
    mask = 1 << Quartz.kCGEventKeyDown
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionDefault,
        mask, _tap_callback, None)
    if tap is None:
        return
    source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopDefaultMode)
    Quartz.CFRunLoopRun()


def _read_yaml_file(path: Path) -> dict:
    """读取 YAML 文件，编码回退：UTF-8 → GBK → GB2312。"""
    yaml = YAML(typ="safe")
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            return yaml.load(path.read_text(encoding=enc)) or {}
        except (UnicodeDecodeError, LookupError):
            continue
    return {}


def load_all_regions(images_dir: Path) -> dict[str, dict[str, list | None]]:
    """加载 images/ 下所有 regions.yaml。返回 {dir_name: {key: region}}。"""
    result: dict[str, dict[str, list | None]] = {}
    for rf in sorted(images_dir.rglob("regions.yaml")):
        dir_name = str(rf.parent.relative_to(images_dir))
        data = _read_yaml_file(rf)
        result[dir_name] = {
            k: (list(v) if v is not None else None) for k, v in data.items()
        }
    return result


class MigrateTool:
    def __init__(self, target_dir: str, source_dir: str = "images"):
        self._target = Path(target_dir)
        self._source = Path(source_dir) if isinstance(source_dir, str) else source_dir
        # 读取源锚点列表
        self._all_regions = load_all_regions(self._source)
        # 展平为任务队列: [(subdir, key, region), ...]
        self._queue: list[tuple[str, str, list | None]] = []
        for subdir, regions in self._all_regions.items():
            for key, region in regions.items():
                self._queue.append((subdir, key, region))
        self._current = 0

        # tkinter 初始化
        self.root = tk.Tk()
        self.root.title(f"分辨率迁移 — 目标: {self._target}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.pil_image = Image.new("RGB", (800, 600), (40, 40, 40))
        self.orig_w, self.orig_h = 800, 600
        self.scale = 1.0

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(screen_w, int(screen_w * 0.9))
        win_h = min(screen_h, int(screen_h * 0.85))
        self.scale = min(win_w / self.orig_w, win_h / self.orig_h)

        self._make_photo()
        canvas_w = min(self.scaled_w, win_w)
        canvas_h = min(self.scaled_h, win_h)

        frame = tk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(frame, width=canvas_w, height=canvas_h,
                                cursor="cross",
                                scrollregion=(0, 0, self.scaled_w, self.scaled_h))
        self.canvas.grid(row=0, column=0, sticky=tk.NSEW)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW, tags="bg")

        # 状态栏
        self.info_var = tk.StringVar(value="按 Enter 截取屏幕开始采集")
        tk.Label(self.root, textvariable=self.info_var, font=("", 13), pady=6).pack()

        # 进度栏
        self.progress_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self.progress_var, font=("", 12),
                fg="blue", pady=2).pack()

        # 提示文字
        tk.Label(self.root,
                text="Enter=截图  R=保存  ESC=跳过  Space=生成代码  C=复制坐标",
                font=("", 11), fg="gray").pack(pady=(0, 4))

        # 坐标输入框
        input_frame = tk.Frame(self.root)
        input_frame.pack(pady=(0, 4))
        tk.Label(input_frame, text="坐标:", font=("", 11)).pack(side=tk.LEFT)
        self.coord_entry = tk.Entry(input_frame, width=40, font=("", 11))
        self.coord_entry.pack(side=tk.LEFT, padx=(4, 4))
        self.coord_entry.bind("<Return>", self._on_coord_enter)
        tk.Label(input_frame, text="例: (100,200,300,400)",
                font=("", 10), fg="gray").pack(side=tk.LEFT)

        self.start_x = self.start_y = None
        self.rect_id = None
        self._saved_region = None

        # 绑定
        self.canvas.bind("<Motion>", self.on_move)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Return>", lambda e: self._capture_and_load())
        self.root.bind("<r>", lambda e: self._save_current())
        self.root.bind("<Escape>", lambda e: self._skip_current())
        self.root.bind("<space>", lambda e: self._gen_code())
        self.root.bind("<c>", lambda e: self._copy_region())

        # 热键
        global _tap_instance
        _tap_instance = self
        self.root.event_add("<<Capture>>", "None")
        try:
            import Quartz
            threading.Thread(target=_run_event_tap, daemon=True).start()
        except (ImportError, OSError):
            pass
        self.root.bind("<F5>", lambda e: self.root.event_generate(
            "<<Capture>>", when="tail"))
        self.root.bind("<<Capture>>", lambda e: self._capture_and_load())

        self._update_progress()

    # ---- 截图 ----
    def _capture_and_load(self):
        self.root.withdraw()
        self.root.update_idletasks()
        self.root.after(200, self._do_capture)

    def _do_capture(self):
        try:
            self.pil_image = ImageGrab.grab()
            self.orig_w, self.orig_h = self.pil_image.size
            win_w = self.canvas.winfo_width()
            win_h = self.canvas.winfo_height()
            if win_w > 1 and win_h > 1:
                self.scale = min(win_w / self.orig_w, win_h / self.orig_h, 1.0)
            else:
                self.scale = 1.0
            self._rebuild_photo()
            self.rect_id = None
            self._saved_region = None
            self.info_var.set(
                f"截图: {self.orig_w}×{self.orig_h} — 框选\"{self._current_name()}\"后按 R 保存")
        except Exception as e:
            self.info_var.set(f"截图失败: {e}")
        finally:
            self.root.deiconify()

    # ---- 进度管理 ----
    def _current_entry(self):
        if self._current < len(self._queue):
            return self._queue[self._current]
        return None

    def _current_name(self) -> str:
        entry = self._current_entry()
        return f"{entry[0]}/{entry[1]}" if entry else "完成"

    def _update_progress(self):
        total = len(self._queue)
        # 已保存：目标目录中存在对应 .png 文件
        done = sum(1 for sd, k, _ in self._queue[:self._current]
                   if (self._target / sd / f"{k}.png").exists())
        if self._current < total:
            subdir, key, _ = self._queue[self._current]
            self.progress_var.set(
                f"📋 {self._current + 1}/{total}  — 当前: {subdir}/{key}")
        else:
            self.progress_var.set(f"✅ 全部完成！{total} 个锚点")

    # ---- 保存 ----
    def _save_current(self):
        if not self._saved_region:
            self.info_var.set("请先框选区域")
            return
        entry = self._current_entry()
        if not entry:
            self.info_var.set("所有锚点已完成")
            return

        subdir, key, _ = entry
        left, top, right, bottom = self._saved_region

        # 弹出确认窗口（名称已预填）
        confirmed = self._ask_confirm(subdir, key, left, top, right, bottom)
        if not confirmed:
            return

        # 保存图片
        save_dir = self._target / subdir
        save_dir.mkdir(parents=True, exist_ok=True)
        crop = self.pil_image.crop((left, top, right, bottom))
        crop.save(save_dir / f"{key}.png")

        # 写入 regions.yaml
        self._write_region(save_dir, key, (left, top, right, bottom))

        self.info_var.set(
            f"✅ 已保存 {subdir}/{key}.png [{left},{top},{right},{bottom}]")
        self._current += 1
        self._saved_region = None
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self._update_progress()

    def _skip_current(self):
        if self._current < len(self._queue):
            self._current += 1
            self._saved_region = None
            if self.rect_id:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
            self._update_progress()
            self.info_var.set(f"已跳过 → 下一个: {self._current_name()}")

    def _ask_confirm(self, subdir: str, key: str,
                     left: int, top: int, right: int, bottom: int) -> bool:
        result = False
        dlg = tk.Toplevel(self.root)
        dlg.title("确认保存")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text=f"目录: {subdir}", font=("", 12)).pack(
            padx=20, pady=(16, 2))
        tk.Label(dlg, text=f"名称: {key}", font=("", 13, "bold")).pack(
            padx=20, pady=(0, 4))
        tk.Label(dlg, text=f"区域: [{left}, {top}, {right}, {bottom}]  "
                 f"{right-left}×{bottom-top}",
                 font=("", 11), fg="gray").pack(padx=20, pady=(0, 12))

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=(0, 14))

        def on_ok():
            nonlocal result
            result = True
            dlg.destroy()

        tk.Button(btn_frame, text="保存 (Enter)", width=14,
                  command=on_ok).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="跳过 (ESC)", width=14,
                  command=dlg.destroy).pack(side=tk.LEFT, padx=4)

        dlg.bind("<Return>", lambda e: on_ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        px = (self.root.winfo_x() +
              (self.root.winfo_width() - dlg.winfo_width()) // 2)
        py = (self.root.winfo_y() +
              (self.root.winfo_height() - dlg.winfo_height()) // 2)
        dlg.geometry(f"+{px}+{py}")
        dlg.wait_window()
        return result

    @staticmethod
    def _write_region(save_dir: Path, key: str,
                      region: tuple[int, int, int, int]) -> None:
        yf = save_dir / "regions.yaml"
        yaml = YAML()
        yaml.default_flow_style = None
        data: dict = _read_yaml_file(yf) if yf.is_file() else {}
        data[key] = list(region)
        with open(yf, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

    # ---- 坐标 & 画布 ----
    def _to_orig(self, cx: float, cy: float) -> tuple[int, int]:
        return int(cx / self.scale), int(cy / self.scale)

    def _to_canvas(self, ox: int, oy: int) -> tuple[float, float]:
        return ox * self.scale, oy * self.scale

    def on_move(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        ox, oy = self._to_orig(cx, cy)
        self.info_var.set(f"屏幕: ({ox}, {oy}) — 框选\"{self._current_name()}\"")

    def on_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        self.start_x, self.start_y = self._to_orig(cx, cy)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None

    def on_drag(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        sx, sy = self._to_canvas(self.start_x, self.start_y)
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            sx, sy, cx, cy, outline="lime", width=2)

    def on_release(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        ox, oy = self._to_orig(cx, cy)
        left, right = sorted([self.start_x, ox])
        top, bottom = sorted([self.start_y, oy])
        if abs(ox - self.start_x) < 5 and abs(oy - self.start_y) < 5:
            return
        self._saved_region = (left, top, right, bottom)
        self.info_var.set(
            f"区域 [{left}, {top}, {right}, {bottom}]  "
            f"{right-left}×{bottom-top}  — 按 R 保存")

    def _on_coord_enter(self, _event):
        raw = self.coord_entry.get().strip()
        try:
            parts = [int(x.strip()) for x in raw.strip("[]()").split(",")]
            if len(parts) != 4:
                raise ValueError
            left, top, right, bottom = parts
        except (ValueError, TypeError):
            self.info_var.set("格式错误，示例: (100,200,300,400)")
            return
        self._saved_region = (left, top, right, bottom)
        self._draw_rect(left, top, right, bottom)
        self.info_var.set(f"定位到 ({left},{top},{right},{bottom})")

    def _draw_rect(self, left, top, right, bottom):
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        sl, st = self._to_canvas(left, top)
        sr, sb = self._to_canvas(right, bottom)
        self.rect_id = self.canvas.create_rectangle(
            sl, st, sr, sb, outline="lime", width=3)

    def _copy_region(self):
        if not self._saved_region:
            return
        left, top, right, bottom = self._saved_region
        text = f"({left}, {top}, {right}, {bottom})"
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.info_var.set(f"已复制: {text}")

    def _gen_code(self):
        if self._saved_region:
            left, top, right, bottom = self._saved_region
            entry = self._current_entry()
            key = entry[1] if entry else "xxx"
            print(f'\nAnchor(ref=img["{key}"], region=({left},{top},{right},{bottom}))')
            self.info_var.set(f"代码已生成（见终端）")

    def _make_photo(self):
        if self.scale == 1.0:
            img = self.pil_image
        else:
            nw, nh = max(1, int(self.orig_w * self.scale)), max(
                1, int(self.orig_h * self.scale))
            img = self.pil_image.resize((nw, nh), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.scaled_w, self.scaled_h = self.photo.width(), self.photo.height()

    def _rebuild_photo(self):
        self._make_photo()
        self.canvas.delete("all")
        self.canvas.configure(
            scrollregion=(0, 0, self.scaled_w, self.scaled_h))
        self.canvas.create_image(0, 0, image=self.photo, anchor=tk.NW, tags="bg")

    def _on_close(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="分辨率迁移：引导式重新采集所有锚点图")
    parser.add_argument("target_dir", help="新分辨率锚点图输出目录，如 images_4k")
    parser.add_argument("--source-dir", default="images",
                       help="源 images 目录（默认 images/）")
    args = parser.parse_args()

    tool = MigrateTool(args.target_dir, str(Path(args.source_dir)))
    if not tool._queue:
        print("源目录中无 regions.yaml 或锚点列表为空")
        sys.exit(1)
    print(f"共 {len(tool._queue)} 个锚点待采集 → {args.target_dir}/")
    tool.run()


if __name__ == "__main__":
    main()
