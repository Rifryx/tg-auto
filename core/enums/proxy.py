from enum import Enum


class ProxyType(str, Enum):
    """Тип прокси (PROJECT-STAGES §1.3)."""

    SOCKS5 = "socks5"
    HTTP = "http"


class ProxyStatus(str, Enum):
    """Статус живости прокси (PROJECT-STAGES §1.3)."""

    ALIVE = "alive"
    DEAD = "dead"
    UNCHECKED = "unchecked"
