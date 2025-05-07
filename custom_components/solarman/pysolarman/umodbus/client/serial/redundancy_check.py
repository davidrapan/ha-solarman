""" CRC is calculated over slave id + PDU.

Most code is taken from: https://github.com/pyhys/minimalmodbus/blob/e99f4d74c83258c6039073082955ac9bed3f2155/minimalmodbus.py  # NOQA
"""
import struct


def generate_look_up_table():
    """ Generate look up table.

    :return: List
    """
    poly = 0xA001
    table = []

    for index in range(256):

        data = index << 1
        crc = 0
        for _ in range(8, 0, -1):
            data >>= 1
            if (data ^ crc) & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
        table.append(crc)

    return table


look_up_table = generate_look_up_table()


def get_crc(msg):
    """ Return CRC of 2 byte for message.

        >>> assert get_crc(b'\x02\x07') == struct.unpack('<H', b'\x41\x12')

    :param msg: A byte array.
    :return: Byte array of 2 bytes.
    """
    register = 0xFFFF

    for byte_ in msg:
        try:
            val = struct.unpack('<B', byte_)[0]
        # Iterating over a bit-like objects in Python 3 gets you ints.
        # Because fuck logic.
        except TypeError:
            val = byte_

        register = \
            (register >> 8) ^ look_up_table[(register ^ val) & 0xFF]

    # CRC is little-endian!
    return struct.pack('<H', register)


def add_crc(msg):
    """ Append CRC to message.

    :param msg: A byte array.
    :return: Byte array.
    """
    return msg + get_crc(msg)


def validate_crc(msg):
    """ Validate CRC of message.

    :param msg: Byte array with message with CRC.
    :raise: CRCError.
    """
    if not struct.unpack('<H', get_crc(msg[:-2])) ==\
            struct.unpack('<H', msg[-2:]):
        raise CRCError('CRC validation failed.')


class CRCError(Exception):
    """ Valid error to raise when CRC isn't correct. """
    pass
