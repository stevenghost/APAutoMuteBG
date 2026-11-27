import ctypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C


def parse_hotkey(spec):
    """把 "F12" / "Ctrl+Shift+F12" 解析成 (modifiers, vk)，失败返回 None。"""
    if not spec:
        return None
    mods = 0
    vk = None
    for part in str(spec).upper().replace(' ', '').split('+'):
        if part in ('CTRL', 'CONTROL'):
            mods |= MOD_CONTROL
        elif part == 'ALT':
            mods |= MOD_ALT
        elif part == 'SHIFT':
            mods |= MOD_SHIFT
        elif part in ('WIN', 'WINDOWS'):
            mods |= MOD_WIN
        elif part.startswith('F') and part[1:].isdigit():
            n = int(part[1:])
            if 1 <= n <= 24:
                vk = 0x70 + n - 1
        elif len(part) == 1 and part.isalnum():
            vk = ord(part)
        else:
            return None
    return (mods, vk) if vk is not None else None


def _down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def modifiers_match(mods):
    if bool(mods & MOD_CONTROL) != _down(_VK_CONTROL):
        return False
    if bool(mods & MOD_SHIFT) != _down(_VK_SHIFT):
        return False
    if bool(mods & MOD_ALT) != _down(_VK_MENU):
        return False
    if bool(mods & MOD_WIN) != (_down(_VK_LWIN) or _down(_VK_RWIN)):
        return False
    return True


def key_down(vk):
    return _down(vk)
