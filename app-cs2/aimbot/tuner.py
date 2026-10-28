"""Runtime tuning UI (CustomTkinter, dark, modern). Own thread; sliders
write straight into the config module so every change applies on the
next frame -- no restart.

Value changes also call refresh(), which re-derives the module-level
constants targeting.py baked at import (_INV_SEN, _AIM_RANGE_SQ, the
lead/deadband gates). save() writes values back into config.py with
regex, keeping comments and layout intact.
"""

import math
import re
import threading

import config

try:
    import customtkinter as ctk
except ImportError:  # UI is optional; the aim loop must never die for it
    ctk = None
    print('[ui] customtkinter not installed - tuner disabled '
          '(uv pip install customtkinter)')

# name -> (label, min, max, resolution, hint)
KNOBS = {
    'move_rate':       ('吸附速度', 1.0, 20.0, 0.5,
                        '弹簧刚度：大=快狠，小=柔（推荐 4-12）'),
    'track_tau':       ('目标平滑', 0.005, 0.080, 0.001,
                        '框 EMA 秒数：大=稳，小=紧跟（0.015-0.050）'),
    'deadband_px':     ('死区半径', 0.0, 8.0, 0.5,
                        '死区内完全不动：锁定后微晃就加大（1-4）'),
    'lead_min_speed':  ('引导噪声门', 0.0, 120.0, 5.0,
                        '目标速度低于此值引导=0：静止目标仍晃就加大'),
    'lead_fade_radius': ('引导衰减', 0.0, 40.0, 1.0,
                         '接近准星时引导逐渐关闭（8-16）'),
    'max_move_speed':  ('移动限速', 600.0, 9600.0, 100.0,
                        '最大 px/s：大幅甩动太猛就调小'),
    'lock_y':          ('锁定垂直位', 0.0, 1.0, 0.01,
                        '0=框顶 0.2=头 0.5=中心 1=框底'),
    'aim_range':       ('触发半径', 20.0, 200.0, 5.0,
                        '目标距准星超过此 px 不瞄'),
    'lock_sen':        ('灵敏度换算', 0.5, 3.0, 0.05,
                        '像素→dots：填游戏灵敏度倍数'),
    'confidence':      ('检测置信度', 0.1, 0.95, 0.05,
                        'v5 约 0.75，v11 约 0.45-0.55'),
}

_GROUPS = [
    ('手感 / Feel', ['move_rate', 'track_tau', 'deadband_px',
                     'lead_min_speed', 'lead_fade_radius', 'max_move_speed']),
    ('目标 / Target', ['lock_y', 'aim_range', 'lock_sen', 'confidence']),
]

_ACCENT = '#4f8cff'
_GREEN = '#39d98a'


def _fmt(value, resolution):
    if resolution >= 1.0:
        return '{:.0f}'.format(value)
    decimals = max(0, int(round(-math.log10(resolution))))
    return '{:.{prec}f}'.format(value, prec=decimals)


def refresh():
    """Re-derive the module-level constants targeting.py baked at import."""
    import aimbot.targeting as tgt
    tgt._INV_SEN = 1.0 / config.lock_sen
    tgt._AIM_RANGE_SQ = config.aim_range * config.aim_range
    tgt._LEAD_FADE_R = config.lead_fade_radius
    tgt._LEAD_MIN = config.lead_min_speed
    tgt._DEADBAND = config.deadband_px


def save():
    """Write the current values back into config.py (regex, keeps comments)."""
    path = config.__file__
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    for name in KNOBS:
        value = getattr(config, name)
        rep = repr(value) if isinstance(value, float) else str(value)
        text, n = re.subn(
            r'^{} = .*$'.format(re.escape(name)),
            '{} = {}'.format(name, rep),
            text, count=1, flags=re.MULTILINE)
        if n == 0:
            print('[ui] config.py: {} not found (not saved)'.format(name))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print('[ui] config.py saved')


if ctk is not None:
    class Tuner:
        """The CustomTkinter window; built lazily inside its own thread."""

        def __init__(self):
            ctk.set_appearance_mode('dark')
            ctk.set_default_color_theme('dark-blue')
            self.root = ctk.CTk()
            self.root.title('Aim Tuner')
            self.root.attributes('-topmost', True)
            self.root.resizable(False, False)
            self._values = {}
            self._build()
            self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        def _build(self):
            header = ctk.CTkFrame(self.root, corner_radius=0, fg_color='transparent')
            header.pack(fill='x')
            ctk.CTkLabel(
                header, text='瞄准调参面板',
                font=ctk.CTkFont(size=18, weight='bold')).pack(
                side='left', padx=18, pady=(14, 8))
            self._status = ctk.CTkLabel(
                header, text='● 运行中', text_color=_GREEN,
                font=ctk.CTkFont(size=12))
            self._status.pack(side='right', padx=18)

            for group_name, names in _GROUPS:
                box = ctk.CTkFrame(self.root, corner_radius=10)
                box.pack(fill='x', padx=14, pady=(8, 2))
                ctk.CTkLabel(
                    box, text=group_name, text_color='#8a93a6',
                    font=ctk.CTkFont(size=12, weight='bold')).pack(
                    anchor='w', padx=14, pady=(10, 2))
                for name in names:
                    self._knob(box, name)
                box.pack_propagate(True)

            footer = ctk.CTkFrame(self.root, fg_color='transparent')
            footer.pack(fill='x', padx=14, pady=(10, 14))
            ctk.CTkButton(
                footer, text='保存到 config.py', command=self._save_clicked,
                fg_color=_ACCENT, hover_color='#3d78e6', corner_radius=8,
            ).pack(side='right', ipadx=10, ipady=3)

        def _knob(self, parent, name):
            label, lo, hi, res, hint = KNOBS[name]
            value = getattr(config, name)

            row = ctk.CTkFrame(parent, fg_color='transparent')
            row.pack(fill='x', padx=14, pady=(4, 0))
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13)).pack(
                side='left')
            value_label = ctk.CTkLabel(
                row, text=_fmt(value, res), text_color=_ACCENT,
                width=64, anchor='e',
                font=ctk.CTkFont(size=13, weight='bold'))
            value_label.pack(side='right')
            self._values[name] = value_label

            scale = ctk.CTkSlider(
                parent, from_=lo, to=hi,
                number_of_steps=int(round((hi - lo) / res)),
                command=lambda v, n=name: self._on_slide(n, float(v)),
                progress_color=_ACCENT, button_color=_ACCENT,
                button_hover_color='#3d78e6', height=18)
            scale.set(value)
            scale.pack(fill='x', padx=14, pady=(0, 2))

            ctk.CTkLabel(
                parent, text=hint, text_color='#6b7386',
                font=ctk.CTkFont(size=11), anchor='w').pack(
                fill='x', padx=14)

        def _on_slide(self, name, value):
            _, lo, hi, res, _ = KNOBS[name]
            value = min(hi, max(lo, round(value / res) * res))
            setattr(config, name, value)
            self._values[name].configure(text=_fmt(value, res))
            refresh()

        def _save_clicked(self):
            save()
            self._status.configure(text='● 已保存', text_color=_GREEN)
            self.root.after(1200, lambda: self._status.configure(
                text='● 运行中', text_color=_GREEN))

        def _on_close(self):
            # Keep the process runnable; the window just hides.
            self.root.withdraw()

        def run(self):
            self.root.mainloop()


    _thread = None


    def start():
        """Open the tuner window in a daemon thread (idempotent)."""
        global _thread
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, daemon=True)
        _thread.start()


    def _run():
        try:
            Tuner().run()
        except Exception as e:
            print('[ui] tuner failed: {}'.format(e))

else:
    def start():
        pass
