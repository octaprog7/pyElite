"""
elite_core.py — детерминированное ядро порта «pyElite» (6502 -> CPython).

Назначение модуля: перенести игровую математику из ассемблера в чистый Python 3.10+,
чтобы результаты (цены, прыжки, описания планет, PRNG) совпадали с оригиналом.
Ядро не содержит ни CLI, ни UI — только состояние и движки; критичные части
можно позже перенести на C++/Rust, а логи вести через SQLite.

Оригинальная версия: дизассемблирование C64/BBC-версии Elite.
Использованы файлы и диапазоны строк src/:

- src/code_6a00.asm
    145-170   randomize_once — один шаг регистра «Twins» (генерация галактики)
    556-653   get_system_info/TT24 — параметры системы (экономика, правительство,
              техуровень, население, производительность, радиус)
    695-720   galactic_chart/TT22 — перечисление 256 систем галактики
    1631-1724 _TT111 — расстояние между системами: sqrt(dx^2+(dy>>1)^2)*4
    1793-1799 проверка прыжка (RANGE?): дальность движка и топливо
    2222-2230 _73dd — списание топлива (расход = младший byte расстояния)
    2298-2315 _745a — списание PLAYER_CASH (4-байтовое big-endian, цепочка sbc)
    2412-2416 цена топлива = (70 - PLAYER_FUEL) * 2 внутренние единицы (0.1 Cr)
    2465-2466 заправка: ldx #$46; stx PLAYER_FUEL (всегда до полного)
    2613-2614 отказ при нехватке кредитов (bcs _764b)
    2725-2738 price_list (шкала цен: .word 300 = 30.0 Cr, т.е. единица = 0.1 Cr)
    2747-2784 _76e9 — имя системы по слогам
    4424-4450 get_random_number_clc / get_random_number (BBC: DORND)
- src/save_data.asm
    159       PLAYER_CASH: 1000 единиц = "100.00 cr"
    160       PLAYER_FUEL: 70 = "7.0" (10 единиц = 1 световой год)
    169       SHIP_HOLD (вместимость трюма Cobra MkIII)
- src/code_28ba.asm
    2006-2007 eject_escapepod (BBC: ESCAPE)
    2068-2071 заправка нового корабля (бесплатно, $46 = 70 единиц)
    3944-3951 копирование последних 4 байт seed системы в seed «goat soup»
              seed
- src/text/text_docked.asm        285-560 — токены $5B..$80 (описания планет)
- src/text/text_docked_code.asm   275-309 — выбор шаблона описания планеты 0-4
- src/text/text_flight.asm        427-493 — категории товаров
- src/vars_main.asm               210-227 — PLAYER_CARGO
- src/vars_ships.asm              88-90   — флаги кораблей (pirate/angry)
- src/vars_zeropage.asm           31-34   — комментарий про «goat soup»

Терминология PRNG: TUT/DODIV — канонические имена подпрограмм BBC Micro Elite
(см. bbcelite.com); в C64-порте регистру соответствует ZP_GOATSOUP_pt1..pt4
(src/code_6a00.asm:4439-4449), а шагу — get_random_number (DORND). Внешних
зависимостей нет; модуль `random` не используется.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Final, Iterator, Protocol, Sequence, TypeAlias

# --------------------------------------------------------------------------
# Data tables — the single source of truth
# --------------------------------------------------------------------------

# Base seed of galaxy 0 (ELITE_SEED, 6 little-endian bytes):
# src/elite.inc:119 (.define ELITE_SEED $5a4a,$0248,$b753),
# src/save_data.asm:158 (.word ELITE_SEED ; SEED_GALAXY).
SEED_GALAXY_0: Final[tuple[int, int, int, int, int, int]] = (
    0x4A,  # W0_LO
    0x5A,  # W0_HI
    0x48,  # W1_LO
    0x02,  # W1_HI
    0x53,  # W2_LO
    0xB7,  # W2_HI
)

# 32 letter pairs for system names (src/text/text_pairs.asm:126-157).
# Index 15 — "A?" (the second char '?' marks "no second letter").
NAME_PAIRS: Final[tuple[str, ...]] = (
    "AL", "LE", "XE", "GE", "ZA", "CE", "BI", "SO",
    "US", "ES", "AR", "MA", "IN", "DI", "RE", "A",
    "ER", "AT", "EN", "BE", "RA", "LA", "VE", "TI",
    "ED", "OR", "QU", "AN", "TE", "IS", "RI", "ON",
)

# Economies (index = economy byte 0-7, src/code_6a00.asm:569-571)
ECONOMIES: Final[tuple[str, ...]] = (
    "Rich Industrial", "Average Industrial", "Poor Industrial",
    "Mainly Industrial", "Mainly Agricultural", "Rich Agricultural",
    "Average Agricultural", "Poor Agricultural",
)

# Governments (index = government byte 0-7, src/code_6a00.asm:579-584)
GOVERNMENTS: Final[tuple[str, ...]] = (
    "Anarchy", "Feudal", "Multi-government", "Dictatorship",
    "Communist", "Confederacy", "Democracy", "Corporate State",
)

# Commodities: 17 categories (src/text/text_flight.asm:427-493,
# src/vars_main.asm:210-227). The 17th ("Alien Items") is unavailable on the
# market (MARKET_ALIENS zeroed in _731a, src/code_6a00.asm:2094).
COMMODITIES: Final[tuple[str, ...]] = (
    "Food", "Textiles", "Radioactives", "Slaves", "Liquor/Wines",
    "Luxuries", "Narcotics", "Computers", "Machinery", "Alloys",
    "Firearms", "Furs", "Minerals", "Gold", "Platinum", "Gem-stones",
    "Alien Items",
)

# Commodity table: (base_price, flags, base_qty, noise_mask).
# src/code_6a00.asm:6405-6420 (labels _90a5.._90a8):
#   bit 7 of flags  — gradient sign (1 = price/qty grow with the economy);
#   bits 5-6        — units of measure (00=T, 01=KG, 10=g);
#   bits 0-4        — gradient magnitude.
MARKET_TABLE: Final[tuple[tuple[int, int, int, int], ...]] = (
    (0x13, 0x82, 0x06, 0x01),  #  0 Food         $13/$82/$06/$01
    (0x14, 0x81, 0x0A, 0x03),  #  1 Textiles     $14/$81/$0A/$03
    (0x41, 0x83, 0x02, 0x07),  #  2 Radioactives $41/$83/$02/$07
    (0x28, 0x85, 0xE2, 0x1F),  #  3 Slaves       $28/$85/$E2/$1F
    (0x53, 0x85, 0xFB, 0x0F),  #  4 Liquor/Wines $53/$85/$FB/$0F
    (0xC4, 0x08, 0x36, 0x03),  #  5 Luxuries     $C4/$08/$36/$03
    (0xEB, 0x1D, 0x08, 0x78),  #  6 Narcotics    $EB/$1D/$08/$78
    (0x9A, 0x0E, 0x38, 0x03),  #  7 Computers    $9A/$0E/$38/$03
    (0x75, 0x06, 0x28, 0x07),  #  8 Machinery    $75/$06/$28/$07
    (0x4E, 0x01, 0x11, 0x1F),  #  9 Alloys       $4E/$01/$11/$1F
    (0x7C, 0x0D, 0x1D, 0x07),  # 10 Firearms     $7C/$0D/$1D/$07
    (0xB0, 0x89, 0xDC, 0x3F),  # 11 Furs         $B0/$89/$DC/$3F
    (0x20, 0x81, 0x35, 0x03),  # 12 Minerals     $20/$81/$35/$03
    (0x61, 0xA1, 0x42, 0x07),  # 13 Gold         $61/$A1/$42/$07
    (0xAB, 0xA2, 0x37, 0x1F),  # 14 Platinum     $AB/$A2/$37/$1F
    (0x2D, 0xC1, 0xFA, 0x0F),  # 15 Gem-stones   $2D/$C1/$FA/$0F
)

# Units of measure by flags bits 5-6 (src/code_6a00.asm:1993-2036)
UNIT_BY_FLAGS: Final[tuple[str, str, str, str]] = ("T", "KG", "g", "g")

# Cobra MkIII cargo capacity (src/save_data.asm:169)
SHIP_HOLD: Final[int] = 22
# Precious cargo limit — 200 units/kg of each kind (src/code_6a00.asm:85)
PRECIOUS_LIMIT: Final[int] = 200
# Jameson's starting cash: 1000 units = "100.00 cr" (src/save_data.asm:159)
STARTING_CASH_UNITS: Final[int] = 1000

# Fuel and refuelling (see the module header):
#   tank 70 units = 7.0 ly (src/save_data.asm:160, src/code_6a00.asm:858,
#   2412: lda #$46); scale 10 units = 1 ly;
#   price = (70 - fuel) * 2 internal units (0.1 Cr) => 0.2 Cr/unit =
#   2.0 Cr per ly (src/code_6a00.asm:2412-2416, price scale 2725-2738);
#   refuelling always to full (src/code_6a00.asm:2465-2466).
FUEL_TANK_CAPACITY: Final[int] = 70
FUEL_PRICE_PER_UNIT_CR: Final[float] = 0.2
# Hard engine limit: distance >= 256 units -> jump impossible
# (src/code_6a00.asm:1793-1794)
ENGINE_MAX_RANGE_UNITS: Final[int] = 256

# Ship defense: all three layers are 0-255 bytes
# (FSH, ASH, ENERGY — bbcelite.com/compare/main/subroutine/reset.html)
SHIP_DEFENSE_MAX: Final[int] = 255

# System danger by government (BBC: DANGER, canonical disassembly table,
# see bbcelite.com/main/variable/danger.html; in the C64 port pirate
# encounters are tied to PSYSTEM_GOVERNMENT in the main flight loop).
DANGER_TABLE: Final[tuple[int, ...]] = (249, 199, 149, 99, 49, 49, 19, 19)

# Planet description word groups (tokens $5B..$80,
# src/text/text_docked.asm:285-560; group comments $A0..$A4, $2E..$32,
# $42..$46 etc.)
DESC_ADJ1: Final[tuple[str, ...]] = (
    "fabled", "notable", "well-known", "famous", "noted")
DESC_ADJ2: Final[tuple[str, ...]] = (
    "very", "mildly", "most", "reasonably")
DESC_ADJ3: Final[tuple[str, ...]] = (
    "ancient", "funny", "weird", "unusual", "strange",
    "peculiar", "great", "vast", "pink")
DESC_GEO: Final[tuple[str, ...]] = (
    "plantations", "mountains", "parking meters", "dust clouds",
    "ice bergs", "rock formations", "volcanoes", "forests", "oceans")
DESC_ANIMAL: Final[tuple[str, ...]] = (
    "shrew", "beast", "bison", "snake", "wolf", "leopard", "cat",
    "monkey", "goat", "fish", "walking treeoid", "craboid", "lobstoid",
    "poet", "arts graduate", "yak", "snail", "slug", "wasp", "moth",
    "grub", "ant")
DESC_KILLER: Final[tuple[str, ...]] = (
    "killer", "deadly", "evil", "lethal", "vicious")
DESC_DRINK: Final[tuple[str, ...]] = (
    "juice", "brandy", "water", "brew", "gargle blasters")
DESC_NOUN: Final[tuple[str, ...]] = (
    "food blenders", "tourists", "poetry", "discos", "cuisine",
    "night life", "casinos", "sit coms")

# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

Cargo: TypeAlias = list[int]           # 17 categories (PLAYER_CARGO)
SystemRow: TypeAlias = dict[str, int | str]
MarketRow: TypeAlias = dict[str, int | float | str]


@dataclass(frozen=True)
class ResultBase:
    """Базовый класс результатов движков (успех / причина отказа).

    Все Result-классы ядра — frozen dataclass, наследующие этот базовый
    класс, чтобы любой результат можно было проверить единообразно:
    `result.success` / `result.error_reason`.
    """

    success: bool
    error_reason: str | None = None

    def __bool__(self) -> bool:
        """bool(result) == result.success — позволяет писать `if result:`."""
        return self.success


@dataclass(frozen=True)
class JumpResult(ResultBase):
    """Результат гиперпрыжка (заменил прежний `TypeAlias = dict`).

    Поля соответствуют ключам старого словаря: distance_units, distance_ly,
    fuel_cost, new_fuel, current_system.
    """

    distance_units: int = 0
    distance_ly: float = 0.0
    fuel_cost: int = 0
    new_fuel: int = 0
    current_system: int = 0


@dataclass(frozen=True)
class RefuelResult(ResultBase):
    """Refuelling result (src/code_6a00.asm:2412-2466)."""

    cost: float = 0.0    # Cr
    new_fuel: float = 0.0  # units


@dataclass(frozen=True)
class CombatResult(ResultBase):
    """Combat resolution result (core math)."""

    action: str = ""                     # "fight" | "escape" | "surrender"
    message: str = ""
    status: str = ""                     # i18n key suffix
    fuel_used: int = 0                   # units
    credits_lost: float = 0.0            # Cr
    cargo_lost: tuple[int, ...] = ()     # how many units of each category
    detail: int = 0                      # aux: escape_no_fuel → need units
    destroyed: bool = False              # ship destroyed (ENERGY <= 0)
    ouch_lost: str = ""                  # item lost via OUCH, "" if none


# --------------------------------------------------------------------------
# EngineBase — общая база всех движков ядра
# --------------------------------------------------------------------------


class EngineBase(ABC):
    """Общий базовый класс движков ядра (ABC).

    Единый контракт движка: «принять контекст (генератор галактик + номер
    галактики) → вычислить → вернуть результат (frozen dataclass)».
    Конструктор принимает необязательный generator/galaxy: движки, которым
    генератор не нужен (FuelEngine, CombatEngine), вызываются без аргументов
    (как и раньше, публичный API GameState не меняется).
    """

    def __init__(
        self, generator: GalaxyGenerator | None = None, galaxy: int = 0
    ) -> None:
        self.generator: GalaxyGenerator | None = generator
        self._galaxy: int = galaxy & 0x07

    def _validate_system(self, system: int) -> None:
        """Проверка номера системы 0-255 (ValueError при недопустимом)."""
        if not isinstance(system, int) or not 0 <= system < 256:
            raise ValueError(
                f"system {system!r} does not exist (valid range 0-255)")


# --------------------------------------------------------------------------
# DeterministicRNG — the original PRNG (BBC: DORND / "goat soup")
# --------------------------------------------------------------------------


class DeterministicRNG:
    """
    Deterministic PRNG from Elite (BBC: DORND, "Twins"/TUT register).

    The register is 4 bytes (ZP_GOATSOUP_pt1..pt4,
    src/code_6a00.asm:4439-4449). One step (`next_byte`) reproduces
    `get_random_number` (DORND) with carry-in 0, i.e. the equivalent of
    `get_random_number_clc` (src/code_6a00.asm:4424-4426) — as assumed in
    the trading port (market noise). In the original this register is also
    called "goat soup": its seed for planet descriptions is copied from the
    last 4 bytes of the system seed (src/code_28ba.asm:3944-3951).

    The names TUT/DODIV are canonical for BBC Micro Elite (bbcelite.com):
    TUT — temporary PRNG bytes, DODIV — random-number-with-division routine.
    Here the range generators are built on masks/division following the
    assembler range restrictions (e.g. the description-template thresholds
    $33/$66/$99/$CC, src/text/text_docked_code.asm:288-298).
    """

    def __init__(self, seed: Sequence[int] | None = None) -> None:
        if seed is None:
            seed = SEED_GALAXY_0[:4]  # starting register bytes
        self._reg: list[int] = [int(b) & 0xFF for b in seed][:4]
        while len(self._reg) < 4:
            self._reg.append(0)

    @property
    def state(self) -> tuple[int, int, int, int]:
        """Current register state (4 bytes)."""
        return (self._reg[0], self._reg[1], self._reg[2], self._reg[3])

    def next_byte(self) -> int:
        """
        One DORND step (src/code_6a00.asm:4431-4450), returns A (= pt2):

            lda pt1 / rol (carry-in 0) / tax ; X = (pt1<<1)&FF
            adc pt3 / sta pt1 / stx pt3      ; pt1 = X + pt3 (+carry)
            lda pt2 / tax / adc pt4          ; Y = pt2 + pt4 (+carry)
            sta pt2 / stx pt4                ; pt2 = Y
        """
        p1, p2, p3, p4 = self._reg

        t: int = ((p1 << 1) | 0) & 0xFF   # A after ROL (carry-in 0)
        carry: int = p1 >> 7              # old bit 7 -> carry
        s: int = t + p3 + carry
        self._reg[0] = s & 0xFF           # sta pt1
        self._reg[2] = t                  # stx pt3
        carry = s >> 8
        t = p2
        s = p2 + p4 + carry
        self._reg[1] = s & 0xFF           # sta pt2
        self._reg[3] = t                  # stx pt4
        return self._reg[1]

    def next_word(self) -> int:
        """16-bit random number (two DORND calls)."""
        return (self.next_byte() << 8) | self.next_byte()

    def next_range(self, min_value: int, max_value: int) -> int:
        """Random integer in [min_value, max_value] inclusive.

        Modulo division is a DODIV simplification (in assembly the ranges
        are usually defined by masks, e.g. and #%00011111 in
        src/code_6a00.asm:2875).
        """
        span: int = max_value - min_value + 1
        return min_value + (self.next_byte() % span)

    def pick(self, values: Sequence[str]) -> str:
        """Random element via threshold split of 0-255 (original style).

        Divides the 0-255 range into len(values) equal bands and returns
        the element whose band contains next_byte(). This matches the
        original's threshold-based selection (e.g. $33/$66/$99/$CC for
        5-element groups, src/text/text_docked_code.asm:286-298).
        """
        n = len(values)
        if n <= 1:
            return values[0]
        byte = self.next_byte()
        band = 256 // n
        index = min(byte // band, n - 1)
        return values[index]

    # ------------------------------------------------------------------

    def __iter__(self) -> DeterministicRNG:
        """PRNG как бесконечный итератор случайных байт (для islice и т.п.)."""
        return self

    def __next__(self) -> int:
        """Следующий случайный байт (эквивалент next_byte())."""
        return self.next_byte()


# --------------------------------------------------------------------------
# GalaxyGenerator — deterministic generation of 8 galaxies x 256 systems
# --------------------------------------------------------------------------


class GalaxyGenerator(EngineBase):
    """
    Galaxy generator (port of src/code_6a00.asm:133-2784).

    System enumeration advances the 6-byte "Twins" register
    (randomize_once, src/code_6a00.asm:145-170) by 4 steps between systems
    (src/code_6a00.asm:717). Coordinates: X = W1_HI, Y = W0_HI
    (src/code_6a00.asm:699-715); the chart is twice as high as wide —
    therefore dy is halved in distance calculations (2:1 ratio).
    """

    def __init__(self) -> None:
        # GalaxyGenerator не нуждается во внешнем генераторе — он сам
        # генератор. EngineBase.__init__ вызывается с generator=self,
        # чтобы self.generator имел осмысленное значение.
        super().__init__(generator=self, galaxy=0)
        # Кеш готовых галактик: 8 галактик x 256 систем (см. 3.4).
        self._galaxy_cache: dict[int, list[SystemRow]] = {}

    def __len__(self) -> int:
        """Количество систем в галактике (256)."""
        return 256

    @staticmethod
    def galaxy_seed(galaxy_number: int) -> list[int]:
        """Galaxy seed: ELITE_SEED bytes rotated left by N bits (the galaxy
        counter is masked and #%11110111, src/code_6a00.asm:1831)."""
        n: int = galaxy_number & 0x07
        seed: list[int] = list(SEED_GALAXY_0)
        for _ in range(n):
            seed = [((b << 1) | (b >> 7)) & 0xFF for b in seed]
        return seed

    @staticmethod
    def _randomize_once(seed: list[int]) -> None:
        """One "Twins"-register step (src/code_6a00.asm:145-170):
        w2 = w0 + w1 + w2 (bytewise, with carries), words shift left."""
        w0_lo, w0_hi, w1_lo, w1_hi, w2_lo, w2_hi = seed

        t: int = w0_lo + w1_lo
        x: int = t & 0xFF
        carry: int = t >> 8

        t = w0_hi + w1_hi + carry
        y: int = t & 0xFF

        seed[0] = w1_lo
        seed[1] = w1_hi
        seed[2] = w2_lo
        seed[3] = w2_hi

        t = x + w2_lo
        seed[4] = t & 0xFF
        carry = t >> 8
        seed[5] = (y + w2_hi + carry) & 0xFF

    @classmethod
    def _randomize(cls, seed: list[int]) -> None:
        """Full system-enumeration step — 4 x randomize_once
        (src/code_6a00.asm:133-143)."""
        for _ in range(4):
            cls._randomize_once(seed)

    def system_seed(self, galaxy_number: int, system_number: int) -> list[int]:
        """Seed of system N = galaxy seed advanced N times
        (src/code_6a00.asm:717, 1598-1604)."""
        seed: list[int] = self.galaxy_seed(galaxy_number)
        for _ in range(system_number & 0xFF):
            self._randomize(seed)
        return seed

    def _system_data(self, seed: list[int]) -> dict[str, int]:
        """System parameters (src/code_6a00.asm:556-653, get_system_info/TT24),
        including the carries of 6502 arithmetic."""
        w0_lo, w0_hi, w1_lo, w1_hi, w2_lo, w2_hi = seed

        pos_x: int = w1_hi                       # X = high byte of W1
        pos_y: int = w0_hi                       # Y = high byte of W0
        star_size: int = w2_lo                   # star size = low byte W2

        economy: int = w0_hi & 0x07              # W0_HI & 7 (569-571)
        government: int = (w1_lo >> 3) & 0x07    # (W1_LO>>3) & 7 (579-584)
        if government <= 1:                      # anarchy/feudalism cannot be
            economy |= 0x02                      # "rich" (588-593)

        tech_level: int = (economy ^ 0x07) + (w1_hi & 0x03) + government
        tech_level &= 0xFF                       # (598-611)

        acc: int = (tech_level << 2) & 0xFF
        carry: int = 1 if (tech_level & 0x40) else 0
        s: int = acc + economy + carry
        acc, carry = s & 0xFF, s >> 8
        s = acc + government + carry
        acc, carry = s & 0xFF, s >> 8
        s = acc + 1 + carry
        population: int = s & 0xFF               # tenths of a billion (613-620)

        p: int = (economy ^ 0x07) + 3
        q: int = government + 4
        product1: int = p * q
        product2: int = (product1 & 0xFF) * population
        productivity: int = (product2 << 3) & 0xFFFF  # (622-651)

        radius_km: int = ((w2_hi & 0x0F) + 11) * 256  # (530-537)

        return {
            "x": pos_x,
            "y": pos_y,
            "z": star_size,
            "economy": economy,
            "government": government,
            "tech_level": tech_level,
            "population": population,
            "productivity": productivity,
            "radius_km": radius_km,
        }

    def _system_name(self, seed: list[int]) -> str:
        """System name by syllables (src/code_6a00.asm:2747-2784, _76e9)."""
        backup: list[int] = list(seed)
        t: int = 2 if (seed[0] & 0x40) else 3     # 3 or 4 syllables (bit 6 of W0_LO)
        name: list[str] = []
        while t >= 0:
            syllable: int = seed[5] & 0x1F        # W2_HI & %00011111
            if syllable:
                name.append(NAME_PAIRS[syllable])
            self._randomize_once(seed)
            t -= 1
        seed[:] = backup                          # restore the seed
        return "".join(name)

    def generate_galaxy(self, galaxy_number: int) -> list[SystemRow]:
        """Systems of the galaxy; результат кешируется по номеру галактики.

        Кеш экономит повторную генерацию (MarketEngine/JumpEngine/systems
        используют один и тот же инстанс генератора). Возвращаемый список
        НЕ мутируется после создания — все потребители только читают его,
        поэтому детерминизм сохраняется.
        """
        galaxy: int = galaxy_number & 0x07
        if galaxy not in self._galaxy_cache:
            self._galaxy_cache[galaxy] = self._generate_galaxy_impl(galaxy)
        return self._galaxy_cache[galaxy]

    def _generate_galaxy_impl(self, galaxy_number: int) -> list[SystemRow]:
        """Generate the 256 systems of the galaxy (src/code_6a00.asm:695-720)."""
        working_seed: list[int] = self.galaxy_seed(galaxy_number)
        systems: list[SystemRow] = []
        for index in range(256):
            seed: list[int] = list(working_seed)
            data: dict[str, int] = self._system_data(seed)
            name: str = self._system_name(seed)
            systems.append({
                "number": index,
                "x": data["x"],
                "y": data["y"],
                "z": data["z"],
                "economy": data["economy"],
                "government": data["government"],
                "tech_level": data["tech_level"],
                "population": data["population"],
                "productivity": data["productivity"],
                "radius_km": data["radius_km"],
                "name": name,
                "economy_name": ECONOMIES[data["economy"]],
                "government_name": GOVERNMENTS[data["government"]],
            })
            self._randomize(working_seed)
        return systems


# --------------------------------------------------------------------------
# MarketEngine — commodity prices and availability (src/code_6a00.asm:1951-2165)
# --------------------------------------------------------------------------


class MarketError(ValueError):
    """Trading operation error (no commodity/money/space)."""


def commodity_index(item: str | int, lang: str | None = None) -> int:
    """Commodity index by name (case-insensitive/prefix) or number.

    lang — локаль игрока ("ru"/"es"): помимо канонических имён принимаются
    локализованные названия (elite_i18n, prefix-матчинг). Канонические
    имена работают при любой локали. Raises MarketError on invalid input.
    """
    if isinstance(item, int):
        if 0 <= item < len(COMMODITIES):
            return item
        raise MarketError(f"no commodity with index {item}")
    key = str(item).strip().lower()
    for i, name in enumerate(COMMODITIES):
        if name.lower() == key or name.lower().startswith(key):
            return i
    if lang not in (None, "en"):
        # Локализованный ввод (ленивый импорт: ядро не зависит от i18n
        # при каноническом вводе).
        from elite_i18n import resolve_commodity
        idx: int = resolve_commodity(str(item), lang)
        if idx >= 0:
            return idx
    raise MarketError(f"unknown commodity: {item!r}")


class MarketEngine(EngineBase):
    """
    Market of a system. Deterministic: equal (galaxy, system) always give
    equal prices/availability. Price noise is the first DORND byte on the
    system "goat soup" seed (last 4 bytes of the seed,
    src/code_28ba.asm:3944-3951; one get_random_number step on arrival,
    src/code_6a00.asm:2128-2129).

    Commodity price: TT151 (src/code_6a00.asm:1951-1977):
        price = (base + noise (+/-) grad) & 0xFF,  grad = (flags&$1F)*economy;
    availability: _7365 (src/code_6a00.asm:2131-2165):
        qty = (base_qty + noise (+/-) grad) & 0xFF, then the bpl check
        (>= $80 -> 0) and and #%00111111.
    Displayed price = raw * 4 internal units = raw * 0.4 Cr
    (src/code_6a00.asm:2355-2364, _74a5). Buy/sell at the same price.
    """

    def __init__(
        self,
        generator: GalaxyGenerator,
        system_number: int,
        galaxy_number: int = 0,
    ) -> None:
        super().__init__(generator, galaxy_number)
        self._system_number: int = system_number & 0xFF
        self._system: SystemRow = generator.generate_galaxy(self._galaxy)[
            self._system_number]
        self._economy: int = int(self._system["economy"])

        # goat soup seed = last 4 bytes of the system seed (W1_LO..W2_HI)
        sys_seed: list[int] = generator.system_seed(self._galaxy, self._system_number)
        self._rng: DeterministicRNG = DeterministicRNG(sys_seed[2:6])
        market_random: int = self._rng.next_byte()   # MARKET_RANDOM

        self._available: list[int]
        self._price_raw: list[int]
        self._available, self._price_raw = self._build_market(market_random)

    # ------------------------------------------------------------- calculation

    def _build_market(self, market_random: int) -> tuple[list[int], list[int]]:
        """Quantities and prices of all 17 categories (TT151 + _7365)."""
        available: list[int] = [0] * 17
        price_raw: list[int] = [0] * 17

        for i, (base_price, flags, base_qty, noise_mask) in enumerate(MARKET_TABLE):
            noise: int = market_random & noise_mask
            grad: int = (flags & 0x1F) * self._economy
            sign: int = grad if (flags & 0x80) else -grad

            price_raw[i] = (base_price + noise + sign) & 0xFF

            v8: int = (base_qty + noise + sign) & 0xFF
            available[i] = (v8 & 0x3F) if v8 < 0x80 else 0

        # Alien Items unavailable (MARKET_ALIENS = 0, src/code_6a00.asm:2094)
        available[16] = 0
        price_raw[16] = 0
        return available, price_raw

    # ------------------------------------------------------------- access

    @property
    def system(self) -> SystemRow:
        """System data (name, economy, government)."""
        return self._system

    def index(self, item: str | int) -> int:
        """Category index by name (case-insensitive/prefix) or number."""
        if isinstance(item, int):
            if 0 <= item < 17:
                return item
            raise MarketError(f"no commodity with index {item}")
        key = str(item).strip().lower()
        for i, name in enumerate(COMMODITIES):
            if name.lower() == key or name.lower().startswith(key):
                return i
        raise MarketError(f"unknown commodity: {item!r}")

    def unit_name(self, index: int) -> str:
        """Commodity units of measure (flags bits 5-6)."""
        if index < 16:
            return UNIT_BY_FLAGS[(MARKET_TABLE[index][1] >> 5) & 0x03]
        return "T"

    def price_cr(self, index: int) -> float:
        """Price per unit in Cr (raw * 4 / 10; buy == sell)."""
        return (self._price_raw[index] * 4) / 10.0

    def available(self, index: int) -> int:
        """Available quantity on the market."""
        return self._available[index]

    def get_market(self) -> list[MarketRow]:
        """All 17 rows: name, unit, available, price_buy_cr, price_sell_cr."""
        rows: list[MarketRow] = []
        for i in range(17):
            price: float = self.price_cr(i)
            rows.append({
                "name": COMMODITIES[i],
                "unit": self.unit_name(i),
                "available": self._available[i],
                "price_buy_cr": price,
                "price_sell_cr": price,
            })
        return rows

    # ------------------------------------------------------------- pythonic API

    def __len__(self) -> int:
        """Количество категорий товаров (17)."""
        return 17

    def __getitem__(self, key: int | str) -> MarketRow:
        """Строка рынка по индексу (int) или имени товара (str).

        `market[0]` и `market["Food"]` возвращают одну и ту же строку.
        """
        index: int = self.index(key)
        price: float = self.price_cr(index)
        return {
            "name": COMMODITIES[index],
            "unit": self.unit_name(index),
            "available": self._available[index],
            "price_buy_cr": price,
            "price_sell_cr": price,
        }

    def __iter__(self) -> Iterator[MarketRow]:
        """Итерация по всем строкам рынка (17 товаров)."""
        for i in range(17):
            yield self[i]

    # ------------------------------------------------------------- transactions

    def check_buy(self, item: str | int, quantity: int) -> tuple[int, float]:
        """
        Buy check (src/code_6a00.asm:990-1005 + check_cargo_capacity,
        src/code_6a00.asm:24-88): market availability and cargo capacity.
        Returns (index, cost in Cr); raises MarketError on problems.
        Hold space/money are checked by the caller (GameState).
        """
        index: int = self.index(item)
        qty: int = int(quantity)
        if qty <= 0:
            raise MarketError("quantity must be positive")
        if qty > self._available[index]:
            raise MarketError(
                f"only {self._available[index]} {COMMODITIES[index]} on market")
        return index, qty * self.price_cr(index)

    def check_sell(self, item: str | int, quantity: int, cargo: Cargo) -> tuple[int, float]:
        """Sell check (src/code_6a00.asm:1174-1185): cargo availability."""
        index: int = self.index(item)
        qty: int = int(quantity)
        if qty <= 0:
            raise MarketError("quantity must be positive")
        if qty > cargo[index]:
            raise MarketError(f"only {cargo[index]} {COMMODITIES[index]} in cargo")
        return index, qty * self.price_cr(index)

    def commit_buy(self, index: int, qty: int) -> None:
        """Уменьшить доступность после покупки
        (src/code_6a00.asm:990-1005). Привязано к текущему инстансу ---
        месту и сессии стыковки. Сбрасывается при load_system().
        """
        self._available[index] -= qty


# --------------------------------------------------------------------------
# JumpEngine — hyperjumps (src/code_6a00.asm:1631-1724, 1793-1799, 2222-2230)
# --------------------------------------------------------------------------


class JumpEngine(EngineBase):
    """
    Hyperjumps within a galaxy. Distance (_TT111):
        d = sqrt(|dX|^2 + (|dY|>>1)^2) * 4   (units, 1 unit = 0.1 ly),
    Y is halved because the chart is twice as high as wide (2:1 ratio).

    Jump check (src/code_6a00.asm:1793-1799): high byte of the distance
    != 0 (>= 25.6 ly) -> "RANGE?"; fuel below the cost -> "RANGE?".
    Together with the 70-unit tank (7.0 ly) this gives a practical radius
    of 7.0. Cost = low byte of the distance (TSYSTEM_DISTANCE_LO,
    2222-2230): 1 unit per 0.1 ly.
    """

    def __init__(self, generator: GalaxyGenerator, galaxy_number: int = 0) -> None:
        super().__init__(generator, galaxy_number)
        self._systems: list[SystemRow] = generator.generate_galaxy(self._galaxy)

    def __repr__(self) -> str:
        """Краткое описание движка (галактика и жёсткий предел дальности)."""
        return f"JumpEngine(galaxy={self._galaxy}, max_range=25.6 ly)"

    def coords(self, system: int) -> tuple[int, int]:
        """System coordinates (X, Y) = (W1_HI, W0_HI)."""
        self._validate_system(system)
        return int(self._systems[system]["x"]), int(self._systems[system]["y"])

    @staticmethod
    def _square_root(r: int, q_in: int) -> int:
        """
        Integer square root (port of square_root,
        src/math/math_square.asm:203-247, $9978): long-division algorithm,
        8 iterations, state X.Y.S (24 bits).
        """
        x: int = 0
        y: int = r
        s: int = q_in
        q: int = 0
        for _ in range(8):
            if x > q or (x == q and y >= 0x40):
                y -= 0x40
                if y < 0:
                    y += 0x100
                    x -= q + 1
                else:
                    x -= q
                x &= 0xFF
                q = ((q << 1) | 1) & 0xFF
            else:
                q = (q << 1) & 0xFF
            v: int = ((x << 16) | (y << 8) | s) << 2
            v &= 0xFFFFFF
            x = v >> 16
            y = (v >> 8) & 0xFF
            s = v & 0xFF
        return q

    def distance_units(self, current_sys: int, target_sys: int) -> int:
        """16-bit distance in units (0.1 ly), formula _TT111."""
        self._validate_system(current_sys)
        self._validate_system(target_sys)
        ax, ay = self.coords(current_sys)
        bx, by = self.coords(target_sys)
        dx: int = abs(ax - bx)
        dy: int = abs(ay - by)

        total: int = dx * dx + (dy >> 1) * (dy >> 1)
        if total > 0xFFFF:                 # 16-bit overflow -> R=$FF
            r: int = 0xFF
            q: int = total & 0xFF
        else:
            r = (total >> 8) & 0xFF
            q = total & 0xFF
        sq: int = self._square_root(r, q)
        return (sq << 2) & 0xFFFF           # asl/rol twice

    def distance_ly(self, current_sys: int, target_sys: int) -> float:
        """Distance in light years (units / 10)."""
        return self.distance_units(current_sys, target_sys) / 10.0

    def calculate_fuel_cost(self, current_sys: int, target_sys: int) -> int:
        """Fuel cost, units = low byte of the distance
        (TSYSTEM_DISTANCE_LO, src/code_6a00.asm:2224-2230)."""
        return self.distance_units(current_sys, target_sys) & 0xFF

    def can_jump(self, current_sys: int, target_sys: int, current_fuel: int) -> bool:
        """Can we jump (src/code_6a00.asm:1793-1799)."""
        try:
            self._validate_system(current_sys)
            self._validate_system(target_sys)
        except ValueError:
            return False
        if current_fuel < 0:
            return False
        distance16: int = self.distance_units(current_sys, target_sys)
        if (distance16 >> 8) != 0:             # TSYSTEM_DISTANCE_HI != 0
            return False
        return current_fuel >= (distance16 & 0xFF)

    def execute_jump(
        self, current_sys: int, target_sys: int, current_fuel: int
    ) -> JumpResult:
        """Perform the jump; returns a JumpResult (success/error_reason/
        distance/fuel_cost/new_fuel/current_system; fuel deduction —
        src/code_6a00.asm:2222-2230)."""
        for sys in (current_sys, target_sys):
            try:
                self._validate_system(sys)
            except ValueError as exc:
                return JumpResult(
                    success=False, error_reason=str(exc),
                    new_fuel=current_fuel, current_system=current_sys)
        if current_fuel < 0:
            return JumpResult(
                success=False, error_reason="negative fuel",
                new_fuel=current_fuel, current_system=current_sys)

        distance16: int = self.distance_units(current_sys, target_sys)
        cost: int = distance16 & 0xFF
        if (distance16 >> 8) != 0:
            return JumpResult(
                success=False,
                error_reason="too far: out of engine jump range",
                distance_units=distance16, distance_ly=distance16 / 10.0,
                fuel_cost=cost, new_fuel=current_fuel,
                current_system=current_sys)
        if current_fuel < cost:
            return JumpResult(
                success=False, error_reason="not enough fuel",
                distance_units=distance16, distance_ly=distance16 / 10.0,
                fuel_cost=cost, new_fuel=current_fuel,
                current_system=current_sys)

        return JumpResult(
            success=True,
            distance_units=distance16, distance_ly=distance16 / 10.0,
            fuel_cost=cost, new_fuel=current_fuel - cost,
            current_system=target_sys)


# --------------------------------------------------------------------------
# FuelEngine — refuelling (src/code_6a00.asm:2412-2466)
# --------------------------------------------------------------------------


class FuelEngine(EngineBase):
    """
    Fuel refuelling.

    Tank: 70 units = 7.0 ly (src/save_data.asm:160, src/code_6a00.asm:858,
    2412: lda #$46). Price = (70 - fuel) * 2 internal units (0.1 Cr) =
    (70 - fuel) * 0.2 Cr (src/code_6a00.asm:2412-2416; price scale — 0.1 Cr
    per unit, src/code_6a00.asm:2725-2738). Refuelling is ALWAYS to full
    (src/code_6a00.asm:2465-2466: ldx #$46; stx PLAYER_FUEL) — partial is
    impossible. On insufficient credits — refusal (src/code_6a00.asm:2298-2315,
    2613-2614).
    """

    def __init__(self) -> None:
        super().__init__()
        self.capacity: int = FUEL_TANK_CAPACITY
        self.price_per_unit_cr: float = FUEL_PRICE_PER_UNIT_CR

    def __repr__(self) -> str:
        """Краткое описание движка (ёмкость бака и цена топлива)."""
        return (f"FuelEngine({self.capacity} units, "
                f"{self.price_per_unit_cr} Cr/unit)")

    def cost_to_full(self, current_fuel: float) -> float:
        """Full-refuel cost in Cr: (70 - fuel) * 0.2."""
        room: float = float(self.capacity) - current_fuel
        return max(room, 0.0) * self.price_per_unit_cr

    def refuel(self, current_fuel: float, credits: float) -> RefuelResult:
        """Attempt to refuel to full. Returns a RefuelResult."""
        fuel_now: float = float(current_fuel)
        room: int = self.capacity - int(round(fuel_now))
        if room <= 0:
            return RefuelResult(
                success=False, cost=0.0, new_fuel=fuel_now,
                error_reason="tank already full")

        cost: float = room * self.price_per_unit_cr
        if credits < cost:
            return RefuelResult(
                success=False, cost=cost, new_fuel=fuel_now,
                error_reason=(
                    f"not enough credits: need {cost:.2f} Cr, "
                    f"have {credits:.2f} Cr"))

        return RefuelResult(success=True, cost=cost,
                            new_fuel=float(self.capacity))


# --------------------------------------------------------------------------
# SystemDescriptionEngine — planet descriptions ("goat soup")
# --------------------------------------------------------------------------


class SystemDescriptionEngine(EngineBase):
    """
    Deterministic planet description generator.

    The algorithm matches the original:
      1. "goat soup" seed = last 4 bytes of the system seed
         (src/code_28ba.asm:3944-3951, vars_zeropage.asm:31-34);
      2. the first DORND byte picks template 0-4 by the thresholds
         $33/$66/$99/$CC (src/text/text_docked_code.asm:286-298);
      3. subsequent bytes substitute words from the token groups
         (src/text/text_docked.asm:285-560, groups $A0..$A4, $2E..$32 etc.).

    The {name}/{economy}/{government} insertions come from the system data
    (the original prints "<name> is ..." as the first line).
    """

    # Переопределение EngineBase.generator: здесь генератор ОБЯЗАТЕЛЕН
    # (без None), поэтому type: ignore не требуется.
    generator: GalaxyGenerator

    # Five templates: tuple of phrases; each phrase is a tuple of slots,
    # where "{...}" is a word/data substitution, otherwise a literal.
    TEMPLATES: Final[tuple[tuple[tuple[str, ...], ...], ...]] = (
        (("<NAME> is a <ECONOMY> world.",),
         ("It is <ADJ2> famous for its <GEO>.",),
         ("The natives are <ADJ1> <ANIMAL>-like.",)),
        (("<NAME> is <ADJ1> known for its <NOUN>.",),
         ("The people are <KILLER> <ANIMAL> hunters.",),
         ("Tourists enjoy the local <DRINK>.",)),
        (("A <ADJ3> civilisation on <NAME>.",),
         ("Its <GEO> attract <ADJ2> many visitors.",),
         ("Inhabitants are <ADJ1> friendly <ANIMAL> herders.",)),
        (("<NAME> is plagued by <KILLER> <ANIMAL>s.",),
         ("Local <NOUN> are <ADJ2> popular.",),
         ("The <GEO> are <ADJ3>.",)),
        (("This system is <ADJ3>.",),
         ("Its <GEO> and <ANIMAL>s are unique.",),
         ("The <DRINK> is <ADJ2> good.",)),
    )

    # Slot map -> word groups (description tokens, text_docked.asm:285-560)
    SLOT_GROUPS: Final[dict[str, tuple[str, ...]]] = {
        "<ADJ1>": DESC_ADJ1,
        "<ADJ2>": DESC_ADJ2,
        "<ADJ3>": DESC_ADJ3,
        "<GEO>": DESC_GEO,
        "<ANIMAL>": DESC_ANIMAL,
        "<KILLER>": DESC_KILLER,
        "<DRINK>": DESC_DRINK,
        "<NOUN>": DESC_NOUN,
    }

    def __init__(self, generator: GalaxyGenerator) -> None:
        super().__init__(generator)

    def _description_rng(self, galaxy: int, system_number: int) -> DeterministicRNG:
        """Description RNG on the system "goat soup" seed."""
        sys_seed: list[int] = self.generator.system_seed(galaxy, system_number)
        return DeterministicRNG(sys_seed[2:6])  # W1_LO..W2_HI (copy, 3944-3951)

    def generate_description(
        self,
        system_index: int,
        rng: DeterministicRNG | None = None,
        galaxy: int = 0,
        lang: str = "en",
    ) -> str:
        """
        Description of system `system_index`. If rng is not passed, a new
        RNG is created from the system "goat soup" seed (the description is
        deterministic and does not depend on the game history).

        lang: "en" — канонические таблицы ядра (оригинал); "ru"/"es" —
        переводы из elite_i18n (таблицы 1:1 с английскими, тот же seed
        даёт дословно соответствующее описание).
        """
        local_rng: DeterministicRNG = (
            rng if rng is not None else self._description_rng(galaxy, system_index)
        )

        # template choice 0-4 (src/text/text_docked_code.asm:286-298):
        # thresholds $33/$66/$99/$CC on the first random byte
        roll: int = local_rng.next_byte()
        template: int = 4
        for threshold, tpl in ((0x33, 0), (0x66, 1), (0x99, 2), (0xCC, 3)):
            if roll < threshold:
                template = tpl
                break

        system: SystemRow = self.generator.generate_galaxy(galaxy)[
            system_index & 0xFF]
        if lang == "en":
            templates = self.TEMPLATES
            groups = self.SLOT_GROUPS
            economy_name: str = str(system["economy_name"]).lower()
        else:
            # Переводы живут в elite_i18n (ленивый импорт — при английском
            # описании ядро не зависит от i18n).
            from elite_i18n import desc_tables
            tables = desc_tables(lang)   # ValueError для неизвестной локали
            templates = tables.templates
            groups = dict(tables.groups)
            economy_name = tables.economies[int(system["economy"])].lower()
        placeholders: dict[str, str] = {
            "<NAME>": str(system["name"]),
            "<ECONOMY>": economy_name,
            "<GOVERNMENT>": str(system["government_name"]).lower(),
        }

        sentences: list[str] = []
        for phrase in templates[template]:
            text: str = phrase[0]
            for slot, group in groups.items():
                if slot in text:
                    text = text.replace(slot, local_rng.pick(group))
            for key, value in placeholders.items():
                text = text.replace(key, value)
            sentences.append(text)
        return " ".join(sentences)


# --------------------------------------------------------------------------
# ShipDefense — three-layer ship defense (FSH, ASH, ENERGY)
# --------------------------------------------------------------------------


@dataclass
class ShipDefense:
    """Three-layer ship defense (BBC Elite: FSH, ASH, ENERGY).

    OOPS: damage → shield → energy → death.
    OUCH: ~4.5% chance to lose cargo when shields are breached.
    RESET: full recharge on docking (FSH=ASH=ENERGY=255).
    """

    forward_shield: int = SHIP_DEFENSE_MAX
    aft_shield: int = SHIP_DEFENSE_MAX
    energy: int = SHIP_DEFENSE_MAX

    def __str__(self) -> str:
        """Три слоя защиты одной строкой: FSH/ASH/EN."""
        return (
            f"FSH {self.forward_shield}/{SHIP_DEFENSE_MAX} "
            f"ASH {self.aft_shield}/{SHIP_DEFENSE_MAX} "
            f"EN {self.energy}/{SHIP_DEFENSE_MAX}"
        )

    # -- OOPS (bbcelite.com/master/main/subroutine/oops.html) --

    def take_damage(
        self, amount: int, from_rear: bool
    ) -> tuple[bool, bool]:
        """Apply damage to shield, then energy. Returns (destroyed, ouch_needed).

        OOPS logic: shield -= damage (SBC); if shield < 0 → shield = 0,
        overflow to ENERGY; if ENERGY <= 0 → destroyed.
        """
        if from_rear:
            shield: int = self.aft_shield
        else:
            shield = self.forward_shield

        new_shield: int = shield - amount
        if new_shield >= 0:
            # Shield absorbed the hit
            if from_rear:
                self.aft_shield = new_shield
            else:
                self.forward_shield = new_shield
            return False, False

        # Shield overflowed — excess goes to energy
        overflow: int = -new_shield
        if from_rear:
            self.aft_shield = 0
        else:
            self.forward_shield = 0

        new_energy: int = self.energy - overflow
        if new_energy <= 0:
            self.energy = 0
            return True, False          # destroyed, no OUCH

        self.energy = new_energy
        return False, True             # survived, OUCH needed

    # -- OUCH (bbcelite.com/master/main/subroutine/ouch.html) --

    def ouch(self, rng: DeterministicRNG, cargo: Cargo) -> str:
        """~4.5% chance to lose a cargo item. Returns name or ''.

        DORND → A, X; A < 0 (50%) → nothing; X >= 22 (91%) → nothing;
        cargo[X] == 0 → nothing; else cargo[X] = 0.
        Equipment (indices 17-21) not implemented yet.
        """
        a: int = rng.next_byte()
        if a >= 128:                   # A < 0 (50%)
            return ""
        x: int = rng.next_byte()
        if x >= 22:                     # 91%
            return ""
        if x < 17:
            if cargo[x] == 0:
                return ""
            cargo[x] = 0
            return COMMODITIES[x]
        # Equipment 17-21: not yet implemented
        return ""

    # -- SHD (bbcelite.com/disc/flight/subroutine/shd.html) --

    def recharge(self, rounds: int = 1) -> None:
        """Shield + energy recharge (abstracts main loop Part 13).

        Shields charge +1 each (cost 1 energy) if energy >= 128.
        Energy recharges +1 per round.
        """
        for _ in range(rounds):
            if self.energy >= 128:
                if self.aft_shield < SHIP_DEFENSE_MAX:
                    self.aft_shield = min(self.aft_shield + 1,
                                         SHIP_DEFENSE_MAX)
                    self.energy -= 1
                if self.forward_shield < SHIP_DEFENSE_MAX:
                    self.forward_shield = min(self.forward_shield + 1,
                                              SHIP_DEFENSE_MAX)
                    self.energy -= 1
            self.energy = min(self.energy + 1, SHIP_DEFENSE_MAX)

    @property
    def destroyed(self) -> bool:
        """ENERGY <= 0 → ship destroyed."""
        return self.energy <= 0

    def reset(self) -> None:
        """Full recharge (RES4: FSH=ASH=ENERGY=$FF)."""
        self.forward_shield = SHIP_DEFENSE_MAX
        self.aft_shield = SHIP_DEFENSE_MAX
        self.energy = SHIP_DEFENSE_MAX


# --------------------------------------------------------------------------
# CombatEngine — combat encounters (core math, no 3D)
# --------------------------------------------------------------------------


class CombatEngine(EngineBase):
    """
    Resolution of random pirate encounters.

    The attack chance depends on the system government:
    probability = DANGER[gov]/256 (canonical BBC Elite table, see
    bbcelite.com; in the C64 port the pirate/angry flags are
    src/vars_ships.asm:88-90). Money/cargo deduction on defeat and surrender
    follows the PLAYER_CASH subtraction pattern
    (src/code_6a00.asm:2298-2315); escape spends fuel (like a jump,
    src/code_6a00.asm:2222-2230) and on failure loses part of the cargo.
    """

    def __init__(self) -> None:
        super().__init__()
        self.danger_table: tuple[int, ...] = DANGER_TABLE

    def attack_chance(self, government: int) -> float:
        """Attack probability for a government 0-7."""
        return self.danger_table[government & 0x07] / 256.0

    def check_pirate_attack(self, rng: DeterministicRNG, government: int) -> bool:
        """Attack? Random byte < DANGER[government]."""
        return rng.next_byte() < self.danger_table[government & 0x07]

    # ------------------------------------------------------------------

    def resolve(
        self,
        action: str,
        rng: DeterministicRNG,
        *,
        fuel: float,
        credits: float,
        cargo: Cargo,
        tech_level: int,
        defense: ShipDefense,
    ) -> CombatResult:
        """Player action: "fight" | "escape" | "surrender".

        Damage model (OOPS): pirate hits go to forward shield (fight)
        or aft shield (escape); overflow drains ENERGY; ENERGY <= 0 → death.
        OUCH: ~4.5% chance to lose a cargo item when shields are breached.
        """
        act: str = action.strip().lower()
        if act not in ("fight", "escape", "surrender"):
            raise ValueError(f"unknown action: {action!r}")

        if act == "fight":
            # 3-5 rounds of pirate fire, all to forward shield
            rounds: int = rng.next_range(3, 6)
            total: int = sum(rng.next_range(40, 120) for _ in range(rounds))
            destroyed, ouch_needed = defense.take_damage(total, from_rear=False)

            if destroyed:
                return CombatResult(
                    action="fight", success=False,
                    message="Your ship has been destroyed!",
                    status="destroyed", destroyed=True)

            ouch_lost: str = ""
            if ouch_needed:
                ouch_lost = defense.ouch(rng, cargo)

            odds: int = (0x80 + (tech_level & 0x07) * 8) & 0xFF
            if rng.next_byte() < odds:
                return CombatResult(
                    action="fight", success=True,
                    message="You fought off the pirates.",
                    status="fight_win", ouch_lost=ouch_lost)
            lost = self._lose_fraction(cargo, 0.25)
            credits_lost: float = credits * 0.20
            return CombatResult(
                action="fight", success=False,
                message="The pirates overpowered you: cargo and 20% "
                        "of credits lost.",
                status="fight_lose",
                credits_lost=credits_lost, cargo_lost=lost,
                ouch_lost=ouch_lost)

        if act == "escape":
            # 1-2 rounds of pirate fire to aft shield (running away)
            rounds = rng.next_range(1, 3)
            total = sum(rng.next_range(30, 80) for _ in range(rounds))
            destroyed, ouch_needed = defense.take_damage(total, from_rear=True)

            if destroyed:
                return CombatResult(
                    action="escape", success=False,
                    message="Your ship has been destroyed!",
                    status="destroyed", destroyed=True)

            ouch_lost = ""
            if ouch_needed:
                ouch_lost = defense.ouch(rng, cargo)

            need: int = 1 + rng.next_byte() % 10
            if fuel < need:
                return CombatResult(
                    action="escape", success=False,
                    message=f"Not enough fuel to escape ({need} units).",
                    status="escape_no_fuel", detail=need,
                    ouch_lost=ouch_lost)
            if rng.next_byte() < min(255, int(fuel) * 3):
                return CombatResult(
                    action="escape", success=True,
                    message=f"Escape jump succeeded ({need} units spent).",
                    status="escape_success", fuel_used=need,
                    ouch_lost=ouch_lost)
            lost = self._lose_fraction(cargo, 0.15)
            return CombatResult(
                action="escape", success=False,
                message="Escape failed: pirates knocked off part of the cargo.",
                status="escape_fail", fuel_used=need, cargo_lost=lost,
                ouch_lost=ouch_lost)

        # surrender — no damage
        credits_lost = credits * rng.next_range(10, 50) / 100.0
        lost = self._lose_fraction(cargo, 0.25)
        return CombatResult(
            action="surrender", success=True,
            message="You surrendered: pirates took part of the credits "
                    "and cargo.",
            status="surrender",
            credits_lost=credits_lost, cargo_lost=lost)

    # ------------------------------------------------------------------

    @staticmethod
    def _lose_fraction(cargo: Cargo, fraction: float) -> tuple[int, ...]:
        """Which cargo volumes are lost (deterministically by quantile)."""
        lost: list[int] = []
        for qty in cargo:
            keep: int = int(qty * (1.0 - fraction))
            lost.append(max(qty - keep, 0))
        return tuple(lost)


# --------------------------------------------------------------------------
# GameState — unified game state (no CLI)
# --------------------------------------------------------------------------


class EventLoggerProtocol(Protocol):
    """Duck-typed интерфейс журнала событий (реализация:
    elite_analytics.EventLogger).

    elite_core НЕ импортирует elite_analytics — логгер передаётся в
    GameState как объект, а методы вызываются по имени (утиная типизация).
    """

    def capture(self, gs: GameState) -> None: ...

    def log_buy(self, gs: GameState, item: str, qty: int,
                unit_price: float, total_cost: float) -> None: ...

    def log_sell(self, gs: GameState, item: str, qty: int,
                 unit_price: float, total_cost: float) -> None: ...

    def log_jump(self, gs: GameState, target_index: int, target_name: str,
                 distance_ly: float, fuel_cost: int) -> None: ...

    def log_refuel(self, gs: GameState, cost: float, new_fuel: float) -> None: ...

    def log_combat(self, gs: GameState, action: str, details: str) -> None: ...

    def log_wait(self, gs: GameState, details: str) -> None: ...


class GameState:
    """
    Game state: galaxy, system, fuel, credits, cargo + engines.

    Fields: galaxy, system_index, fuel, credits, cargo, rng (game PRNG),
    generator, market, jump_engine, fuel_engine, combat_engine.
    Methods only read/change the state and delegate to engines — no I/O.
    """

    def __init__(
        self,
        galaxy: int = 0,
        system_index: int = 0,
        fuel: float = float(FUEL_TANK_CAPACITY),
        credits: float = STARTING_CASH_UNITS / 10.0,   # 1000 units = 100.00 Cr
        cargo: Cargo | None = None,
        rng_seed: Sequence[int] | None = None,
        event_logger: EventLoggerProtocol | None = None,  # SQLite event log
    ) -> None:
        self.generator: GalaxyGenerator = GalaxyGenerator()
        self.galaxy: int = galaxy & 0x07
        self.system_index: int = system_index & 0xFF
        self.fuel: float = float(fuel)
        self.credits: float = float(credits)
        self.cargo: Cargo = list(cargo) if cargo is not None else [0] * 17

        # game PRNG (combat and other in-session randomness)
        self.rng: DeterministicRNG = DeterministicRNG(rng_seed)

        self.jump_engine: JumpEngine = JumpEngine(self.generator, self.galaxy)
        self.fuel_engine: FuelEngine = FuelEngine()
        self.combat_engine: CombatEngine = CombatEngine()
        self.defense: ShipDefense = ShipDefense()
        self.description_engine: SystemDescriptionEngine = (
            SystemDescriptionEngine(self.generator))

        self._systems: list[SystemRow] | None = None
        self._systems_galaxy: int | None = None
        self.market: MarketEngine = self._build_market()

        # Логгер событий (None — логирование отключено; duck typing,
        # см. EventLoggerProtocol).
        self.event_logger: EventLoggerProtocol | None = event_logger

    # ------------------------------------------------------------- pythonic API

    def __str__(self) -> str:
        """Краткий статус: галактика, система, топливо, кредиты, груз."""
        return (
            f"Galaxy {self.galaxy} | #{self.system_index} "
            f"{self.system['name']} ({self.system['economy_name']}) | "
            f"Fuel {self.fuel:.0f}/{FUEL_TANK_CAPACITY} "
            f"({self.fuel / 10:.1f} ly) | "
            f"{self.credits:.2f} Cr | "
            f"Cargo {self.cargo_weight}/{SHIP_HOLD} t"
        )

    def __repr__(self) -> str:
        """Компактное представление для отладки."""
        return (
            f"GameState(galaxy={self.galaxy}, "
            f"system_index={self.system_index}, "
            f"fuel={self.fuel}, credits={self.credits})"
        )

    # ------------------------------------------------------------- chart

    @property
    def systems(self) -> list[SystemRow]:
        """Chart of the current galaxy (cache)."""
        if self._systems is None or self._systems_galaxy != self.galaxy:
            self._systems = self.generator.generate_galaxy(self.galaxy)
            self._systems_galaxy = self.galaxy
        return self._systems

    @property
    def system(self) -> SystemRow:
        """Data of the current system."""
        return self.systems[self.system_index]

    # ------------------------------------------------------------- market

    def _build_market(self) -> MarketEngine:
        return MarketEngine(self.generator, self.system_index, self.galaxy)

    def load_system(self) -> None:
        """Rebuild the market of the current system (deterministically)."""
        self.market = self._build_market()
        self.defense.reset()   # docking = full recharge (RES4: FSH=ASH=ENERGY=$FF)

    # ------------------------------------------------------------- fuel

    def update_fuel(self, amount: float) -> float:
        """Change fuel clamped to [0, 70] (clamp, as in the game)."""
        self.fuel = min(max(self.fuel + amount, 0.0), float(FUEL_TANK_CAPACITY))
        return self.fuel

    @property
    def cargo_weight(self) -> int:
        """Occupied hold tonnes (Food..Minerals, sum of PLAYER_CARGO[:13])."""
        return sum(self.cargo[:13])

    # ------------------------------------------------------------- trading

    def buy(self, item: str | int, qty: int, lang: str | None = None) -> float:
        """
        Buy a commodity (src/code_6a00.asm:990-1005 + hold 24-88):
        market check, hold space, money. Returns the cost in Cr.

        lang — локаль игрока для разбора локализованных названий;
        в журнал и API уходит каноническое имя.
        """
        if isinstance(item, str) and lang not in (None, "en"):
            item = COMMODITIES[commodity_index(item, lang)]
        index, cost = self.market.check_buy(item, qty)
        if index <= 12:                             # Food..Minerals — tonnes
            if self.cargo_weight + qty > SHIP_HOLD:
                raise MarketError(f"cargo hold full ({SHIP_HOLD} t)")
        elif self.cargo[index] + qty > PRECIOUS_LIMIT:
            raise MarketError(f"limit {PRECIOUS_LIMIT} {self.market.unit_name(index)}")
        if self.credits < cost:
            raise MarketError(
                f"not enough credits: need {cost:.2f} Cr, "
                f"have {self.credits:.2f} Cr")

        self.credits -= cost
        self.cargo[index] += qty
        self.market.commit_buy(index, qty)   # доступность уменьшается после покупки

        # --- логирование события (если логгер задан) ---
        if self.event_logger is not None:
            item_name = COMMODITIES[index] if isinstance(item, int) else str(item)
            self.event_logger.log_buy(self, item_name, qty, cost / qty, cost)

        return cost

    def sell(self, item: str | int, qty: int,
             lang: str | None = None) -> float:
        """Sell a commodity (src/code_6a00.asm:1174-1185). Returns income.

        lang — локаль игрока для разбора локализованных названий;
        в журнал и API уходит каноническое имя."""
        if isinstance(item, str) and lang not in (None, "en"):
            item = COMMODITIES[commodity_index(item, lang)]
        index, income = self.market.check_sell(item, qty, self.cargo)
        self.credits += income
        self.cargo[index] -= qty

        # --- логирование события (если логгер задан) ---
        if self.event_logger is not None:
            item_name = COMMODITIES[index] if isinstance(item, int) else str(item)
            self.event_logger.log_sell(self, item_name, qty, income / qty, income)

        return income

    # ------------------------------------------------------------- jumps

    def near_systems(self) -> list[tuple[int, str, int, int]]:
        """Systems reachable at the current fuel (can_jump = True):
        (index, name, distance units, fuel cost). Sorted by distance."""
        fuel: int = int(round(self.fuel))
        result: list[tuple[int, str, int, int]] = []
        for i in range(256):
            if i == self.system_index:
                continue
            if self.jump_engine.can_jump(self.system_index, i, fuel):
                dist: int = self.jump_engine.distance_units(self.system_index, i)
                result.append((i, str(self.systems[i]["name"]), dist, dist & 0xFF))
        result.sort(key=lambda row: row[2])
        return result

    def jump(self, target_index: int) -> JumpResult:
        """Jump to a system: can_jump -> execute_jump -> update state.
        On success: new system, fuel, market rebuild."""
        if not 0 <= target_index < 256:
            return JumpResult(
                success=False,
                error_reason=f"system #{target_index} does not exist",
                new_fuel=int(round(self.fuel)),
                current_system=self.system_index)
        fuel: int = int(round(self.fuel))
        result: JumpResult = self.jump_engine.execute_jump(
            self.system_index, target_index, fuel)
        if result:
            self.system_index = result.current_system
            self.fuel = float(result.new_fuel)
            self.load_system()

            # --- логирование события (если логгер задан) ---
            if self.event_logger is not None:
                target_name = str(self.system["name"])
                self.event_logger.log_jump(
                    self, target_index, target_name,
                    float(result.distance_ly), int(result.fuel_cost))
        return result

    # ------------------------------------------------------------- refuel

    def refuel(self) -> RefuelResult:
        """Refuel to full (FuelEngine). Applies changes on success."""
        result: RefuelResult = self.fuel_engine.refuel(self.fuel, self.credits)
        if result:
            self.credits -= result.cost
            self.fuel = result.new_fuel

            # --- логирование события (если логгер задан) ---
            if self.event_logger is not None:
                self.event_logger.log_refuel(self, result.cost, result.new_fuel)
        return result

    # ------------------------------------------------------------- combat

    def check_pirate_attack(self) -> bool:
        """Pirate attack? Probability = DANGER[government]/256."""
        government: int = int(self.system["government"])
        return self.combat_engine.check_pirate_attack(self.rng, government)

    def resolve_combat_action(self, action: str) -> CombatResult:
        """Apply a combat action and change the state."""
        # --- снимок состояния ДО боя (для before/after в логе) ---
        if self.event_logger is not None:
            self.event_logger.capture(self)

        result: CombatResult = self.combat_engine.resolve(
            action, self.rng,
            fuel=self.fuel, credits=self.credits, cargo=self.cargo,
            tech_level=int(self.system["tech_level"]),
            defense=self.defense)
        if result.fuel_used:
            self.update_fuel(-result.fuel_used)
        if result.credits_lost:
            self.credits = max(self.credits - result.credits_lost, 0.0)
        if result.cargo_lost:
            for i, lost in enumerate(result.cargo_lost):
                self.cargo[i] = max(self.cargo[i] - lost, 0)

        # --- логирование боя (если логгер задан) ---
        if self.event_logger is not None:
            # EventLogger использует "pirate_attack" для fight (см. схему БД).
            action_map = {
                "fight": "pirate_attack",
                "flee": "escape",
                "surrender": "surrender",
            }
            log_action = action_map.get(action, action)
            self.event_logger.log_combat(self, log_action, result.message)

        return result

    # ------------------------------------------------------------- wait

    def wait_turn(self) -> None:
        """Wait one turn: shields/energy +1 (main loop Part 13).

        Как в оригинале, рынок и опасность привязаны к прыжкам:
        ожидание НЕ обновляет рынок и НЕ перезапускает проверки атак.
        Событие хода пишется в журнал (action="wait")."""
        self.defense.recharge(1)
        if self.event_logger is not None:
            self.event_logger.log_wait(
                self, "waited one turn (shields/energy +1)")

    # ------------------------------------------------------------- description

    def generate_description(self, lang: str = "en") -> str:
        """Deterministic description of the current system ("goat soup").

        lang="en" — оригинальные таблицы ядра; "ru"/"es" — переводы
        из elite_i18n (1:1, тот же seed)."""
        return self.description_engine.generate_description(
            self.system_index, galaxy=self.galaxy, lang=lang)


# --------------------------------------------------------------------------
# Core test (no CLI)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    gs = GameState(galaxy=0, system_index=0)   # TIBEDI, fuel 70, credits 100
    gs.load_system()
    market_tibedi = gs.market.get_market()   # snapshot for the determinism check

    print(f"=== Status: galaxy {gs.galaxy}, system #{gs.system_index} "
          f"{gs.system['name']} ({gs.system['economy_name']}) ===")
    print(gs)

    print("\n=== Market (first 6 rows) ===")
    for row in gs.market.get_market()[:6]:
        print(f"  {row['name']:<15} {row['unit']:<4} available: {row['available']:>4}  "
              f"price: {row['price_buy_cr']:>6.2f} Cr")

    print("\n=== Systems in jump range ===")
    for i, name, dist, cost in gs.near_systems():
        print(f"  #{i:<3} {name:<10} {dist / 10:>5.1f} ly  fuel cost: {cost} units")

    print("\n=== Buying ===")
    try:
        gs.buy("Food", 22)   # TIBEDI market has only 11 Food -> expect refusal
    except MarketError as exc:
        print(f"  (validation) buy Food 22 -> Error: {exc}")
    cost = gs.buy("Food", 10)   # 10 x 9.6 = 96 Cr (fits into 100 Cr)
    print(f"  buy Food 10 -> {cost:.2f} Cr; credits: {gs.credits:.2f} Cr, "
          f"cargo: {gs.cargo_weight}/{SHIP_HOLD} t")

    print("\n=== Jump TIBEDI -> EDINSOIN (#71) ===")
    result = gs.jump(71)
    print(f"  success={result.success}; distance {result.distance_ly:.1f} "
          f"ly; fuel cost {result.fuel_cost} units; fuel after: "
          f"{gs.fuel:.0f}/{FUEL_TANK_CAPACITY} units; system: "
          f"#{gs.system_index} {gs.system['name']}")

    print("\n=== Refuel to full (0.2 Cr/unit) ===")
    ref = gs.refuel()
    print(f"  success={ref.success}; cost={ref.cost:.2f} Cr; "
          f"new_fuel={ref.new_fuel:.0f}; credits: {gs.credits:.2f} Cr")

    print("\n=== System description (goat soup) ===")
    print(f"  {gs.generate_description()}")

    print("\n=== Combat: attack check and action ===")
    attacked = gs.check_pirate_attack()
    print(f"  pirates attack: {attacked}")
    outcome = gs.resolve_combat_action("fight")
    print(f"  resolve('fight') -> {outcome.message}")
    print(f"  lost: credits {outcome.credits_lost:.2f} Cr, "
          f"cargo {sum(outcome.cargo_lost)} units")

    # determinism check: the TIBEDI market and the 0->71 distance must match
    gs2 = GameState(galaxy=0, system_index=0)
    assert gs2.market.get_market() == market_tibedi
    assert gs2.jump_engine.distance_units(0, 71) == 16
    print("\n(determinism confirmed: market and distance 0->71 == 16 units)")