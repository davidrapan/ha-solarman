"""
.. note:: This section is based on `MODBUS over Serial Line Specification and
    Implementation Guide V1.02`_.

The ADU for Modbus RTU messages differs from Modbus TCP/IP messages. Messages
send over RTU don't have a MBAP header, instead they have an Address field.
This field contains the slave id.  A CRC is appended to the message. Below all
parts of a Modbus RTU message are listed together with their byte size:

+---------------+-----------------+
| **Component** | **Size** (bytes)|
+---------------+-----------------+
| Address field | 1               |
+---------------+-----------------+
| PDU           | N               |
+---------------+-----------------+
| CRC           | 2               |
+---------------+-----------------+

The CRC is calculated from the Address field and the PDU.

Below you see a hexadecimal presentation of request over RTU with Modbus
function code 1. It requests data of slave with 1, starting at coil 100, for
the length of 3 coils:

..
    Note: the backslash in the bytes below are escaped using an extra back
    slash. Without escaping the bytes aren't printed correctly in the HTML
    output of this docs.

    To work with the bytes in Python you need to remove the escape sequences.
    `b'\\x01\\x00d` -> `b\x01\x00d`

.. code-block:: python

    >>> # Read coils, starting from coil 100 for the length of 3 coils.
    >>> adu = b'\\x01\\x01\\x00d\\x00\\x03=\\xd4'

The lenght of this ADU is 8 bytes::

    >>> len(adu)
    8

"""
import struct

from .redundancy_check import get_crc, validate_crc
from ...functions import (FUNCTION_CODE, create_function_from_response_pdu,
                               expected_response_pdu_size_from_request_pdu,
                               pdu_to_function_code_or_raise_error, ReadCoils,
                               ReadDiscreteInputs, ReadHoldingRegisters,
                               ReadInputRegisters, WriteSingleCoil,
                               WriteSingleRegister, WriteMultipleCoils,
                               WriteMultipleRegisters)
from ...utils import recv_exactly


def _create_request_adu(slave_id, req_pdu):
    """ Return request ADU for Modbus RTU.

    :param slave_id: Slave id.
    :param req_pdu: Byte array with PDU.
    :return: Byte array with ADU.
    """
    first_part_adu = struct.pack('>B', slave_id) + req_pdu

    return first_part_adu + get_crc(first_part_adu)


def read_coils(slave_id, starting_address, quantity):
    """ Return ADU for Modbus function code 01: Read Coils.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = ReadCoils()
    function.starting_address = starting_address
    function.quantity = quantity

    return _create_request_adu(slave_id, function.request_pdu)


def read_discrete_inputs(slave_id, starting_address, quantity):
    """ Return ADU for Modbus function code 02: Read Discrete Inputs.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = ReadDiscreteInputs()
    function.starting_address = starting_address
    function.quantity = quantity

    return _create_request_adu(slave_id, function.request_pdu)


def read_holding_registers(slave_id, starting_address, quantity):
    """ Return ADU for Modbus function code 03: Read Holding Registers.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = ReadHoldingRegisters()
    function.starting_address = starting_address
    function.quantity = quantity

    return _create_request_adu(slave_id, function.request_pdu)


def read_input_registers(slave_id, starting_address, quantity):
    """ Return ADU for Modbus function code 04: Read Input Registers.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = ReadInputRegisters()
    function.starting_address = starting_address
    function.quantity = quantity

    return _create_request_adu(slave_id, function.request_pdu)


def write_single_coil(slave_id, address, value):
    """ Return ADU for Modbus function code 05: Write Single Coil.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = WriteSingleCoil()
    function.address = address
    function.value = value

    return _create_request_adu(slave_id, function.request_pdu)


def write_single_register(slave_id, address, value):
    """ Return ADU for Modbus function code 06: Write Single Register.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = WriteSingleRegister()
    function.address = address
    function.value = value

    return _create_request_adu(slave_id, function.request_pdu)


def write_multiple_coils(slave_id, starting_address, values):
    """ Return ADU for Modbus function code 15: Write Multiple Coils.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = WriteMultipleCoils()
    function.starting_address = starting_address
    function.values = values

    return _create_request_adu(slave_id, function.request_pdu)


def write_multiple_registers(slave_id, starting_address, values):
    """ Return ADU for Modbus function code 16: Write Multiple Registers.

    :param slave_id: Number of slave.
    :return: Byte array with ADU.
    """
    function = WriteMultipleRegisters()
    function.starting_address = starting_address
    function.values = values

    return _create_request_adu(slave_id, function.request_pdu)


def parse_response_adu(resp_adu, req_adu=None):
    """ Parse response ADU and return response data. Some functions require
    request ADU to fully understand request ADU.

    :param resp_adu: Resonse ADU.
    :param req_adu: Request ADU, default None.
    :return: Response data.
    """
    resp_pdu = resp_adu[1:-2]
    validate_crc(resp_adu)

    req_pdu = None

    if req_adu is not None:
        req_pdu = req_adu[1:-2]

    function = create_function_from_response_pdu(resp_pdu, req_pdu)

    return function.data


def raise_for_exception_adu(resp_adu):
    """ Check a response ADU for error

    :param resp_adu: Response ADU.
    :raises ModbusError: When a response contains an error code.
    """
    resp_pdu = resp_adu[1:-2]
    pdu_to_function_code_or_raise_error(resp_pdu)


def send_message(adu, serial_port):
    """ Send ADU over serial to to server and return parsed response.

    :param adu: Request ADU.
    :param sock: Serial port instance.
    :return: Parsed response from server.
    """
    serial_port.write(adu)
    serial_port.flush()

    # Check exception ADU (which is shorter than all other responses) first.
    exception_adu_size = 5
    response_error_adu = recv_exactly(serial_port.read, exception_adu_size)
    raise_for_exception_adu(response_error_adu)

    expected_response_size = \
        expected_response_pdu_size_from_request_pdu(adu[1:-2]) + 3
    response_remainder = recv_exactly(
        serial_port.read, expected_response_size - exception_adu_size)

    return parse_response_adu(response_error_adu + response_remainder, adu)


function_code_to_function_map = {
    FUNCTION_CODE.READ_COILS: lambda slave_id, address, count, **_: read_coils(slave_id, address, count),
    FUNCTION_CODE.READ_DISCRETE_INPUTS: lambda slave_id, address, count, **_: read_discrete_inputs(slave_id, address, count),
    FUNCTION_CODE.READ_HOLDING_REGISTERS: lambda slave_id, address, count, **_: read_holding_registers(slave_id, address, count),
    FUNCTION_CODE.READ_INPUT_REGISTERS: lambda slave_id, address, count, **_: read_input_registers(slave_id, address, count),
    FUNCTION_CODE.WRITE_SINGLE_COIL: lambda slave_id, address, data, **_: write_single_coil(slave_id, address, data),
    FUNCTION_CODE.WRITE_SINGLE_REGISTER: lambda slave_id, address, data, **_: write_single_register(slave_id, address, data),
    FUNCTION_CODE.WRITE_MULTIPLE_COILS: lambda slave_id, address, data, **_: write_multiple_coils(slave_id, address, data),
    FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS: lambda slave_id, address, data, **_: write_multiple_registers(slave_id, address, data)
}
