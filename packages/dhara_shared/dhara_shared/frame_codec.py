"""Codec for the 16-byte packed-binary uplink frame ("sixteen bytes on the
radio") that a Tier-1 farm edge box sends. Comfortably inside a 51-byte
LoRaWAN payload at spreading factor 12 on IN865.

Byte layout:
  0      frame type/version   uint8
  1-2    sequence number      uint16
  3-4    moisture @15cm       uint16, hundredths of a percent
  5-6    moisture @30cm       uint16, hundredths of a percent
  7-8    moisture @60cm       uint16, hundredths of a percent
  9-10   soil temperature     int16, tenths of a degree C
  11-12  battery              uint16, millivolts
  13-14  flow counter         uint16, litres (cumulative, wraps at 65535)
  15     status bits          8 flags (bit0 tamper, bit1 dry_run, bit2 valve_fault,
                                        bit3 low_battery, bit4 stuck_valve,
                                        bit5-7 reserved)
"""
import struct
from dataclasses import dataclass

FRAME_STRUCT = struct.Struct(">BHHHHhHHB")  # big-endian to match network byte order
FRAME_TYPE_UPLINK_V1 = 0x01

STATUS_TAMPER = 0b0000_0001
STATUS_DRY_RUN = 0b0000_0010
STATUS_VALVE_FAULT = 0b0000_0100
STATUS_LOW_BATTERY = 0b0000_1000
STATUS_STUCK_VALVE = 0b0001_0000


@dataclass
class UplinkFrame:
    frame_type: int
    sequence: int
    moisture_15cm_pct: float
    moisture_30cm_pct: float
    moisture_60cm_pct: float
    soil_temp_c: float
    battery_mv: int
    flow_litres_cumulative: int
    status_bits: int

    @property
    def tamper(self) -> bool:
        return bool(self.status_bits & STATUS_TAMPER)

    @property
    def dry_run(self) -> bool:
        return bool(self.status_bits & STATUS_DRY_RUN)

    @property
    def valve_fault(self) -> bool:
        return bool(self.status_bits & STATUS_VALVE_FAULT)

    @property
    def low_battery(self) -> bool:
        return bool(self.status_bits & STATUS_LOW_BATTERY)

    @property
    def stuck_valve(self) -> bool:
        return bool(self.status_bits & STATUS_STUCK_VALVE)


def encode_uplink(
    sequence: int,
    moisture_15cm_pct: float,
    moisture_30cm_pct: float,
    moisture_60cm_pct: float,
    soil_temp_c: float,
    battery_mv: int,
    flow_litres_cumulative: int,
    status_bits: int = 0,
) -> bytes:
    return FRAME_STRUCT.pack(
        FRAME_TYPE_UPLINK_V1,
        sequence & 0xFFFF,
        int(round(moisture_15cm_pct * 100)) & 0xFFFF,
        int(round(moisture_30cm_pct * 100)) & 0xFFFF,
        int(round(moisture_60cm_pct * 100)) & 0xFFFF,
        int(round(soil_temp_c * 10)),
        battery_mv & 0xFFFF,
        flow_litres_cumulative & 0xFFFF,
        status_bits & 0xFF,
    )


def decode_uplink(raw: bytes) -> UplinkFrame:
    if len(raw) != FRAME_STRUCT.size:
        raise ValueError(f"expected {FRAME_STRUCT.size}-byte frame, got {len(raw)} bytes")
    (frame_type, seq, m15, m30, m60, temp10, batt, flow, status) = FRAME_STRUCT.unpack(raw)
    return UplinkFrame(
        frame_type=frame_type,
        sequence=seq,
        moisture_15cm_pct=m15 / 100.0,
        moisture_30cm_pct=m30 / 100.0,
        moisture_60cm_pct=m60 / 100.0,
        soil_temp_c=temp10 / 10.0,
        battery_mv=batt,
        flow_litres_cumulative=flow,
        status_bits=status,
    )
