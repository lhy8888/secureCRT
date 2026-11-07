"""Validated serial settings; no device names are fabricated by the UI."""
from dataclasses import dataclass

from serial.tools import list_ports


@dataclass(frozen=True)
class SerialSettings:
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = 'N'
    stopbits: float = 1
    flow_control: str = 'none'

    def __post_init__(self):
        if type(self.baudrate) is not int or not 50 <= self.baudrate <= 4_000_000:
            raise ValueError('Baud rate must be between 50 and 4,000,000')
        if self.bytesize not in (5, 6, 7, 8):
            raise ValueError('Data bits must be 5, 6, 7 or 8')
        if self.parity not in ('N', 'E', 'O', 'M', 'S'):
            raise ValueError('Invalid parity')
        if isinstance(self.stopbits, bool) or self.stopbits not in (1, 1.5, 2):
            raise ValueError('Invalid stop bits')
        if self.flow_control not in ('none', 'rtscts', 'dsrdtr', 'xonxoff'):
            raise ValueError('Select one flow control method')

    def port_options(self):
        return dict(baudrate=self.baudrate, bytesize=self.bytesize,
                    parity=self.parity, stopbits=self.stopbits,
                    xonxoff=self.flow_control == 'xonxoff',
                    rtscts=self.flow_control == 'rtscts',
                    dsrdtr=self.flow_control == 'dsrdtr')


def discover_ports():
    """Use the OS/driver inventory, including virtual COM and vendor devices."""
    return [dict(device=p.device, description=p.description or '',
                 hwid=p.hwid or '', serial_number=p.serial_number or '')
            for p in sorted(list_ports.comports(), key=lambda p: p.device)]
