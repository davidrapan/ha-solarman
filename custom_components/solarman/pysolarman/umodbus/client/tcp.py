"""

.. note:: This section is based on `MODBUS Messaging on TCP/IP
    Implementation Guide V1.0b`_.

The Application Data Unit (ADU) for Modbus messages carried over a TCP/IP are
build out of two components: a MBAP header and a PDU. The Modbus Application
Header (MBAP) is what makes Modbus TCP/IP requests and responses different from
their counterparts send over a serial line.  Below the components of the Modbus
TCP/IP are listed together with their size in bytes:

+---------------+-----------------+
| **Component** | **Size** (bytes)|
+---------------+-----------------+
| MBAP Header   | 7               |
+---------------+-----------------+
| PDU           | N               |
+---------------+-----------------+

Below you see a hexadecimal presentation of request over TCP/IP with Modbus
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
    >>> adu = b'\\x00\\x08\\x00\\x00\\x00\\x06\\x01\\x01\\x00d\\x00\\x03'

The length of the ADU is 12 bytes::

    >>> len(adu)
    12

The MBAP header is 7 bytes long::

    >>> mbap = adu[:7]
    >>> mbap
    b'\\x00\\x08\\x00\\x00\\x00\\x06\\x01'

The MBAP header contains the following fields:

+------------------------+--------------------+--------------------------------------+
| **Field**              | **Length** (bytes) | **Description**                      |
+------------------------+--------------------+--------------------------------------+
| Transaction identifier | 2                  | Identification of a                  |
|                        |                    | Modbus request/response transaction. |
+------------------------+--------------------+--------------------------------------+
| Protocol identifier    | 2                  | Protocol ID, is 0 for Modbus.        |
+------------------------+--------------------+--------------------------------------+
| Length                 | 2                  | Number of following bytes            |
+------------------------+--------------------+--------------------------------------+
| Unit identifier        | 1                  | Identification of a                  |
|                        |                    | remote slave                         |
+------------------------+--------------------+--------------------------------------+

When unpacked, these fields have the following values::

    >>> transaction_id = mbap[:2]
    >>> transaction_id
    b'\\x00\\x08'
    >>> protocol_id = mbap[2:4]
    >>> protocol_id
    b'\\x00\\x00'
    >>> length = mbap[4:6]
    >>> length
    b'\\x00\\x06'
    >>> unit_id = mbap[6:]
    >>> unit_id
    b'\\0x01'

The request in words: a request with Transaction ID 8 for slave 1. The
request uses Protocol ID 0, which is the Modbus protocol. The length of the
bytes after the Length field is 6 bytes. These 6 bytes are Unit Identifier (1
byte) + PDU (5 bytes).

"""
import struct
from random import randint

from ..functions import (FUNCTION_CODE, create_function_from_response_pdu,
                               expected_response_pdu_size_from_request_pdu,
                               pdu_to_function_code_or_raise_error, ReadCoils,
                               ReadDiscreteInputs, ReadHoldingRegisters,
                               ReadInputRegisters, WriteSingleCoil,
                               WriteSingleRegister, WriteMultipleCoils,
                               WriteMultipleRegisters)
from ..utils import recv_exactly


def _create_request_adu(slave_id, pdu):
    """ Create MBAP header and combine it with PDU to return ADU.

    :param slave_id: Number of slave.
    :param pdu: Byte array with PDU.
    :return: Byte array with ADU.
    """
    return _create_mbap_header(slave_id, pdu) + pdu


def _create_mbap_header(slave_id, pdu):
    """ Return byte array with MBAP header for PDU.

    :param slave_id: Number of slave.
    :param pdu: Byte array with PDU.
    :return: Byte array of 7 bytes with MBAP header.
    """
    # 65535 = (2**16)-1 aka maximum number that fits in 2 bytes.
    transaction_id = randint(0, 65535)
    length = len(pdu) + 1

    return struct.pack('>HHHB', transaction_id, 0, length, slave_id)


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
    resp_pdu = resp_adu[7:]
    function = create_function_from_response_pdu(resp_pdu, req_adu)

    return function.data


def raise_for_exception_adu(resp_adu):
    """ Check a response ADU for error

    :param resp_adu: Response ADU.
    :raises ModbusError: When a response contains an error code.
    """
    resp_pdu = resp_adu[7:]
    pdu_to_function_code_or_raise_error(resp_pdu)


def send_message(adu, sock):
    """ Send ADU over socket to to server and return parsed response.

    :param adu: Request ADU.
    :param sock: Socket instance.
    :return: Parsed response from server.
    """
    sock.sendall(adu)

    # Check exception ADU (which is shorter than all other responses) first.
    exception_adu_size = 9
    response_error_adu = recv_exactly(sock.recv, exception_adu_size)
    raise_for_exception_adu(response_error_adu)

    expected_response_size = \
        expected_response_pdu_size_from_request_pdu(adu[7:]) + 7
    response_remainder = recv_exactly(
        sock.recv, expected_response_size - exception_adu_size)

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
