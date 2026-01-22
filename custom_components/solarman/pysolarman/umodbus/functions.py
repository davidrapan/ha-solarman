"""
.. note:: This section is based on `MODBUS Application Protocol Specification
    V1.1b3`_

The Protocol Data Unit (PDU) is the request or response message and is
indepedent of the underlying communication layer. This module only implements
requests PDU's.

A request PDU contains two parts: a function code and request data. A response
PDU contains the function code from the request and response data. The general
structure is listed in table below:

+---------------+-----------------+
| **Field**     | **Size** (bytes)|
+---------------+-----------------+
| Function code | 1               |
+---------------+-----------------+
| data          | N               |
+---------------+-----------------+

Below you see the request PDU with function code 1, requesting status of 3
coils, starting from coil 100.

..
    Note: the backslash in the bytes below are escaped using an extra back
    slash. Without escaping the bytes aren't printed correctly in the HTML
    output of this docs.

    To work with the bytes in Python you need to remove the escape sequences.
    `b'\\x01\\x00d` -> `b\x01\x00d`

.. code-block:: python

    >>> req_pdu = b'\\x01\x00d\\x00\\x03'
    >>> function_code = req_pdu[:1]
    >>> function_code
    b'\\x01'
    >>> starting_address = req_pdu[1:3]
    >>> starting_address
    b'\\x00d'
    >>> quantity = req_pdu[3:]
    >>> quantity
    b'\\x00\\x03'

A response PDU could look like this::

    >>> resp_pdu = b'\\x01\\x01\\x06'
    >>> function_code = resp_pdu[:1]
    >>> function_code
    b'\\x01'
    >>> byte_count = resp[1:2]
    >>> byte_count
    b'\\x01'
    >>> coil_status = resp[2:]
    'b\\x06'

"""
from __future__ import division
import struct
import types
import math

try:
    from inspect import getfullargspec
except ImportError:
    # inspect.getfullargspec was introduced in Python 3.4.
    # Earlier versions have inspect.getargspec.
    from inspect import getargspec as getfullargspec

try:
    from functools import reduce
except ImportError:
    pass

from . import conf, log
from .exceptions import (error_code_to_exception_map,
                                IllegalDataValueError, IllegalFunctionError,
                                IllegalDataAddressError)
from .utils import memoize, get_function_code_from_request_pdu

# Function related to data access.
READ_COILS = 1
READ_DISCRETE_INPUTS = 2
READ_HOLDING_REGISTERS = 3
READ_INPUT_REGISTERS = 4

WRITE_SINGLE_COIL = 5
WRITE_SINGLE_REGISTER = 6
WRITE_MULTIPLE_COILS = 15
WRITE_MULTIPLE_REGISTERS = 16

READ_FILE_RECORD = 20

WRITE_FILE_RECORD = 21

READ_WRITE_MULTIPLE_REGISTERS = 23
READ_FIFO_QUEUE = 24

# Diagnostic functions, only available when using serial line.
READ_EXCEPTION_STATUS = 7
DIAGNOSTICS = 8
GET_COMM_EVENT_COUNTER = 11
GET_COM_EVENT_LOG = 12
REPORT_SERVER_ID = 17

FUNCTION_CODE = types.SimpleNamespace()
FUNCTION_CODE.READ_COILS = READ_COILS
FUNCTION_CODE.READ_DISCRETE_INPUTS = READ_DISCRETE_INPUTS
FUNCTION_CODE.READ_HOLDING_REGISTERS = READ_HOLDING_REGISTERS
FUNCTION_CODE.READ_INPUT_REGISTERS = READ_INPUT_REGISTERS
FUNCTION_CODE.WRITE_SINGLE_COIL = WRITE_SINGLE_COIL
FUNCTION_CODE.WRITE_SINGLE_REGISTER = WRITE_SINGLE_REGISTER
FUNCTION_CODE.WRITE_MULTIPLE_COILS = WRITE_MULTIPLE_COILS
FUNCTION_CODE.WRITE_MULTIPLE_REGISTERS = WRITE_MULTIPLE_REGISTERS

FUNCTION_CODES = FUNCTION_CODE.__dict__.values()


def pdu_to_function_code_or_raise_error(resp_pdu):
    """ Parse response PDU and return of :class:`ModbusFunction` or
    raise error.

    :param resp_pdu: PDU of response.
    :return: Subclass of :class:`ModbusFunction` matching the response.
    :raises ModbusError: When response contains error code.
    """
    function_code = struct.unpack('>B', resp_pdu[0:1])[0]

    if function_code not in function_code_to_function_map.keys():
        error_code = struct.unpack('>B', resp_pdu[1:2])[0]
        raise error_code_to_exception_map[error_code]

    return function_code


def create_function_from_response_pdu(resp_pdu, req_pdu=None):
    """ Parse response PDU and return instance of :class:`ModbusFunction` or
    raise error.

    :param resp_pdu: PDU of response.
    :param  req_pdu: Request PDU, some functions require more info than in
        response PDU in order to create instance. Default is None.
    :return: Number or list with response data.
    """
    function_code = pdu_to_function_code_or_raise_error(resp_pdu)
    function = function_code_to_function_map[function_code]

    if req_pdu is not None and \
        'req_pdu' in getfullargspec(function.create_from_response_pdu).args:  # NOQA

        return function.create_from_response_pdu(resp_pdu, req_pdu)

    return function.create_from_response_pdu(resp_pdu)


@memoize
def create_function_from_request_pdu(pdu):
    """ Return function instance, based on request PDU.

    :param pdu: Array of bytes.
    :return: Instance of a function.
    """
    function_code = get_function_code_from_request_pdu(pdu)
    try:
        function_class = function_code_to_function_map[function_code]
    except KeyError:
        raise IllegalFunctionError(function_code)

    return function_class.create_from_request_pdu(pdu)


def expected_response_pdu_size_from_request_pdu(pdu):
    """ Return number of bytes expected for response PDU, based on request PDU.

    :param pdu: Array of bytes.
    :return: number of bytes.
    """
    return create_function_from_request_pdu(pdu).expected_response_pdu_size


class ModbusFunction(object):
    function_code = None


class ReadCoils(ModbusFunction):
    """ Implement Modbus function code 01.

        "This function code is used to read from 1 to 2000 contiguous status of
        coils in a remote device. The Request PDU specifies the starting
        address, i.e. the address of the first coil specified, and the number
        of coils. In the PDU Coils are addressed starting at zero. Therefore
        coils numbered 1-16 are addressed as 0-15.

        The coils in the response message are packed as one coil per bit of the
        data field. Status is indicated as 1= ON and 0= OFF. The LSB of the
        first data byte contains the output addressed in the query. The other
        coils follow toward the high order end of this byte, and from low order
        to high order in subsequent bytes.

        If the returned output quantity is not a multiple of eight, the
        remaining bits in the final data byte will be padded with zeros (toward
        the high order end of the byte). The Byte Count field specifies the
        quantity of complete bytes of data."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.1

    The request PDU with function code 01 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x01\\x00d\\x00\\x03')
        (1, 100, 3)

    The reponse PDU varies in length, depending on the request. Each 8 coils
    require 1 byte. The amount of bytes needed represent status of the coils to
    can be calculated with: bytes = ceil(quantity / 8). This response
    contains ceil(3 / 8) = 1 byte to describe the status of the coils. The
    structure of a compleet response PDU looks like this:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Byte count       1
        Coil status      n
        ================ ===============

    Assume the status of 102 is 0, 101 is 1 and 100 is also 1. This is binary
    011 which is decimal 3.

    The PDU can packed like this::

        >>> struct.pack('>BBB', function_code, byte_count, 3)
        b'\\x01\\x01\\x03'

    """
    function_code = READ_COILS
    max_quantity = 2000
    format_character = 'B'

    data = None
    starting_address = None
    _quantity = None

    @property
    def quantity(self):
        return self._quantity

    @quantity.setter
    def quantity(self, value):
        """ Set number of coils to read. Quantity must be between 1 and 2000.

        :param value: Quantity.
        :raises: IllegalDataValueError.
        """
        if not (1 <= value <= 2000):
            raise IllegalDataValueError('Quantify field of request must be a '
                                        'value between 0 and '
                                        '{0}.'.format(2000))

        self._quantity = value

    @property
    def request_pdu(self):
        """ Build request PDU to read coils.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.starting_address, self.quantity]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BHH', self.function_code, self.starting_address,
                           self.quantity)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, starting_address, quantity = struct.unpack('>BHH', pdu)

        instance = cls()
        instance.starting_address = starting_address
        instance.quantity = quantity

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 2 + int(math.ceil(self.quantity / 8))

    def create_response_pdu(self, data):
        """ Create response pdu.

        :param data: A list with 0's and/or 1's.
        :return: Byte array of at least 3 bytes.
        """
        log.debug('Create single bit response pdu {0}.'.format(data))
        bytes_ = [data[i:i + 8] for i in range(0, len(data), 8)]

        # Reduce each all bits per byte to a number. Byte
        # [0, 0, 0, 0, 0, 1, 1, 1] is intepreted as binary en is decimal 3.
        for index, byte in enumerate(bytes_):
            bytes_[index] = \
                reduce(lambda a, b: (a << 1) + b, list(reversed(byte)))

        log.debug('Reduced single bit data to {0}.'.format(bytes_))
        # The first 2 B's of the format encode the function code (1 byte) and
        # the length (1 byte) of the following byte series. Followed by # a B
        # for every byte in the series of bytes. 3 lead to the format '>BBB'
        # and 257 lead to the format '>BBBB'.
        fmt = '>BB' + self.format_character * len(bytes_)
        return struct.pack(fmt, self.function_code, len(bytes_), *bytes_)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu, req_pdu):
        """ Create instance from response PDU.

        Response PDU is required together with the quantity of coils read.

        :param resp_pdu: Byte array with request PDU.
        :param quantity: Number of coils read.
        :return: Instance of :class:`ReadCoils`.
        """
        instance = cls()
        instance.quantity = struct.unpack('>H', req_pdu[-2:])[0]
        instance.byte_count = struct.unpack('>B', resp_pdu[1:2])[0]

        fmt = '>' + ('B' * instance.byte_count)
        data = list()

        for i, value in enumerate(struct.unpack(fmt, resp_pdu[2:2 + instance.byte_count])):
            padding = 8 if (instance.quantity - (8 * i)) // 8 > 0 \
                else instance.quantity % 8

            fmt = '{{0:0{padding}b}}'.format(padding=padding)

            # Create binary representation of integer, convert it to a list
            # and reverse the list.
            data = data + [int(i) for i in fmt.format(value)][::-1]

        instance.data = data

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        :return: Result of call to endpoint.
        """
        values = []

        for address in range(self.starting_address,
                             self.starting_address + self.quantity):
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            values.append(endpoint(slave_id=slave_id, address=address,
                                   function_code=self.function_code))

        return values


class ReadDiscreteInputs(ModbusFunction):
    """ Implement Modbus function code 02.

        "This function code is used to read from 1 to 2000 contiguous status of
        discrete inputs in a remote device. The Request PDU specifies the
        starting address, i.e. the address of the first input specified, and
        the number of inputs. In the PDU Discrete Inputs are addressed starting
        at zero. Therefore Discrete inputs numbered 1-16 are addressed as
        0-15.

        The discrete inputs in the response message are packed as one input per
        bit of the data field.  Status is indicated as 1= ON; 0= OFF. The LSB
        of the first data byte contains the input addressed in the query. The
        other inputs follow toward the high order end of this byte, and from
        low order to high order in subsequent bytes.

        If the returned input quantity is not a multiple of eight, the
        remaining bits in the final d ata byte will be padded with zeros
        (toward the high order end of the byte). The Byte Count field specifies
        the quantity of complete bytes of data."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.2

    The request PDU with function code 02 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x02\\x00d\\x00\\x03')
        (2, 100, 3)

    The reponse PDU varies in length, depending on the request. 8 inputs
    require 1 byte. The amount of bytes needed represent status of the inputs
    to can be calculated with: bytes = ceil(quantity / 8). This response
    contains ceil(3 / 8) = 1 byte to describe the status of the inputs. The
    structure of a compleet response PDU looks like this:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Byte count       1
        Coil status      n
        ================ ===============

    Assume the status of 102 is 0, 101 is 1 and 100 is also 1. This is binary
    011 which is decimal 3.

    The PDU can packed like this::

        >>> struct.pack('>BBB', function_code, byte_count, 3)
        b'\\x02\\x01\\x03'

    """
    function_code = READ_DISCRETE_INPUTS
    max_quantity = 2000
    format_character = 'B'

    data = None
    starting_address = None
    _quantity = None

    @property
    def quantity(self):
        return self._quantity

    @quantity.setter
    def quantity(self, value):
        """ Set number of inputs to read. Quantity must be between 1 and 2000.

        :param value: Quantity.
        :raises: IllegalDataValueError.
        """
        if not (1 <= value <= 2000):
            raise IllegalDataValueError('Quantify field of request must be a '
                                        'value between 0 and '
                                        '{0}.'.format(2000))

        self._quantity = value

    @property
    def request_pdu(self):
        """ Build request PDU to read discrete inputs.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.starting_address, self.quantity]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BHH', self.function_code, self.starting_address,
                           self.quantity)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, starting_address, quantity = struct.unpack('>BHH', pdu)

        instance = cls()
        instance.starting_address = starting_address
        instance.quantity = quantity

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 2 + int(math.ceil(self.quantity / 8))

    def create_response_pdu(self, data):
        """ Create response pdu.

        :param data: A list with 0's and/or 1's.
        :return: Byte array of at least 3 bytes.
        """
        log.debug('Create single bit response pdu {0}.'.format(data))
        bytes_ = [data[i:i + 8] for i in range(0, len(data), 8)]

        # Reduce each all bits per byte to a number. Byte
        # [0, 0, 0, 0, 0, 1, 1, 1] is intepreted as binary en is decimal 3.
        for index, byte in enumerate(bytes_):
            bytes_[index] = \
                reduce(lambda a, b: (a << 1) + b, list(reversed(byte)))

        log.debug('Reduced single bit data to {0}.'.format(bytes_))
        # The first 2 B's of the format encode the function code (1 byte) and
        # the length (1 byte) of the following byte series. Followed by # a B
        # for every byte in the series of bytes. 3 lead to the format '>BBB'
        # and 257 lead to the format '>BBBB'.
        fmt = '>BB' + self.format_character * len(bytes_)
        return struct.pack(fmt, self.function_code, len(bytes_), *bytes_)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu, req_pdu):
        """ Create instance from response PDU.

        Response PDU is required together with the quantity of inputs read.

        :param resp_pdu: Byte array with request PDU.
        :param quantity: Number of inputs read.
        :return: Instance of :class:`ReadDiscreteInputs`.
        """
        instance = cls()
        instance.quantity = struct.unpack('>H', req_pdu[-2:])[0]
        instance.byte_count = struct.unpack('>B', resp_pdu[1:2])[0]

        fmt = '>' + ('B' * instance.byte_count)
        data = list()

        for i, value in enumerate(struct.unpack(fmt, resp_pdu[2:2 + instance.byte_count])):
            padding = 8 if (instance.quantity - (8 * i)) // 8 > 0 \
                else instance.quantity % 8

            fmt = '{{0:0{padding}b}}'.format(padding=padding)

            # Create binary representation of integer, convert it to a list
            # and reverse the list.
            data = data + [int(i) for i in fmt.format(value)][::-1]

        instance.data = data

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        :return: Result of call to endpoint.
        """
        values = []

        for address in range(self.starting_address,
                             self.starting_address + self.quantity):
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            values.append(endpoint(slave_id=slave_id, address=address,
                                   function_code=self.function_code))

        return values


class ReadHoldingRegisters(ModbusFunction):
    """ Implement Modbus function code 03.

        "This function code is used to read the contents of a contiguous block
        of holding registers in a remote device. The Request PDU specifies the
        starting register address and the number of registers. In the PDU
        Registers are addressed starting at zero. Therefore registers numbered
        1-16 are addressed as 0-15.

        The register data in the response message are packed as two bytes per
        register, with the binary contents right justified within each byte.
        For each register, the first byte contains the high order bits and the
        second contains the low order bits."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.3

    The request PDU with function code 03 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x03\\x00d\\x00\\x03')
        (3, 100, 3)

    The reponse PDU varies in length, depending on the request. By default,
    holding registers are 16 bit (2 bytes) values. So values of 3 holding
    registers is expressed in 2 * 3 = 6 bytes.

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Byte count       1
        Register values  Quantity * 2
        ================ ===============

    Assume the value of 100 is 8, 101 is 0 and 102 is also 15.

    The PDU can packed like this::

        >>> data = [8, 0, 15]
        >>> struct.pack('>BBHHH', function_code, len(data) * 2, *data)
        b'\\x03\\x06\\x00\\x08\\x00\\x00\\x00\\x0f'

    """
    function_code = READ_HOLDING_REGISTERS
    max_quantity = 0x007D

    data = None
    starting_address = None
    _quantity = None

    @property
    def quantity(self):
        return self._quantity

    @quantity.setter
    def quantity(self, value):
        """ Set number of registers to read. Quantity must be between 1 and
        0x00FD.

        :param value: Quantity.
        :raises: IllegalDataValueError.
        """
        if not (1 <= value <= 0x007D):
            raise IllegalDataValueError('Quantify field of request must be a '
                                        'value between 0 and '
                                        '{0}.'.format(0x007D))

        self._quantity = value

    @property
    def request_pdu(self):
        """ Build request PDU to read coils.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.starting_address, self.quantity]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BHH', self.function_code, self.starting_address,
                           self.quantity)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, starting_address, quantity = struct.unpack('>BHH', pdu)

        instance = cls()
        instance.starting_address = starting_address
        instance.quantity = quantity

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 2 + self.quantity * 2

    def create_response_pdu(self, data):
        """ Create response pdu.

        :param data: A list with values.
        :return: Byte array of at least 4 bytes.
        """
        log.debug('Create multi bit response pdu {0}.'.format(data))
        fmt = '>BB' + conf.TYPE_CHAR * len(data)

        return struct.pack(fmt, self.function_code, len(data) * 2, *data)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu, req_pdu):
        """ Create instance from response PDU.

        Response PDU is required together with the number of registers read.

        :param resp_pdu: Byte array with request PDU.
        :param quantity: Number of coils read.
        :return: Instance of :class:`ReadCoils`.
        """
        instance = cls()
        instance.quantity = struct.unpack('>H', req_pdu[-2:])[0]
        instance.byte_count = struct.unpack('>B', resp_pdu[1:2])[0]
        instance.data = list(
            struct.unpack(
                '>' + (conf.TYPE_CHAR * instance.quantity),
                resp_pdu[2:2 + instance.byte_count]
            )
        )

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        :return: Result of call to endpoint.
        """
        values = []

        for address in range(self.starting_address,
                             self.starting_address + self.quantity):
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            values.append(endpoint(slave_id=slave_id, address=address,
                                   function_code=self.function_code))

        return values


class ReadInputRegisters(ModbusFunction):
    """ Implement Modbus function code 04.

        "This function code is used to read from 1 to 125 contiguous input
        registers in a remote device. The Request PDU specifies the starting
        register address and the number of registers. In the PDU Registers are
        addressed starting at zero. Therefore input registers numbered 1-16 are
        addressed as 0-15.

        The register data in the response message are packed as two bytes per
        register, with the binary contents right justified within each byte.
        For each register, the first byte contains the high order bits and the
        second contains the low order bits."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.4

    The request PDU with function code 04 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x04\\x00d\\x00\\x03')
        (4, 100, 3)

    The reponse PDU varies in length, depending on the request. By default,
    holding registers are 16 bit (2 bytes) values. So values of 3 holding
    registers is expressed in 2 * 3 = 6 bytes.

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Byte count       1
        Register values  Quantity * 2
        ================ ===============

    Assume the value of 100 is 8, 101 is 0 and 102 is also 15.

    The PDU can packed like this::

        >>> data = [8, 0, 15]
        >>> struct.pack('>BBHHH', function_code, len(data) * 2, *data)
        b'\\x04\\x06\\x00\\x08\\x00\\x00\\x00\\x0f'

    """
    function_code = READ_INPUT_REGISTERS
    max_quantity = 0x007D

    data = None
    starting_address = None
    _quantity = None

    @property
    def quantity(self):
        return self._quantity

    @quantity.setter
    def quantity(self, value):
        """ Set number of registers to read. Quantity must be between 1 and
        0x00FD.

        :param value: Quantity.
        :raises: IllegalDataValueError.
        """
        if not (1 <= value <= 0x007D):
            raise IllegalDataValueError('Quantify field of request must be a '
                                        'value between 0 and '
                                        '{0}.'.format(0x007D))

        self._quantity = value

    @property
    def request_pdu(self):
        """ Build request PDU to read coils.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.starting_address, self.quantity]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BHH', self.function_code, self.starting_address,
                           self.quantity)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, starting_address, quantity = struct.unpack('>BHH', pdu)

        instance = cls()
        instance.starting_address = starting_address
        instance.quantity = quantity

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 2 + self.quantity * 2

    def create_response_pdu(self, data):
        """ Create response pdu.

        :param data: A list with values.
        :return: Byte array of at least 4 bytes.
        """
        log.debug('Create multi bit response pdu {0}.'.format(data))
        fmt = '>BB' + conf.TYPE_CHAR * len(data)

        return struct.pack(fmt, self.function_code, len(data) * 2, *data)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu, req_pdu):
        """ Create instance from response PDU.

        Response PDU is required together with the number of registers read.

        :param resp_pdu: Byte array with request PDU.
        :param quantity: Number of coils read.
        :return: Instance of :class:`ReadCoils`.
        """
        instance = cls()
        instance.quantity = struct.unpack('>H', req_pdu[-2:])[0]
        instance.byte_count = struct.unpack('>B', resp_pdu[1:2])[0]
        instance.data = list(
            struct.unpack(
                '>' + (conf.TYPE_CHAR * instance.quantity),
                resp_pdu[2:2 + instance.byte_count]
            )
        )

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        :return: Result of call to endpoint.
        """
        values = []

        for address in range(self.starting_address,
                             self.starting_address + self.quantity):
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            values.append(endpoint(slave_id=slave_id, address=address,
                                   function_code=self.function_code))

        return values


class WriteSingleCoil(ModbusFunction):
    """ Implement Modbus function code 05.

        "This function code is used to write a single output to either ON or
        OFF in a remote device. The requested ON/OFF state is specified by a
        constant in the request data field. A value of FF 00 hex requests the
        output to be ON.  A value of 00 00 requests it to be OFF. All other
        values are illegal and will not affect the output.

        The Request PDU specifies the address of the coil to be forced. Coils
        are addressed starting at zero. Therefore coil numbered 1 is addressed
        as 0.  The requested ON/OFF state is specified by a constant in the
        Coil Value field. A value of 0XFF00 requests the coil to be ON. A value
        of 0X0000 requests the coil to be off. All other values are illegal and
        will not affect the coil.

        The normal response is an echo of the request, returned after the coil
        state has been written."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.5

    The request PDU with function code 05 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Address          2
        Value            2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x05\\x00d\\xFF\\x00')
        (5, 100, 65280)

    The reponse PDU is a copy of the request PDU.

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Address          2
        Value            2
        ================ ===============

    """
    function_code = WRITE_SINGLE_COIL
    format_character = 'B'

    address = None
    data = None
    _value = None

    @property
    def value(self):
        if self._value == 0xFF00:
            return 1

        return self._value

    @value.setter
    def value(self, value):
        if value not in [0, 1, 0xFF00]:
            raise IllegalDataValueError

        value = 0xFF00 if value == 1 else value
        self._value = value

    @property
    def request_pdu(self):
        """ Build request PDU to write single coil.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.address, self.value]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BHH', self.function_code, self.address,
                           self._value)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A response PDU.
        :return: Instance of this class.
        """
        _, address, value = struct.unpack('>BHH', pdu)

        value = 1 if value == 0xFF00 else value

        instance = cls()
        instance.address = address
        instance.value = value

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 5

    def create_response_pdu(self):
        """ Create response pdu.

        :param data: A list with values.
        :return: Byte array of at least 4 bytes.
        """
        fmt = '>BHH'
        return struct.pack(fmt, self.function_code, self.address, self._value)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu):
        """ Create instance from response PDU.

        :param resp_pdu: Byte array with request PDU.
        :return: Instance of :class:`WriteSingleCoil`.
        """
        instance = cls()

        address, value = struct.unpack('>HH', resp_pdu[1:5])
        value = 1 if value == 0xFF00 else value

        instance.address = address
        instance.data = value

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        """
        endpoint = route_map.match(slave_id, self.function_code, self.address)
        if endpoint is None:
            raise IllegalDataAddressError()
        endpoint(slave_id=slave_id, address=self.address, value=self.value,
                 function_code=self.function_code)


class WriteSingleRegister(ModbusFunction):
    """ Implement Modbus function code 06.

        "This function code is used to write a single holding register in a
        remote device. The Request PDU specifies the address of the register to
        be written. Registers are addressed starting at zero. Therefore
        register numbered 1 is addressed as 0. The normal response is an echo
        of the request, returned after the register contents have been
        written."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.6

    The request PDU with function code 06 must be 5 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Address          2
        Value            2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHH', b'\\x06\\x00d\\x00\\x03')
        (6, 100, 3)

    The reponse PDU is a copy of the request PDU.

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Address          2
        Value            2
        ================ ===============

    """
    function_code = WRITE_SINGLE_REGISTER

    address = None
    data = None
    _value = None

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        """ Value to be written on register.

        :param value: An integer.
        :raises: IllegalDataValueError when value isn't in range.
        """
        try:
            struct.pack('>' + conf.TYPE_CHAR, value)
        except struct.error:
            raise IllegalDataValueError

        self._value = value

    @property
    def request_pdu(self):
        """ Build request PDU to write single register.

        :return: Byte array of 5 bytes with PDU.
        """
        if None in [self.address, self.value]:
            # TODO Raise proper exception.
            raise Exception

        return struct.pack('>BH' + conf.TYPE_CHAR, self.function_code,
                           self.address, self.value)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, address, value = \
            struct.unpack('>BH' + conf.MULTI_BIT_VALUE_FORMAT_CHARACTER, pdu)

        instance = cls()
        instance.address = address
        instance.value = value

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 5

    def create_response_pdu(self):
        fmt = '>BH' + conf.TYPE_CHAR
        return struct.pack(fmt, self.function_code, self.address, self.value)

    @classmethod
    def create_from_response_pdu(cls, resp_pdu):
        """ Create instance from response PDU.

        :param resp_pdu: Byte array with request PDU.
        :return: Instance of :class:`WriteSingleRegister`.
        """
        instance = cls()

        address, value = struct.unpack('>H' + conf.TYPE_CHAR, resp_pdu[1:5])

        instance.address = address
        instance.data = value

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        """
        endpoint = route_map.match(slave_id, self.function_code, self.address)
        if endpoint is None:
            raise IllegalDataAddressError()
        endpoint(slave_id=slave_id, address=self.address, value=self.value,
                 function_code=self.function_code)


class WriteMultipleCoils(ModbusFunction):
    """ Implement Modbus function 15 (0x0F) Write Multiple Coils.

        "This function code is used to force each coil in a sequence of coils
        to either ON or OFF in a remote device. The Request PDU specifies the
        coil references to be forced. Coils are addressed starting at zero.
        Therefore coil numbered 1 is addressed as 0.

        The requested ON/OFF states are specified by contents of the request
        data field. A logical '1' in a bit position of the field requests the
        corresponding output to be ON. A logical '0' requests it to be OFF.

        The normal response returns the function code, starting address, and
        quantity of coils forced."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.11

    The request PDU with function code 15 must be at least 7 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting Address 2
        Quantity         2
        Byte count       1
        Value            n
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHHBB', b'\\x0f\\x00d\\x00\\x03\\x01\\x05')
        (16, 100, 3, 1, 5)

    The reponse PDU is 5 bytes and contains following structure:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    """
    function_code = WRITE_MULTIPLE_COILS

    starting_address = None
    _values = None
    _data = None

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, values):
        if not (1 <= len(values) <= 0x7B0):
            raise IllegalDataValueError

        for value in values:
            if value not in [0, 1]:
                raise IllegalDataValueError

        self._values = values

    @property
    def request_pdu(self):
        if None in [self.starting_address, self._values]:
            raise IllegalDataValueError

        bytes_ = [self.values[i:i + 8] for i in range(0, len(self.values), 8)]

        # Reduce each all bits per byte to a number. Byte
        # [0, 0, 0, 0, 0, 1, 1, 1] is intepreted as binary en is decimal 3.
        for index, byte in enumerate(bytes_):
            bytes_[index] = \
                reduce(lambda a, b: (a << 1) + b, list(reversed(byte)))

        fmt = '>BHHB' + 'B' * len(bytes_)
        return struct.pack(fmt, self.function_code, self.starting_address,
                           len(self.values), (len(self.values) + 7) // 8,
                           *bytes_)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        This method requires some clarification regarding the unpacking of
        the status that are being passed to the callbacks.

        A coil status can be 0 or 1. The request PDU contains at least 1 byte,
        representing the status for 1 to 8 coils.

        Assume a request with starting address 100, quantity set to 3 and the
        value byte is 6. 0b110 is the binary reprensention of decimal 6. The
        Least Significant Bit (LSB) is status of coil with starting address. So
        status of coil 100 is 0, status of coil 101 is 1 and status of coil 102
        is 1 too.

        coil address  102     101     100
                        1       1       0

        Again, assume starting address 100 and  byte value is 6. But now
        quantity is 4. So the value byte is addressing 4 coils. The binary
        representation of 6 is now 0b0110. LSB again is 0, meaning status of
        coil 100 is 0. Status of 101 and 102 is 1, like in the previous
        example. Status of coil 104 is 0.

        coil address  104     102     101     100
                        0       1       1       0


        In short: the binary representation of the byte value is in reverse
        mapped to the coil addresses. In table below you can see some more
        examples.

        #  quantity value binary representation | 102 101 100
        == ======== ===== ===================== | === === ===
        01 1        0     0b0                      -   -   0
        02 1        1     0b1                      -   -   1
        03 2        0     0b00                     -   0   0
        04 2        1     0b01                     -   0   1
        05 2        2     0b10                     -   1   0
        06 2        3     0b11                     -   1   1
        07 3        0     0b000                    0   0   0
        08 3        1     0b001                    0   0   1
        09 3        2     0b010                    0   1   0
        10 3        3     0b011                    0   1   1
        11 3        4     0b100                    1   0   0
        12 3        5     0b101                    1   0   1
        13 3        6     0b110                    1   1   0
        14 3        7     0b111                    1   1   1

        :param pdu: A request PDU.
        """
        _, starting_address, quantity, byte_count = \
            struct.unpack('>BHHB', pdu[:6])

        fmt = '>' + (conf.SINGLE_BIT_VALUE_FORMAT_CHARACTER * byte_count)
        values = struct.unpack(fmt, pdu[6:])

        res = list()

        for i, value in enumerate(values):
            padding = 8 if (quantity - (8 * i)) // 8 > 0 else quantity % 8
            fmt = '{{0:0{padding}b}}'.format(padding=padding)

            # Create binary representation of integer, convert it to a list
            # and reverse the list.
            res = res + [int(i) for i in fmt.format(value)][::-1]

        instance = cls()
        instance.starting_address = starting_address
        instance.quantity = quantity

        instance.values = res

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 5

    def create_response_pdu(self):
        """ Create response pdu.

        :param data: A list with values.
        :return: Byte array 5 bytes.
        """
        return struct.pack('>BHH', self.function_code, self.starting_address,
                           len(self.values))

    @classmethod
    def create_from_response_pdu(cls, resp_pdu):
        """ Create instance from response PDU.

        :param resp_pdu: Byte array with request PDU.
        :return: Instance of :class:`WriteMultipleCoils`.
        """
        instance = cls()

        starting_address, data = struct.unpack('>HH', resp_pdu[1:5])

        instance.starting_address = starting_address
        instance.data = data

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        """
        for index, value in enumerate(self.values):
            address = self.starting_address + index
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            endpoint(slave_id=slave_id, address=address, value=value,
                     function_code=self.function_code)


class WriteMultipleRegisters(ModbusFunction):
    """ Implement Modbus function 16 (0x10) Write Multiple Registers.

        "This function code is used to write a block of contiguous registers (1
        to 123 registers) in a remote device.

        The requested written values are specified in the request data field.
        Data is packed as two bytes per register.

        The normal response returns the function code, starting address, and
        quantity of registers written."

        -- MODBUS Application Protocol Specification V1.1b3, chapter 6.12

    The request PDU with function code 16 must be at least 8 bytes:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting Address 2
        Quantity         2
        Byte count       1
        Value            Quantity * 2
        ================ ===============

    The PDU can unpacked to this:

    ..
        Note: the backslash in the bytes below are escaped using an extra back
        slash. Without escaping the bytes aren't printed correctly in the HTML
        output of this docs.

        To work with the bytes in Python you need to remove the escape sequences.
        `b'\\x01\\x00d` -> `b\x01\x00d`

    .. code-block:: python

        >>> struct.unpack('>BHHBH', b'\\x10\\x00d\\x00\\x01\\x02\\x00\\x05')
        (16, 100, 1, 2, 5)

    The reponse PDU is 5 bytes and contains following structure:

        ================ ===============
        Field            Length (bytes)
        ================ ===============
        Function code    1
        Starting address 2
        Quantity         2
        ================ ===============

    """
    function_code = WRITE_MULTIPLE_REGISTERS

    starting_address = None
    _values = None
    _data = None

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, values):
        if not (1 <= len(values) <= 0x7B0):
            raise IllegalDataValueError

        for value in values:
            try:
                struct.pack(">" + conf.MULTI_BIT_VALUE_FORMAT_CHARACTER, value)
            except struct.error:
                raise IllegalDataValueError

        self._values = values
        self._values = values

    @property
    def request_pdu(self):
        fmt = '>BHHB' + (conf.TYPE_CHAR * len(self.values))
        return struct.pack(fmt, self.function_code, self.starting_address,
                           len(self.values), len(self.values) * 2,
                           *self.values)

    @classmethod
    def create_from_request_pdu(cls, pdu):
        """ Create instance from request PDU.

        :param pdu: A request PDU.
        :return: Instance of this class.
        """
        _, starting_address, _, byte_count = \
            struct.unpack('>BHHB', pdu[:6])

        # Values are 16 bit, so each value takes up 2 bytes.
        fmt = '>' + (conf.MULTI_BIT_VALUE_FORMAT_CHARACTER *
                     int((byte_count / 2)))

        values = list(struct.unpack(fmt, pdu[6:]))

        instance = cls()
        instance.starting_address = starting_address
        instance.values = values

        return instance

    @property
    def expected_response_pdu_size(self):
        """ Return number of bytes expected for response PDU.

        :return: number of bytes.
        """
        return 5

    def create_response_pdu(self):
        """ Create response pdu.

        :param data: A list with values.
        :return: Byte array 5 bytes.
        """
        return struct.pack('>BHH', self.function_code, self.starting_address,
                           len(self.values))

    @classmethod
    def create_from_response_pdu(cls, resp_pdu):
        """ Create instance from response PDU.

        :param resp_pdu: Byte array with request PDU.
        :return: Instance of :class:`WriteMultipleRegisters`.
        """
        instance = cls()

        starting_address, data = struct.unpack('>HH', resp_pdu[1:5])

        instance.starting_address = starting_address
        instance.data = data

        return instance

    def execute(self, slave_id, route_map):
        """ Execute the Modbus function registered for a route.

        :param slave_id: Slave id.
        :param route_map: Instance of modbus.route.Map.
        """
        for index, value in enumerate(self.values):
            address = self.starting_address + index
            endpoint = route_map.match(slave_id, self.function_code, address)
            if endpoint is None:
                raise IllegalDataAddressError()
            endpoint(slave_id=slave_id, address=address, value=value,
                     function_code=self.function_code)


function_code_to_function_map = {
    READ_COILS: ReadCoils,
    READ_DISCRETE_INPUTS: ReadDiscreteInputs,
    READ_HOLDING_REGISTERS: ReadHoldingRegisters,
    READ_INPUT_REGISTERS: ReadInputRegisters,
    WRITE_SINGLE_COIL: WriteSingleCoil,
    WRITE_SINGLE_REGISTER: WriteSingleRegister,
    WRITE_MULTIPLE_COILS: WriteMultipleCoils,
    WRITE_MULTIPLE_REGISTERS: WriteMultipleRegisters,
}
