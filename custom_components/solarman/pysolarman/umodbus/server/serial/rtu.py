from __future__ import division
import struct
from binascii import hexlify

from . import log
from ...server.serial import AbstractSerialServer
from ...client.serial.redundancy_check import get_crc, validate_crc


def get_char_size(baudrate):
    """ Get the size of 1 character in seconds.

    From the implementation guide:

        "The implementation of RTU reception driver may imply the management of
        a lot of interruptions due to the t 1.5  and t 3.5  timers. With high

        communication baud rates, this leads to a heavy CPU load. Consequently
        these two timers must be strictly respected when the baud rate is equal
        or lower than 19200 Bps. For baud rates greater than 19200 Bps, fixed
        values for the 2 timers should be used:  it is recommended to use a
        value of 750us for the inter-character time-out (t 1.5) and a value of
        1.750ms for inter-frame delay (t 3.5)."
    """
    if baudrate <= 19200:
        # One frame is 11 bits.
        return 11 / baudrate

    # 750 us / 1.5 = 500 us or 0.0005 s.
    return 0.0005


class RTUServer(AbstractSerialServer):
    @property
    def serial_port(self):
        return self._serial_port

    @serial_port.setter
    def serial_port(self, serial_port):
        """ Set timeouts on serial port based on baudrate to detect frames. """
        char_size = get_char_size(serial_port.baudrate)

        # See docstring of get_char_size() for meaning of constants below.
        serial_port.inter_byte_timeout = 1.5 * char_size
        serial_port.timeout = 3.5 * char_size
        self._serial_port = serial_port

    def serve_once(self):
        """ Listen and handle 1 request. """
        # 256 is the maximum size of a Modbus RTU frame.
        request_adu = self.serial_port.read(256)
        log.debug('<-- {0}'.format(hexlify(request_adu)))

        if len(request_adu) == 0:
            raise ValueError

        response_adu = self.process(request_adu)
        self.respond(response_adu)

    def process(self, request_adu):
        """ Process request ADU and return response.

        :param request_adu: A bytearray containing the ADU request.
        :return: A bytearray containing the response of the ADU request.
        """
        validate_crc(request_adu)
        return super(RTUServer, self).process(request_adu)

    def create_response_adu(self, meta_data, response_pdu):
        """ Build response ADU from meta data and response PDU and return it.

        :param meta_data: A dict with meta data.
        :param request_pdu: A bytearray containing request PDU.
        :return: A bytearray containing request ADU.
        """
        first_part_adu = struct.pack('>B', meta_data['unit_id']) + response_pdu
        return first_part_adu + get_crc(first_part_adu)
