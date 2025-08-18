import struct
from types import MethodType

from ..route import Map
from ..server import AbstractRequestHandler, route
from ..utils import unpack_mbap, pack_mbap
from ..exceptions import ServerDeviceFailureError


def get_server(server_class, server_address, request_handler_class):
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
    s = server_class(server_address, request_handler_class)

    s.route_map = Map()
    s.route = MethodType(route, s)

    return s


class RequestHandler(AbstractRequestHandler):
    """ A subclass of :class:`socketserver.BaseRequestHandler` dispatching
    incoming Modbus TCP/IP request using the server's :attr:`route_map`.

    """
    def get_meta_data(self, request_adu):
        """" Extract MBAP header from request adu and return it. The dict has
        4 keys: transaction_id, protocol_id, length and unit_id.

        :param request_adu: A bytearray containing request ADU.
        :return: Dict with meta data of request.
        """
        try:
            transaction_id, protocol_id, length, unit_id = \
                unpack_mbap(request_adu[:7])
        except struct.error:
            raise ServerDeviceFailureError()

        return {
            'transaction_id': transaction_id,
            'protocol_id': protocol_id,
            'length': length,
            'unit_id': unit_id,
        }

    def get_request_pdu(self, request_adu):
        """ Extract PDU from request ADU and return it.

        :param request_adu: A bytearray containing request ADU.
        :return: An bytearray container request PDU.
        """
        return request_adu[7:]

    def create_response_adu(self, meta_data, response_pdu):
        """ Build response ADU from meta data and response PDU and return it.

        :param meta_data: A dict with meta data.
        :param request_pdu: A bytearray containing request PDU.
        :return: A bytearray containing request ADU.
        """
        response_mbap = pack_mbap(
            transaction_id=meta_data['transaction_id'],
            protocol_id=meta_data['protocol_id'],
            length=len(response_pdu) + 1,
            unit_id=meta_data['unit_id']
        )

        return response_mbap + response_pdu
