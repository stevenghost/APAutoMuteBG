import os
import sys


def resource_path(relative):
    """返回打包前后都能用的资源路径。

    - PyInstaller 冻结后：资源在 sys._MEIPASS 下；
    - 直接跑源码：资源在项目根目录下。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)
