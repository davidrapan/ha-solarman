import struct
from binascii import hexlify
from types import MethodType
from serial import SerialTimeoutException

from . import log
from ...route import Map
from ...server import route
from ...functions import create_function_from_request_pdu
from ...exceptions import ModbusError, ServerDeviceFailureError
from ...utils import (get_function_code_from_request_pdu,
                           pack_exception_pdu)
from ...client.serial.redundancy_check import CRCError


def get_server(server_class, serial_port):
    """ Return instance of :param:`server_class` with :param:`request_handler`
    bound to it.
    This method also binds a :func:`route` method to the server instance.
        >>> server = get_server(TcpServer, ('localhost', 502), RequestHandler)
        >>> server.serve_forever()
    :param server_class: (sub)Class of :class:`socketserver.BaseServer`.
    :param request_handler_class: (sub)Class of
        :class:`umodbus.server.RequestHandler`.
    :return: Instance of :param:`server_class`.
    """
    s = server_class()
    s.serial_port = serial_port

    s.route_map = Map()
    s.route = MethodType(route, s)

    return s


class AbstractSerialServer(object):
    _shutdown_request = False

    def get_meta_data(self, request_adu):
        """" Extract MBAP header from request adu and return it. The dict has
        4 keys: transaction_id, protocol_id, length and unit_id.

        :param request_adu: A bytearray containing request ADU.
        :return: Dict with meta data of request.
        """
        return {
            'unit_id': struct.unpack('>B', request_adu[:1])[0],
        }

    def get_request_pdu(self, request_adu):
        """ Extract PDU from request ADU and return it.

        :param request_adu: A bytearray containing request ADU.
        :return: An bytearray container request PDU.
        """
        return request_adu[1:-2]

    def serve_once(self):
        """ Listen and handle 1 request. """
        raise NotImplementedError

    def serve_forever(self, poll_interval=0.5):
        """ Wait for incomming requests. """
        self.serial_port.timeout = poll_interval

        while not self._shutdown_request:
            try:
                self.serve_once()
            except (CRCError, struct.error) as e:
                log.error('Can\'t handle request: {0}'.format(e))
            except (SerialTimeoutException, ValueError):
                pass

    def process(self, request_adu):
        """ Process request ADU and return response.

        :param request_adu: A bytearray containing the ADU request.
        :return: A bytearray containing the response of the ADU request.
        """
        meta_data = self.get_meta_data(request_adu)
        request_pdu = self.get_request_pdu(request_adu)

        response_pdu = self.execute_route(meta_data, request_pdu)
        response_adu = self.create_response_adu(meta_data, response_pdu)

        return response_adu

    def execute_route(self, meta_data, request_pdu):
        """ Execute configured route based on requests meta data and request
        PDU.

        :param meta_data: A dict with meta data. It must at least contain
            key 'unit_id'.
        :param request_pdu: A bytearray containing request PDU.
        :return: A bytearry containing reponse PDU.
        """
        try:
            function = create_function_from_request_pdu(request_pdu)
            results =\
                function.execute(meta_data['unit_id'], self.route_map)

            try:
                # ReadFunction's use results of callbacks to build response
                # PDU...
                return function.create_response_pdu(results)
            except TypeError:
                # ...other functions don't.
                return function.create_response_pdu()
        except ModbusError as e:
            function_code = get_function_code_from_request_pdu(request_pdu)
            return pack_exception_pdu(function_code, e.error_code)
        except Exception as e:
            log.exception('Could not handle request: {0}.'.format(e))
            function_code = get_function_code_from_request_pdu(request_pdu)

            return pack_exception_pdu(function_code,
                                      ServerDeviceFailureError.error_code)

    def respond(self, response_adu):
        """ Send response ADU back to client.

        :param response_adu: A bytearray containing the response of an ADU.
        """
        log.debug('--> {0}'.format(hexlify(response_adu)))
        self.serial_port.write(response_adu)

    def shutdown(self):
        self._shutdown_request = True
