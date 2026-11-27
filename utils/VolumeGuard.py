import threading

_lock = threading.Lock()
# pid -> (session, 原始音量)
_registry = {}


def register(pid, session, volume):
    """记录被本程序改动过的音频会话及其原始音量。"""
    with _lock:
        _registry[int(pid)] = (session, float(volume))


def unregister(pid):
    with _lock:
        _registry.pop(int(pid), None)


def restore_all(logger=None):
    """退出前把记录过的会话音量恢复成原始值。"""
    with _lock:
        items = list(_registry.items())
        _registry.clear()

    for pid, (session, volume) in items:
        try:
            session.SimpleAudioVolume.SetMasterVolume(volume, None)
            if logger:
                logger.info("Restored volume for pid %s to %.2f.", pid, volume)
        except Exception as exc:  # 会话可能已随进程退出而失效
            if logger:
                logger.warning("Failed to restore volume for pid %s: %s", pid, exc)
