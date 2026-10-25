"""Reference data: the parts we buy and the suppliers who quote them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Part:
    description: str
    base_price_usd: float


KNOWN_PARTS: dict[str, Part] = {
    "AX-4410": Part("M3 x 10 stainless hex bolt", 0.12),
    "CN-2201": Part("USB-C 24-pin receptacle", 0.38),
    "PCB-7781": Part("6-layer main logic board (bare)", 14.50),
    "BT-5520": Part("Li-ion pouch cell 3.85V 3200mAh", 4.10),
    "DS-6100": Part("6.1in OLED display module", 22.00),
}


@dataclass(frozen=True)
class Supplier:
    name: str
    slug: str  # short id used in file names, e.g. "mueller"
    currency: str
    date_fmt: str  # how this supplier writes dates (strftime pattern)
    decimal_comma: bool = False  # True -> writes 1.234,56 instead of 1,234.56


SUPPLIERS: list[Supplier] = [
    Supplier("Acme Components Inc.", "acme", "USD", "%m/%d/%Y"),
    Supplier("Müller Präzisionsteile GmbH", "mueller", "EUR", "%d.%m.%Y", decimal_comma=True),
    Supplier("Kanto Precision Co., Ltd.", "kanto", "JPY", "%Y/%m/%d"),
]
