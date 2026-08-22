"""Coffee-machine models and protocol-level information decoders."""

from __future__ import annotations

from .enums import (
    BrewType,
    ErrorCode,
    Ingredient,
    MachineType,
    Temperature,
    Temprature,
)

__all__ = [
    "BlueMachine",
    "BrewType",
    "CoffeeMachine",
    "CoffeeMachineFactory",
    "ConnectivityFirmwareVersion",
    "ErrorCode",
    "ExpertMachine",
    "Ingredient",
    "MachineType",
    "ProdigioMachine",
    "ProdigoMachine",
    "Temperature",
    "Temprature",
    "VTP2Machine",
    "VersionInformation",
    "decode_machine_information",
    "decode_pairing_key_state",
    "get_error_message",
    "get_machine_type_from_model_name",
    "supported",
]


def get_machine_type_from_model_name(model_name: str | None) -> MachineType | None:
    """Return the machine type encoded in a Bluetooth model name."""

    if not model_name:
        return None

    normalized_name = model_name.upper()
    return next(
        (machine_type for machine_type in MachineType if machine_type.name in normalized_name),
        None,
    )


def supported(name: str | None) -> MachineType | None:
    """Return the matching machine type, or ``None`` if it is unsupported."""

    return get_machine_type_from_model_name(name)


class CoffeeMachine:
    """Description and capabilities of a connected coffee machine."""

    def __init__(
        self,
        model: MachineType | None,
        name: str = "default",
        serial: str = "default",
    ) -> None:
        self.model = model
        self.name = name
        self.serial = serial
        self.fw_version: str | None = None
        self.hw_version: str | None = None
        self.configurations = self.default_configurations()

    def default_configurations(self) -> dict[str, bool]:
        """Return capabilities shared by all supported machines."""

        return {
            "temperature_control": False,
            # Keep the old key available to third-party callers.
            "temprature_control": False,
            "custom_recipes": False,
        }

    def __repr__(self) -> str:
        return f"Name: {self.name}\nSerial: {self.serial}"


class ExpertMachine(CoffeeMachine):
    def __init__(self, name: str, serial: str) -> None:
        super().__init__(MachineType.EXPERT, name, serial)

    def default_configurations(self) -> dict[str, bool]:
        configurations = super().default_configurations()
        configurations.update(
            {
                "temperature_control": True,
                "temprature_control": True,
                "custom_recipes": True,
            }
        )
        return configurations


class VTP2Machine(CoffeeMachine):
    def __init__(self, name: str, serial: str) -> None:
        super().__init__(MachineType.VTP2, name, serial)


class ProdigioMachine(CoffeeMachine):
    def __init__(self, name: str, serial: str) -> None:
        super().__init__(MachineType.PRODIGIO, name, serial)


# Compatibility for users importing the old misspelling.
ProdigoMachine = ProdigioMachine


class BlueMachine(CoffeeMachine):
    def __init__(self, name: str, serial: str) -> None:
        super().__init__(MachineType.BLUE, name, serial)


class CoffeeMachineFactory:
    """Create the model-specific machine representation."""

    _MACHINE_CLASSES = {
        MachineType.BLUE: BlueMachine,
        MachineType.EXPERT: ExpertMachine,
        MachineType.PRODIGIO: ProdigioMachine,
        MachineType.VTP2: VTP2Machine,
    }

    @classmethod
    def get_coffee_machine(cls, model_name: str, serial: str) -> CoffeeMachine:
        model = get_machine_type_from_model_name(model_name)
        machine_class = cls._MACHINE_CLASSES.get(model)
        if machine_class is None:
            return CoffeeMachine(model, model_name, serial)
        return machine_class(model_name, serial)


def get_error_message(error_code: bytes) -> str:
    """Return a readable message for a protocol error code."""

    try:
        return ErrorCode(error_code).name.replace("_", " ").title()
    except ValueError:
        return f"Unknown Error({error_code})"


def decode_machine_information(byte_array: bytes | bytearray) -> dict[str, str | None]:
    """Decode the 14-byte machine-information characteristic."""

    if len(byte_array) < 14:
        raise ValueError(
            f"Machine information must contain at least 14 bytes, got {len(byte_array)}"
        )

    def bytes_to_int(byte_pair: bytes | bytearray) -> int:
        return int.from_bytes(byte_pair, byteorder="big")

    def bytes_to_mac_address(address: bytes | bytearray) -> str:
        return ":".join(f"{byte:02x}" for byte in address)

    hardware_version = bytes_to_int(byte_array[0:2])
    bootloader_version = bytes_to_int(byte_array[2:4])
    main_firmware_version = bytes_to_int(byte_array[4:6])
    connectivity_firmware_version = bytes_to_int(byte_array[6:8])

    return {
        "Hardware Version": VersionInformation(hardware_version).format_standard_version(),
        "Bootloader Version": VersionInformation(bootloader_version).format_standard_version(),
        "Main Firmware Version": VersionInformation(
            main_firmware_version
        ).format_standard_version(),
        "Connectivity Firmware Version": ConnectivityFirmwareVersion(
            connectivity_firmware_version
        ).format_standard_version(),
        "Device Address": bytes_to_mac_address(byte_array[8:14]),
    }


def decode_pairing_key_state(byte_buffer: bytes | bytearray) -> str:
    """Decode the pairing-key state reported by the machine."""

    if not byte_buffer:
        raise ValueError("Pairing-key state must contain at least one byte")

    pairing_key_state = byte_buffer[0]
    if pairing_key_state in (0, 1):
        return "ABSENT"
    if pairing_key_state == 2:
        return "PRESENT"
    if pairing_key_state == 3:
        return "UNDEFINED"
    raise ValueError(f"Undefined PairingKeyState: {pairing_key_state}")


class VersionInformation:
    MAJOR_VERSION_MULTIPLIER = 100

    def __init__(self, version: int) -> None:
        self.version = version

    def get_major_version(self) -> int:
        return self.version // self.MAJOR_VERSION_MULTIPLIER

    def get_minor_version(self) -> int:
        return self.version % self.MAJOR_VERSION_MULTIPLIER

    def is_available(self) -> bool:
        return self.version > 0

    def format_standard_version(self) -> str | None:
        if not self.is_available():
            return None
        return f"{self.get_major_version()}.{self.get_minor_version()}"


class ConnectivityFirmwareVersion:
    MAJOR_VERSION_MULTIPLIER = 10000
    MINOR_VERSION_MULTIPLIER = 100

    def __init__(self, version: int) -> None:
        self.version = version

    def get_build_version(self) -> int:
        return self.version % self.MINOR_VERSION_MULTIPLIER

    def get_major_version(self) -> int:
        return self.version // self.MAJOR_VERSION_MULTIPLIER

    def get_minor_version(self) -> int:
        return (self.version % self.MAJOR_VERSION_MULTIPLIER) // self.MINOR_VERSION_MULTIPLIER

    def is_available(self) -> bool:
        return self.version > 0

    def format_standard_version(self) -> str | None:
        if not self.is_available():
            return None
        return f"{self.get_major_version()}.{self.get_minor_version()}.{self.get_build_version()}"
