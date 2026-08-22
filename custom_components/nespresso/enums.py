"""Enumerations used by Nespresso Bluetooth machines."""

from __future__ import annotations

from enum import Enum, auto


class MachineState(Enum):
    """Operating state reported by a machine."""

    RESET = 0
    HEAT_UP = 1
    READY = 2
    DESCALING_READY = 3
    BREWING = 4
    ADVANCED_SELECTION_MENU = 5
    DESCALING = 6
    STEAM_OUT = 7
    ERROR = 8
    POWER_SAVE = 9
    OVER_HEAT = 10
    DIAGNOSTIC_MODE = 11
    BLE_SETTINGS = 12
    FACTORY_RESET = 13
    WATER_HARDNESS_SETTINGS = 14
    STAND_BY_DELAY_SETTINGS = 15
    UNKNOWN = 16


class WaterIsEmpty(Enum):
    NOT_EMPTY = 0
    EMPTY = 1


class WaterIsFresh(Enum):
    NOT_FRESH = 0
    FRESH = 1


class DescalingNeeded(Enum):
    NOT_NEEDED = 0
    NEEDED = 1


class CapsuleMechanismJammed(Enum):
    NOT_JAMMED = 0
    JAMMED = 1


class SliderOpen(Enum):
    OPEN = 0
    CLOSED = 1


class WaterHardness(Enum):
    LEVEL_0 = 0
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


class MachineType(Enum):
    EXPERT = auto()
    VTP2 = auto()
    BLUE = auto()
    PRODIGIO = auto()


class BrewType(Enum):
    RISTRETTO = 0
    ESPRESSO = 1
    LUNGO = 2
    HOT_WATER = 4
    AMERICANO = 5
    CUSTOM = 7

    def is_brew_applicable_for_machine(self, machine_type: MachineType) -> bool:
        """Return whether this recipe is supported by ``machine_type``."""

        return self in APPLICABLE_BREW.get(machine_type, ())


class Temperature(Enum):
    """Water temperature used for a brew command."""

    LOW = 1
    MEDIUM = 0
    HIGH = 2


# Compatibility for existing automations and callers using the historic typo.
Temprature = Temperature


class Ingredient(Enum):
    COFFEE = 1
    WATER = 2


class CupSizeType(Enum):
    RISTRETTO = auto()
    ESPRESSO = auto()
    LUNGO = auto()
    AMERICANO_COFFEE = auto()
    AMERICANO_WATER = auto()
    AMERICANO_XL_COFFEE = auto()
    AMERICANO_XL_WATER = auto()
    HOT_WATER = auto()
    HOT_WATER_VTP2 = auto()

    def is_cup_size_applicable_for_machine(self, machine_type: MachineType) -> bool:
        """Return whether this cup size is supported by ``machine_type``."""

        return self in APPLICABLE_CUP_SIZES.get(machine_type, ())


class ErrorCode(Enum):
    TRAY_FULL = b"2403"
    LID_NOT_CYCLED = b"2412"
    WRONG_COMMAND = b"3603"


APPLICABLE_CUP_SIZES: dict[MachineType, tuple[CupSizeType, ...]] = {
    MachineType.EXPERT: (
        CupSizeType.RISTRETTO,
        CupSizeType.ESPRESSO,
        CupSizeType.LUNGO,
        CupSizeType.HOT_WATER,
        CupSizeType.AMERICANO_COFFEE,
        CupSizeType.AMERICANO_WATER,
    ),
    MachineType.VTP2: (
        CupSizeType.ESPRESSO,
        CupSizeType.LUNGO,
        CupSizeType.HOT_WATER_VTP2,
        CupSizeType.AMERICANO_COFFEE,
        CupSizeType.AMERICANO_WATER,
        CupSizeType.AMERICANO_XL_COFFEE,
        CupSizeType.AMERICANO_XL_WATER,
    ),
    MachineType.BLUE: (
        CupSizeType.RISTRETTO,
        CupSizeType.ESPRESSO,
        CupSizeType.LUNGO,
    ),
}

APPLICABLE_BREW: dict[MachineType, tuple[BrewType, ...]] = {
    MachineType.EXPERT: (
        BrewType.RISTRETTO,
        BrewType.ESPRESSO,
        BrewType.LUNGO,
        BrewType.HOT_WATER,
        BrewType.AMERICANO,
    ),
    MachineType.VTP2: (
        BrewType.ESPRESSO,
        BrewType.LUNGO,
        BrewType.HOT_WATER,
        BrewType.AMERICANO,
    ),
    MachineType.BLUE: (
        BrewType.RISTRETTO,
        BrewType.ESPRESSO,
        BrewType.LUNGO,
    ),
    MachineType.PRODIGIO: (
        BrewType.RISTRETTO,
        BrewType.ESPRESSO,
        BrewType.LUNGO,
    ),
}
