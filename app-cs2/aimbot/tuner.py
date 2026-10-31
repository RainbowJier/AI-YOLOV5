"""Modern runtime tuning workbench.

The UI owns its own daemon Tk thread. Configuration changes are applied live
(with a small coalescing window while a slider is dragged), while the aim
loop never calls Tk directly. The game window itself is picked in the
console (capture.game_selection); the tuner opens afterwards. The live feed
is rendered inside the workbench rather than in a separate OpenCV window.
"""

import math
import os
import queue
import re
import sys
import tempfile
import threading
import time
from typing import NamedTuple

import config
from aimbot import feed

try:
    import tkinter
    import customtkinter as ctk
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # UI is optional; the aim loop must never die for it
    ctk = None
    print('[ui] customtkinter/Pillow not installed - tuner disabled '
          '(uv pip install customtkinter Pillow)')


class Knob(NamedTuple):
    name: str
    label: str
    unit: str
    lo: float
    hi: float
    step: float
    hint: str


class Toggle(NamedTuple):
    name: str
    label: str
    hint: str


_FEEL = [
    Knob('move_rate', '吸附速度', '×', 1.0, 20.0, 0.5,
         '弹簧刚度：大=快狠，小=柔（推荐 4-12）'),
    Knob('track_tau', '目标平滑', 's', 0.005, 0.080, 0.001,
         '框 EMA 秒数：大=稳，小=紧跟（0.015-0.050）'),
    Knob('deadband_px', '死区半径', 'px', 0.0, 8.0, 0.5,
         '死区内完全不动：锁定后微晃就加大（1-4）'),
    Knob('lead_min_speed', '引导噪声门', 'px/s', 0.0, 120.0, 5.0,
         '目标速度低于此值引导=0：静止目标仍晃就加大'),
    Knob('lead_fade_radius', '引导衰减', 'px', 0.0, 40.0, 1.0,
         '接近准星时引导逐渐关闭（8-16）'),
]

_TARGET = [
    Knob('max_move_speed', '移动限速', 'px/s', 600.0, 9600.0, 100.0,
         '最大 px/s：大幅甩动太猛就调小'),
    Knob('lock_y', '锁定垂直位', '', 0.0, 1.0, 0.01,
         '0=框顶 0.2=头 0.5=中心 1=框底（运行中 ↑/↓ 也能调）'),
    Knob('aim_range', '触发半径', 'px', 20.0, 200.0, 5.0,
         '目标距准星超过此 px 不瞄'),
    Knob('lock_sen', '灵敏度换算', '×', 0.5, 3.0, 0.05,
         '像素→dots：填游戏灵敏度倍数'),
    Knob('confidence', '检测置信度', '', 0.1, 0.95, 0.05,
         'v5 约 0.75，v11 约 0.45-0.55'),
]

_AIM_TOGGLE = Toggle(
    'aim_while_firing', '开火时继续吸附',
    '是：开火（按住左键）时照常吸附；否：开火时停止，松开后恢复')
_VISUAL_TOGGLE = Toggle(
    'visuals', '实时画面',
    '开：面板内实时显示检测画面；实战建议关闭')
_BODY_TOGGLE = Toggle(
    'aim_body', '识别身体',
    '开：身体框参与瞄准；两个都关 = 不瞄任何目标')
_HEAD_TOGGLE = Toggle(
    'aim_head', '识别头部',
    '开：头部框参与瞄准；只打头就关掉「识别身体」')

_SECTIONS = [
    ('feel', '手感', 'FEEL', _FEEL, []),
    ('target', '目标', 'TARGET', _TARGET, [_BODY_TOGGLE, _HEAD_TOGGLE]),
    ('runtime', '运行', 'RUNTIME', [], [_AIM_TOGGLE, _VISUAL_TOGGLE]),
]

# Kept as a compatibility-friendly aggregate for code/tests that inspect the
# old metadata shape. The UI itself uses _SECTIONS so it can show tabs.
_GROUPS = [
    ('手感', 'FEEL', _FEEL, []),
    ('目标', 'TARGET', _TARGET, [_AIM_TOGGLE]),
]
_STRIP_TOGGLES = [_VISUAL_TOGGLE]
KNOBS = {k.name: k for _, _, knobs, _ in _GROUPS for k in knobs}
TOGGLES = [_AIM_TOGGLE, _VISUAL_TOGGLE, _BODY_TOGGLE, _HEAD_TOGGLE]


class _Theme:
    BG = '#090d14'
    PANEL = '#0e1420'
    CARD = '#121a28'
    SURFACE = '#182235'
    SURFACE_HOVER = '#202d45'
    BORDER = '#26344d'
    BORDER_FOCUS = '#7784ff'
    TRACK = '#2a3852'
    TEXT = '#f0f3fb'
    TEXT_DIM = '#a6b1c8'
    TEXT_MUTED = '#77859f'
    ACCENT = '#7a86ff'
    ACCENT_DARK = '#5968ed'
    ACCENT_HOVER = '#8b96ff'
    CYAN = '#5ed8e8'
    GREEN = '#4be0a4'
    AMBER = '#f5c15a'
    RED = '#ff707b'
    MONO = 'Consolas'
    UI = 'Microsoft YaHei UI'


_T = _Theme()

_HEADER_H = 66
_FEED_PX = 280
_FEED_MS = 80
_POLL_MS = 250
_HIDDEN_POLL_MS = 700
_COMMIT_MS = 24
_FLASH_MS = 1500
_ERROR_MS = 2200
_SAVE_TEXT = '保存到 config.py'


def _decimals(step):
    return len('{:.6f}'.format(step).rstrip('0').partition('.')[2])


def _fmt(value, step):
    return '{:.{prec}f}'.format(value, prec=_decimals(step))


def _snap(knob, value):
    steps = round((value - knob.lo) / knob.step)
    value = knob.lo + steps * knob.step
    return round(min(knob.hi, max(knob.lo, value)), _decimals(knob.step) + 2)


def refresh():
    """Push live config into modules that cached values at import time."""
    import aimbot.targeting as tgt
    tgt._INV_SEN = 1.0 / config.lock_sen
    tgt._AIM_RANGE_SQ = config.aim_range * config.aim_range
    tgt._LEAD_FADE_R = config.lead_fade_radius
    tgt._LEAD_MIN = config.lead_min_speed
    tgt._DEADBAND = config.deadband_px
    tgt.apply_class_filter()
    for name in ('tensorrt_backend', 'onnx_backend', 'torch_backend'):
        module = sys.modules.get('aimbot.backends.' + name)
        if module is not None:
            module.confidence = config.confidence


def _literal(knob, value):
    if knob.step >= 1.0 and float(value).is_integer():
        return str(int(value))
    return repr(round(float(value), _decimals(knob.step) + 2))


def save(values=None):
    """Write a value snapshot to config.py, preserving comments and endings."""
    path = config.__file__
    values = values or {name: getattr(config, name) for name in KNOBS}
    values.update({toggle.name: getattr(config, toggle.name)
                   for toggle in TOGGLES if toggle.name not in values})
    entries = [(_name, _literal(KNOBS[_name], values[_name]))
               for _name in KNOBS]
    entries += [(toggle.name, str(bool(values[toggle.name])))
                for toggle in TOGGLES]

    with open(path, 'r', encoding='utf-8', newline='') as f:
        text = f.read()
    for name, literal in entries:
        value = values[name]

        def replace(match, literal=literal, value=value):
            try:
                if abs(float(match.group(2)) - value) < 1e-9:
                    return match.group(0)
            except (ValueError, TypeError):
                if match.group(2) == literal:
                    return match.group(0)
            return match.group(1) + literal + match.group(3)

        text, count = re.subn(
            r'^({}\s*=\s*)([^#\s]+)([ \t]*(?:#[^\r\n]*)?)(?=\r?$)'.format(
                re.escape(name)),
            replace, text, count=1, flags=re.MULTILINE)
        if count == 0:
            print('[ui] config.py: {} not found (not saved)'.format(name))

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    print('[ui] config.py saved')


if ctk is not None:
    _SS = 8

    def _blank(px):
        image = Image.new('RGBA', (px * _SS, px * _SS), (0, 0, 0, 0))
        return image, ImageDraw.Draw(image), px * _SS

    def _draw_logo(px):
        image, draw, size = _blank(px)
        draw.rounded_rectangle((0, 0, size - 1, size - 1),
                               radius=size * 0.25, fill=_T.ACCENT_DARK)
        center, width, radius = size / 2, round(size * 0.06), size * 0.17
        draw.ellipse((center - radius, center - radius,
                      center + radius, center + radius),
                     outline='white', width=width)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            draw.line((center + dx * size * 0.25,
                       center + dy * size * 0.25,
                       center + dx * size * 0.37,
                       center + dy * size * 0.37),
                      fill='white', width=width)
        draw.ellipse((center - width / 2, center - width / 2,
                      center + width / 2, center + width / 2), fill='white')
        return image.resize((px, px), Image.LANCZOS)

    def _draw_reset(color, px):
        image, draw, size = _blank(px)
        center, radius, width = size / 2, size * 0.30, round(size * 0.10)
        draw.arc((center - radius, center - radius,
                  center + radius, center + radius),
                 start=40, end=330, fill=color, width=width)
        angle = math.radians(330)
        cosine, sine = math.cos(angle), math.sin(angle)
        edge = radius - width / 2
        ex, ey = center + edge * cosine, center + edge * sine
        half, length = size * 0.15, size * 0.17
        draw.polygon([(ex + cosine * half, ey + sine * half),
                      (ex - cosine * half, ey - sine * half),
                      (ex - sine * length, ey + cosine * length)], fill=color)
        return ImageOps.mirror(image.resize((px, px), Image.LANCZOS))

    def _draw_feed_placeholder(px):
        image, draw, size = _blank(px)
        draw.rounded_rectangle((0, 0, size - 1, size - 1),
                               radius=size * 0.04, fill=_T.SURFACE)
        center, width = size / 2, max(1, round(size * 0.012))
        draw.line((0, center, size, center), fill=_T.TRACK, width=width)
        draw.line((center, 0, center, size), fill=_T.TRACK, width=width)
        radius = size * 0.22
        draw.ellipse((center - radius, center - radius,
                      center + radius, center + radius),
                     outline=_T.TRACK, width=round(size * 0.018))
        return image.resize((px, px), Image.LANCZOS)


    class _Fonts:
        def __init__(self):
            def ui(size, weight='normal'):
                return ctk.CTkFont(family=_T.UI, size=size, weight=weight)
            self.hero = ui(18, 'bold')
            self.title = ui(15, 'bold')
            self.section = ui(13, 'bold')
            self.label = ui(13)
            self.button = ui(12, 'bold')
            self.body = ui(12)
            self.small = ui(11)
            self.caption = ui(10)
            self.value = ctk.CTkFont(family=_T.MONO, size=13, weight='bold')


    class _Icons:
        def __init__(self):
            self.logo = ctk.CTkImage(_draw_logo(128), size=(34, 34))
            self.reset_on = ctk.CTkImage(_draw_reset(_T.AMBER, 64), size=(16, 16))
            self.reset_off = ctk.CTkImage(_draw_reset(_T.TRACK, 64), size=(16, 16))


    class _FeedPanel:
        def __init__(self, tuner, parent):
            self.tuner = tuner
            self._any = False
            self._fps = 0.0
            self._last_caption = None
            f, icons = tuner.fonts, tuner.icons
            self.card = ctk.CTkFrame(parent, corner_radius=16,
                                     fg_color=_T.CARD, border_width=1,
                                     border_color=_T.BORDER)
            self.card.grid_columnconfigure(0, weight=1)
            header = ctk.CTkFrame(self.card, fg_color='transparent')
            header.grid(row=0, column=0, sticky='ew', padx=18, pady=(16, 0))
            ctk.CTkFrame(header, width=3, height=16, corner_radius=2,
                         fg_color=_T.CYAN).pack(side='left', padx=(0, 9))
            ctk.CTkLabel(header, text='实时画面', font=f.section,
                         text_color=_T.TEXT).pack(side='left')
            self.badge = ctk.CTkLabel(
                header, text='PAUSED', font=f.caption, text_color=_T.TEXT_MUTED,
                fg_color=_T.SURFACE, corner_radius=8, width=66, height=22)
            self.badge.pack(side='right')
            ctk.CTkLabel(header, text='LIVE FEED', font=f.caption,
                         text_color=_T.TEXT_MUTED).pack(side='right', padx=(0, 10))

            well = ctk.CTkFrame(self.card, fg_color=_T.BG, corner_radius=12)
            well.grid(row=1, column=0, padx=18, pady=(14, 0))
            self.image = ctk.CTkImage(_draw_feed_placeholder(_FEED_PX),
                                      size=(_FEED_PX, _FEED_PX))
            ctk.CTkLabel(well, text='', image=self.image).pack(padx=8, pady=8)
            self.caption = ctk.CTkLabel(
                self.card, text='打开「实时画面」后显示检测帧',
                font=f.small, text_color=_T.TEXT_MUTED, anchor='w', height=20)
            self.caption.grid(row=2, column=0, sticky='ew', padx=18, pady=(10, 0))
            self.meta = ctk.CTkLabel(
                self.card, text='最新帧优先 · 不创建独立窗口',
                font=f.caption, text_color=_T.TEXT_MUTED, anchor='w', height=18)
            self.meta.grid(row=3, column=0, sticky='ew', padx=18, pady=(2, 14))

        def show(self, frame):
            image = Image.fromarray(frame)
            self.image.configure(light_image=image, dark_image=image)
            self._any = True

        def state(self, enabled, fps=0.0):
            self._fps = fps
            if enabled and fps > 0.5:
                badge, color = 'LIVE', _T.CYAN
                caption = '● LIVE · ~{:.0f} FPS'.format(fps)
            elif enabled:
                badge, color = 'NO SIGNAL', _T.AMBER
                caption = '等待检测帧…'
            elif self._any:
                badge, color = 'PAUSED', _T.TEXT_MUTED
                caption = '已暂停 · 停留在最后一帧'
            else:
                badge, color = 'PAUSED', _T.TEXT_MUTED
                caption = '打开「实时画面」后显示检测帧'
            key = (badge, caption)
            if key == self._last_caption:
                return
            self._last_caption = key
            self.badge.configure(text=badge, text_color=color)
            self.caption.configure(text=caption, text_color=color)


    class _ControlRow:
        def __init__(self, tuner, parent, knob):
            self.tuner = tuner
            self.knob = knob
            self.base = self.value = _snap(knob, getattr(config, knob.name))
            self._editing = False
            self._edit_value = self.value
            self._pending = None
            self._error_job = None
            self._error = False
            f, icons = tuner.fonts, tuner.icons

            self.card = ctk.CTkFrame(parent, corner_radius=12,
                                     fg_color=_T.CARD, border_width=1,
                                     border_color=_T.BORDER)
            self.card.grid_columnconfigure(2, weight=1)
            header = ctk.CTkFrame(self.card, fg_color='transparent')
            header.grid(row=0, column=0, columnspan=5, sticky='ew',
                        padx=14, pady=(11, 0))
            ctk.CTkLabel(header, text=knob.label, font=f.label,
                         text_color=_T.TEXT, anchor='w').pack(side='left')
            self.reset = ctk.CTkButton(
                header, text='', image=icons.reset_off, width=22, height=22,
                corner_radius=11, fg_color='transparent', hover_color=_T.SURFACE,
                state='disabled', command=self.revert)
            self.reset.pack(side='left', padx=(8, 0))
            self.entry = ctk.CTkEntry(
                header, width=72, height=26, justify='right', font=f.value,
                fg_color=_T.SURFACE, border_color=_T.BORDER, border_width=1,
                corner_radius=8, text_color=_T.ACCENT)
            self.entry.pack(side='right')
            ctk.CTkLabel(header, text=knob.unit, font=f.small,
                         text_color=_T.TEXT_MUTED, width=42, anchor='w').pack(
                side='right', padx=(7, 0))

            self.slider = ctk.CTkSlider(
                self.card, from_=knob.lo, to=knob.hi, height=14,
                number_of_steps=int(round((knob.hi - knob.lo) / knob.step)),
                scroll_step=0,  # the wheel must never nudge a value; drag only
                fg_color=_T.TRACK, progress_color=_T.ACCENT,
                button_color=_T.TEXT, button_hover_color='#ffffff',
                command=self._on_slider)
            self.slider.grid(row=1, column=0, columnspan=5, sticky='ew',
                             padx=14, pady=(8, 0))
            self.slider.bind('<ButtonRelease-1>', self._commit_pending, add='+')
            self.hint = ctk.CTkLabel(
                self.card, text=knob.hint, font=f.small, text_color=_T.TEXT_MUTED,
                anchor='w', wraplength=430, height=30)
            self.hint.grid(row=2, column=0, columnspan=5, sticky='ew',
                           padx=14, pady=(3, 8))

            self.entry.bind('<FocusIn>', self._focus_in)
            self.entry.bind('<FocusOut>', self._commit)
            self.entry.bind('<Return>', self._commit)
            self.entry.bind('<Escape>', self._cancel)
            self._show()

        @property
        def modified(self):
            return abs(self.value - self.base) > self.knob.step / 2

        def _show(self):
            if abs(self.slider.get() - self.value) > 1e-9:
                self.slider.set(self.value)
            if not self._editing:
                text = _fmt(self.value, self.knob.step)
                if self.entry.get() != text:
                    self.entry.delete(0, 'end')
                    self.entry.insert(0, text)
            if self._error:
                return
            modified = self.modified
            self.entry.configure(text_color=_T.AMBER if modified else _T.ACCENT)
            self.reset.configure(
                image=self.tuner.icons.reset_on if modified else self.tuner.icons.reset_off,
                state='normal' if modified else 'disabled')

        def _on_slider(self, raw):
            self._editing = False
            self.value = _snap(self.knob, float(raw))
            self._show()
            self.tuner.queue_value(self, self.value)
            self.tuner.render()

        def _commit_pending(self, _event=None):
            if self._pending is not None:
                self.tuner.commit_pending()

        def commit_value(self, value=None):
            if value is not None:
                self.value = _snap(self.knob, value)
            self._pending = None
            setattr(config, self.knob.name, self.value)
            refresh()
            self._show()

        def apply(self, value):
            self.tuner.cancel_pending(self)
            self._editing = False
            self.commit_value(value)
            self.tuner.render()

        def sync(self):
            if self._editing or self._pending is not None:
                return
            current = _snap(self.knob, getattr(config, self.knob.name))
            if current != self.value:
                self.value = current
                self._show()

        def mark_saved(self, snapshot=None):
            if snapshot is None or abs(snapshot - self.value) <= self.knob.step / 2:
                self.base = self.value
                self._show()

        def revert(self):
            self.apply(self.base)

        def _focus_in(self, _event):
            self.tuner.commit_pending()
            self._editing = True
            self._edit_value = self.value
            self._error = False
            self.entry.configure(border_color=_T.BORDER_FOCUS)
            self.entry.after(10, lambda: self.entry.select_range(0, 'end'))

        def _commit(self, event=None):
            try:
                value = float(self.entry.get().strip())
            except ValueError:
                self._show_error('请输入数字')
                if event is not None and getattr(event, 'keysym', '') == 'Return':
                    return 'break'
                return
            self._editing = False
            self._error = False
            self.entry.configure(border_color=_T.BORDER)
            self.apply(value)
            if event is not None and getattr(event, 'keysym', '') == 'Return':
                self.tuner.root.focus_set()
                return 'break'

        def _cancel(self, _event=None):
            self._editing = False
            self._error = False
            self.value = self._edit_value
            self.entry.configure(border_color=_T.BORDER)
            self._show()
            self.tuner.root.focus_set()
            return 'break'

        def _show_error(self, message):
            self._error = True
            self.entry.configure(border_color=_T.RED, text_color=_T.RED)
            self.hint.configure(text=message + ' · 范围 {:.3g} – {:.3g}'.format(
                self.knob.lo, self.knob.hi), text_color=_T.RED)
            if self._error_job is not None:
                self.tuner.root.after_cancel(self._error_job)
            self._error_job = self.tuner.root.after(1600, self._clear_error)

        def _clear_error(self):
            self._error_job = None
            self._error = False
            self._editing = False
            self.value = self._edit_value
            self.entry.configure(border_color=_T.BORDER)
            self.hint.configure(text=self.knob.hint, text_color=_T.TEXT_MUTED)
            self._show()


    class _ToggleRow:
        def __init__(self, tuner, parent, toggle):
            self.tuner = tuner
            self.toggle = toggle
            self.base = self.value = bool(getattr(config, toggle.name))
            self._lit = None
            f, icons = tuner.fonts, tuner.icons
            self.card = ctk.CTkFrame(parent, corner_radius=12,
                                     fg_color=_T.CARD, border_width=1,
                                     border_color=_T.BORDER)
            self.card.grid_columnconfigure(1, weight=1)
            self.label = ctk.CTkLabel(
                self.card, text=toggle.label, font=f.label, text_color=_T.TEXT,
                anchor='w', width=124)
            self.label.grid(row=0, column=0, sticky='w', padx=(14, 0), pady=(12, 0))
            self.reset = ctk.CTkButton(
                self.card, text='', image=icons.reset_off, width=22, height=22,
                corner_radius=11, fg_color='transparent', hover_color=_T.SURFACE,
                state='disabled', command=self.revert)
            self.reset.grid(row=0, column=1, sticky='w', padx=(8, 0), pady=(12, 0))
            self.switch = ctk.CTkSwitch(
                self.card, text='', width=42, switch_width=38, switch_height=20,
                progress_color=_T.ACCENT_DARK, fg_color=_T.TRACK,
                button_color=_T.TEXT, button_hover_color='#ffffff',
                command=lambda: self.apply(bool(self.switch.get())))
            self.switch.grid(row=0, column=2, sticky='e', padx=(0, 14), pady=(12, 0))
            ctk.CTkLabel(
                self.card, text=toggle.hint, font=f.small, text_color=_T.TEXT_MUTED,
                anchor='w', wraplength=430, height=30).grid(
                row=1, column=0, columnspan=3, sticky='ew', padx=14, pady=(3, 10))
            self._show()

        @property
        def modified(self):
            return self.value != self.base

        def _show(self):
            if bool(self.switch.get()) != self.value:
                self.switch.select() if self.value else self.switch.deselect()
            modified = self.modified
            if modified != self._lit:
                self._lit = modified
                self.label.configure(text_color=_T.AMBER if modified else _T.TEXT)
                self.reset.configure(
                    image=self.tuner.icons.reset_on if modified else self.tuner.icons.reset_off,
                    state='normal' if modified else 'disabled')

        def apply(self, value):
            self.value = bool(value)
            setattr(config, self.toggle.name, self.value)
            if self.toggle.name in ('aim_body', 'aim_head'):
                refresh()   # class filter is baked at import; recompute it
            self._show()
            if self.toggle.name == 'visuals':
                self.tuner.visuals_changed()
            self.tuner.render()

        def sync(self):
            current = bool(getattr(config, self.toggle.name))
            if current != self.value:
                self.value = current
                self._show()
                if self.toggle.name == 'visuals':
                    self.tuner.visuals_changed()

        def mark_saved(self, snapshot=None):
            if snapshot is None or bool(snapshot) == self.value:
                self.base = self.value
                self._show()

        def revert(self):
            self.apply(self.base)


    class Tuner:
        """The tuning workbench; the game window is picked in the console."""

        def __init__(self):
            ctk.set_appearance_mode('dark')
            ctk.set_default_color_theme('dark-blue')
            self.root = ctk.CTk(fg_color=_T.BG)
            self.root.attributes('-topmost', True)
            self.root.resizable(False, False)
            self._set_window_icon()
            self.fonts = _Fonts()
            self.icons = _Icons()
            self.rows = []
            self._controls = {}
            self._pending = {}
            self._commit_job = None
            self._poll_job = None
            self._feed_job = None
            self._save_job = None
            self._save_results = queue.Queue()
            self._flash = False
            self._error = None
            self._saving = False
            self._rendered = None
            self._feed_frames = 0
            self._feed_t0 = time.monotonic()
            self._current_section = 'feel'
            self._current_page = 'tuner'
            self._tuner_page = ctk.CTkFrame(self.root, fg_color='transparent')
            self._tuner_page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._build_tuner_page()
            self.root.bind_all('<Button-1>', self._defocus_entry, add='+')
            self.root.bind('<Map>', lambda _e: self._on_visibility(True), add='+')
            self.root.bind('<Unmap>', lambda _e: self._on_visibility(False), add='+')
            self.root.title('Aim Tuner')
            self.root.protocol('WM_DELETE_WINDOW', self.root.iconify)
            self.root.update_idletasks()
            self._set_geometry(self._tuner_page)
            self.visuals_changed()
            self.render()
            self._start_timers()

        def _set_window_icon(self):
            try:
                path = os.path.join(tempfile.gettempdir(), 'aim_tuner.ico')
                _draw_logo(256).save(path, sizes=[(16, 16), (32, 32), (48, 48)])
                self.root.iconbitmap(path)
            except (OSError, ValueError, tkinter.TclError):
                pass

        def _build_header(self, parent, title, subtitle, columnspan=2):
            f = self.fonts
            header = ctk.CTkFrame(parent, fg_color='transparent', height=_HEADER_H)
            header.grid(row=0, column=0, columnspan=columnspan, sticky='ew',
                        padx=22, pady=(14, 8))
            header.grid_propagate(False)
            ctk.CTkLabel(header, text='', image=self.icons.logo).pack(
                side='left', padx=(0, 12))
            titles = ctk.CTkFrame(header, fg_color='transparent')
            titles.pack(side='left')
            ctk.CTkLabel(titles, text=title, font=f.hero,
                         text_color=_T.TEXT, anchor='w').pack(anchor='w')
            subtitle_label = ctk.CTkLabel(
                titles, text=subtitle, font=f.caption,
                text_color=_T.TEXT_MUTED, anchor='w', width=420)
            subtitle_label.pack(anchor='w')
            if parent is self._tuner_page:
                right = ctk.CTkFrame(header, fg_color='transparent')
                right.pack(side='right')
                self._header_status = ctk.CTkLabel(
                    right, text='READY', font=f.caption,
                    text_color=_T.CYAN, fg_color=_T.SURFACE,
                    corner_radius=8, width=68, height=22)
                self._header_status.pack(side='left', padx=(0, 14))
                self._pin = ctk.CTkSwitch(
                    right, text='置顶', font=f.small, text_color=_T.TEXT_DIM,
                    width=68, switch_width=36, switch_height=18,
                    progress_color=_T.ACCENT_DARK, fg_color=_T.TRACK,
                    button_color=_T.TEXT, button_hover_color='#ffffff',
                    command=lambda: self.root.attributes(
                        '-topmost', bool(self._pin.get())))
                self._pin.select()
                self._pin.pack(side='left')
                ctk.CTkButton(
                    right, text='—', width=28, height=26, corner_radius=8,
                    fg_color='transparent', hover_color=_T.SURFACE_HOVER,
                    text_color=_T.TEXT_MUTED, font=f.title,
                    command=self.root.iconify).pack(side='left', padx=(10, 0))
            return subtitle_label

        def _build_tuner_page(self):
            page = self._tuner_page
            page.grid_columnconfigure(0, weight=0)
            page.grid_columnconfigure(1, weight=1)
            page.grid_rowconfigure(1, weight=1)
            self._build_header(page, '瞄准工作台',
                               '拖动即时生效 · 保存后写入 config.py', 2)

            self._feed_panel = _FeedPanel(self, page)
            self._feed_panel.card.grid(row=1, column=0, sticky='nsew',
                                       padx=(22, 9), pady=(0, 0))

            controls = ctk.CTkFrame(page, corner_radius=16, fg_color=_T.PANEL,
                                    border_width=1, border_color=_T.BORDER)
            controls.grid(row=1, column=1, sticky='nsew', padx=(9, 22))
            controls.grid_columnconfigure(0, weight=1)
            controls.grid_rowconfigure(2, weight=1)
            top = ctk.CTkFrame(controls, fg_color='transparent')
            top.grid(row=0, column=0, sticky='ew', padx=18, pady=(14, 0))
            ctk.CTkLabel(top, text='控制中心', font=self.fonts.title,
                         text_color=_T.TEXT).pack(side='left')
            ctk.CTkLabel(top, text='LIVE CONTROLS', font=self.fonts.caption,
                         text_color=_T.TEXT_MUTED).pack(side='right')

            self._tabs = ctk.CTkFrame(controls, fg_color='transparent')
            self._tabs.grid(row=1, column=0, sticky='ew', padx=14, pady=(12, 8))
            for key, title, _caption, _knobs, _toggles in _SECTIONS:
                self._add_tab(key, title)

            self._control_scroll = ctk.CTkScrollableFrame(
                controls, width=510, height=500, corner_radius=12,
                fg_color='transparent')
            # No wheel scrolling anywhere in this panel (mis-touch while
            # gaming): the card list scrolls only via the scrollbar drag.
            # CTkScrollableFrame binds <MouseWheel> app-wide in its
            # constructor, so detach it right after creation.
            self._control_scroll.unbind_all('<MouseWheel>')
            self._control_scroll.grid(row=2, column=0, sticky='nsew',
                                      padx=10, pady=(0, 10))
            self._control_scroll.grid_columnconfigure(0, weight=1)
            self._build_sections()

            action = ctk.CTkFrame(page, fg_color='transparent', height=52)
            action.grid(row=2, column=0, columnspan=2, sticky='ew',
                        padx=22, pady=(10, 14))
            action.grid_propagate(False)
            self._status_label = ctk.CTkLabel(
                action, text='', width=360, height=36, anchor='w',
                font=self.fonts.body, text_color=_T.TEXT_MUTED)
            self._status_label.pack(side='left')
            self._save_button = ctk.CTkButton(
                action, text=_SAVE_TEXT, width=142, height=36, corner_radius=10,
                font=self.fonts.button, command=self._save_clicked)
            self._save_button.pack(side='right')
            self._revert_button = ctk.CTkButton(
                action, text='全部还原', width=88, height=36, corner_radius=10,
                border_width=1, border_color=_T.BORDER, fg_color='transparent',
                hover_color=_T.SURFACE_HOVER, text_color=_T.TEXT_DIM,
                text_color_disabled=_T.TRACK, font=self.fonts.body,
                command=self._revert_all)
            self._revert_button.pack(side='right', padx=(0, 8))

        def _add_tab(self, key, title):
            button = ctk.CTkButton(
                self._tabs, text=title, width=82, height=31, corner_radius=9,
                border_width=1, border_color=_T.BORDER, fg_color='transparent',
                hover_color=_T.SURFACE_HOVER, text_color=_T.TEXT_DIM,
                font=self.fonts.body, command=lambda k=key: self._show_section(k))
            button.pack(side='left', padx=(0, 6))
            if not hasattr(self, '_tab_buttons'):
                self._tab_buttons = {}
            self._tab_buttons[key] = button

        def _build_sections(self):
            self._section_frames = {}
            for index, (key, title, caption, knobs, toggles) in enumerate(_SECTIONS):
                section = ctk.CTkFrame(self._control_scroll, fg_color='transparent')
                section.grid_columnconfigure(0, weight=1)
                self._section_frames[key] = section
                ctk.CTkLabel(
                    section, text=caption, font=self.fonts.caption,
                    text_color=_T.TEXT_MUTED, anchor='w').grid(
                    row=0, column=0, sticky='w', padx=4, pady=(4, 8))
                row_index = 1
                for knob in knobs:
                    control = _ControlRow(self, section, knob)
                    control.card.grid(row=row_index, column=0, sticky='ew', pady=(0, 8))
                    self.rows.append(control)
                    self._controls[knob.name] = control
                    row_index += 1
                for toggle in toggles:
                    control = _ToggleRow(self, section, toggle)
                    control.card.grid(row=row_index, column=0, sticky='ew', pady=(0, 8))
                    self.rows.append(control)
                    self._controls[toggle.name] = control
                    row_index += 1
                if key == 'runtime':
                    self._add_runtime_info(section, row_index)
                section.grid(row=0, column=0, sticky='ew')
            self._show_section('feel')

        def _add_runtime_info(self, section, row):
            info = ctk.CTkFrame(section, corner_radius=12, fg_color=_T.CARD,
                                border_width=1, border_color=_T.BORDER)
            info.grid(row=row, column=0, sticky='ew', pady=(4, 0))
            ctk.CTkLabel(info, text='快捷操作', font=self.fonts.section,
                         text_color=_T.TEXT, anchor='w').pack(
                anchor='w', padx=14, pady=(12, 5))
            ctk.CTkLabel(
                info, text='Caps Lock  开/关瞄准\n↑ / ↓  调整锁定垂直位\nP  退出程序\n鼠标滚轮已禁用：调值请拖滑条或输入数值',
                font=self.fonts.small, text_color=_T.TEXT_MUTED,
                anchor='w', justify='left').pack(anchor='w', padx=14, pady=(0, 12))

        def _show_section(self, key):
            self._commit_all()
            if not hasattr(self, '_section_frames'):
                return
            self._current_section = key
            for section_key, section in self._section_frames.items():
                if section_key == key:
                    section.grid()
                else:
                    section.grid_remove()
            for section_key, button in self._tab_buttons.items():
                if section_key == key:
                    button.configure(fg_color=_T.ACCENT_DARK,
                                     hover_color=_T.ACCENT,
                                     text_color=_T.TEXT)
                else:
                    button.configure(fg_color='transparent',
                                     hover_color=_T.SURFACE_HOVER,
                                     text_color=_T.TEXT_DIM)
            # CTkScrollableFrame wraps a private canvas in 6.0.0; use the
            # underlying canvas when available, without relying on a public
            # yview API that this widget does not expose.
            canvas = getattr(self._control_scroll, '_parent_canvas', None)
            if canvas is not None:
                canvas.yview_moveto(0)
            self.render()

        def _set_geometry(self, page):
            page.update_idletasks()
            width, height = 1120, 720
            scale = max(1.0, self.root.winfo_fpixels('1i') / 96.0)
            screen_w = int(self.root.winfo_screenwidth() / scale)
            screen_h = int(self.root.winfo_screenheight() / scale)
            width = min(width, max(320, screen_w - 24))
            height = min(height, max(320, screen_h - 72))
            x = max(12, screen_w - width - 24)
            y = max(36, min(48, screen_h - height - 24))
            self.root.geometry('{}x{}+{}+{}'.format(width, height, x, y))

        def _start_timers(self):
            if self._poll_job is None:
                self._poll_job = self.root.after(_POLL_MS, self._poll)
            if self._feed_job is None:
                self._feed_job = self.root.after(_FEED_MS, self._poll_feed)

        def _is_visible(self):
            try:
                return self.root.state() not in ('iconic', 'withdrawn') and self.root.winfo_viewable()
            except tkinter.TclError:
                return False

        def _on_visibility(self, visible):
            if visible and getattr(self, '_current_page', None) == 'tuner':
                self._start_timers()

        def queue_value(self, row, value):
            row._pending = value
            self._pending[row] = value
            if self._commit_job is None:
                self._commit_job = self.root.after(_COMMIT_MS, self.commit_pending)

        def cancel_pending(self, row):
            self._pending.pop(row, None)
            row._pending = None

        def commit_pending(self):
            if self._commit_job is not None:
                try:
                    self.root.after_cancel(self._commit_job)
                except tkinter.TclError:
                    pass
                self._commit_job = None
            pending = list(self._pending.items())
            self._pending.clear()
            for row, value in pending:
                row.commit_value(value)
            if pending:
                self.render()

        def _commit_all(self):
            self.commit_pending()
            for row in self.rows:
                if isinstance(row, _ControlRow) and row._editing:
                    row._commit()

        def visuals_changed(self):
            self._feed_frames = 0
            self._feed_t0 = time.monotonic()
            enabled = bool(config.visuals)
            self._feed_panel.state(enabled, 0.0)
            self._header_status.configure(
                text='READY' if enabled else 'PAUSED',
                text_color=_T.CYAN if enabled else _T.TEXT_MUTED)

        def _poll(self):
            self._poll_job = None
            try:
                snapshot, error = self._save_results.get_nowait()
            except queue.Empty:
                pass
            else:
                self._save_done(snapshot, error)
            if self._is_visible() and self._current_page == 'tuner':
                for row in self.rows:
                    row.sync()
                self.render()
            self._poll_job = self.root.after(
                _POLL_MS if self._is_visible() else _HIDDEN_POLL_MS, self._poll)

        def _poll_feed(self):
            self._feed_job = None
            visible = self._is_visible() and self._current_page == 'tuner'
            if visible and config.visuals:
                frame = feed.take()
                if frame is not None:
                    self._feed_panel.show(frame)
                    self._feed_frames += 1
                    # Immediate feedback on the first frame; do not make the
                    # user wait for the one-second FPS sampling window.
                    self._feed_panel.state(True, 1.0)
                    self._header_status.configure(text='LIVE', text_color=_T.CYAN)
                now = time.monotonic()
                if now - self._feed_t0 >= 1.0:
                    fps = self._feed_frames / max(now - self._feed_t0, 1e-6)
                    self._feed_panel.state(True, fps)
                    self._header_status.configure(
                        text='LIVE' if fps > 0.5 else 'NO SIGNAL',
                        text_color=_T.CYAN if fps > 0.5 else _T.AMBER)
                    self._feed_frames = 0
                    self._feed_t0 = now
            elif visible:
                self._feed_panel.state(False, 0.0)
            self._feed_job = self.root.after(
                _FEED_MS if visible else _HIDDEN_POLL_MS, self._poll_feed)

        def render(self):
            if not hasattr(self, '_status_label'):
                return
            count = sum(row.modified for row in self.rows)
            key = (count, self._flash, self._error, self._saving)
            if key == self._rendered:
                return
            self._rendered = key
            if self._saving:
                text, color = '● 保存中…', _T.CYAN
            elif self._error:
                text, color = '● 保存失败：' + str(self._error)[:28], _T.RED
            elif count:
                text, color = '● {} 项未保存'.format(count), _T.AMBER
            elif self._flash:
                text, color = '● 已写入 config.py', _T.GREEN
            else:
                text, color = '● 与 config.py 一致', _T.TEXT_MUTED
            self._status_label.configure(text=text, text_color=color)
            enabled = count > 0 and not self._saving
            self._save_button.configure(
                state='normal' if enabled or self._flash else 'disabled',
                text='✓ 已保存' if self._flash else _SAVE_TEXT,
                fg_color=_T.GREEN if self._flash else (_T.ACCENT_DARK if enabled else _T.SURFACE),
                hover_color=_T.GREEN if self._flash else (_T.ACCENT if enabled else _T.SURFACE),
                text_color='#06281a' if self._flash else (_T.TEXT if enabled else _T.TEXT_MUTED))
            self._revert_button.configure(
                state='normal' if count > 0 and not self._saving else 'disabled')

        def _revert_all(self):
            self._commit_all()
            for row in self.rows:
                row.revert()
            self.render()

        def _save_clicked(self):
            self._commit_all()
            if self._saving or not any(row.modified for row in self.rows):
                return
            snapshot = {name: getattr(config, name) for name in KNOBS}
            snapshot.update({toggle.name: getattr(config, toggle.name)
                             for toggle in TOGGLES})
            self._saving = True
            self._error = None
            self.render()
            self._save_job = threading.Thread(
                target=self._save_worker, args=(snapshot,), daemon=True)
            self._save_job.start()

        def _save_worker(self, snapshot):
            error = None
            try:
                save(snapshot)
            except Exception as exc:
                error = getattr(exc, 'strerror', None) or str(exc)
            self._save_results.put((snapshot, error))

        def _save_done(self, snapshot, error):
            self._saving = False
            if error:
                self._error = error
            else:
                self._error = None
                for row in self.rows:
                    row.mark_saved(snapshot.get(
                        row.knob.name if isinstance(row, _ControlRow)
                        else row.toggle.name))
                self._flash = True
                self.root.after(_FLASH_MS, self._clear_flash)
            self.render()

        def _clear_flash(self):
            self._flash = False
            self.render()

        def _defocus_entry(self, event):
            # Commit only when the click lands outside an actual Tk Entry;
            # tabs/buttons still get an explicit _commit_all before acting.
            if not isinstance(event.widget, tkinter.Entry):
                self.root.focus_set()

        def run(self):
            self.root.mainloop()


    _thread = None


    def start():
        """Open the tuner workbench in a daemon thread (idempotent)."""
        global _thread
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, daemon=True)
        _thread.start()


    def _run():
        try:
            Tuner().run()
        except Exception as exc:
            print('[ui] tuner failed: {}'.format(exc))

else:
    def start():
        pass
