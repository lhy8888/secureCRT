from types import SimpleNamespace
import pytest
from harbor_terminal.serial_config import SerialSettings,discover_ports
from harbor_terminal.transport import SerialTransport


@pytest.mark.parametrize('flow,flags',[
    ('none',(False,False,False)),('rtscts',(False,True,False)),
    ('dsrdtr',(False,False,True)),('xonxoff',(True,False,False))])
def test_flow_modes_are_explicit_and_mutually_exclusive(flow,flags):
    options=SerialSettings(baudrate=9600,bytesize=7,parity='E',stopbits=2,flow_control=flow).port_options()
    assert (options['xonxoff'],options['rtscts'],options['dsrdtr'])==flags
    assert (options['bytesize'],options['parity'],options['stopbits'])==(7,'E',2)


@pytest.mark.parametrize('options',[{'baudrate':0},{'baudrate':1.5},{'parity':'bad'},
                                   {'bytesize':9},{'stopbits':3},{'flow_control':'all'}])
def test_invalid_settings_rejected_before_device_open(options):
    with pytest.raises(ValueError):SerialSettings(**options)


def test_vendor_virtual_port_inventory_is_not_filtered_by_name(monkeypatch):
    ports=[SimpleNamespace(device=r'COM127',description='Moxa virtual COM',hwid='test-vendor',serial_number='test-device'),
           SimpleNamespace(device='COM3',description='USB serial',hwid='test-usb',serial_number=None)]
    monkeypatch.setattr('harbor_terminal.serial_config.list_ports.comports',lambda:ports)
    found=discover_ports()
    assert {x['device'] for x in found}=={'COM127','COM3'}
    assert found[0]['hwid']=='test-vendor'


async def test_serial_configuration_reaches_driver_and_closes(monkeypatch):
    class Driver:
        def __init__(self,device,**options):self.device=device;self.options=options;self.closed=False
        def close(self):self.closed=True
    monkeypatch.setattr('harbor_terminal.transport.serial.Serial',Driver)
    client=SerialTransport()
    await client.connect('COM127',baudrate=9600,bytesize=7,parity='E',stopbits=2,flow_control='rtscts')
    driver=client.port
    assert driver.device=='COM127'
    assert driver.options['rtscts'] and driver.options['bytesize']==7
    assert driver.options['timeout']==.1 and driver.options['write_timeout']==2
    await client.close()
    assert driver.closed
