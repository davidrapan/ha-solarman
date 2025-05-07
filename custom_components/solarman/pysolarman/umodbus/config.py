import os


class Config(object):
    """ Class to hold global configuration. """

    SINGLE_BIT_VALUE_FORMAT_CHARACTER = 'B'
    """ Format character used to (un)pack singlebit values (values used for
    writing from and writing to coils or discrete inputs) from structs.

    .. note:: Its value should not be changed. This attribute exists to be
        consistend with `MULTI_BIT_VALUE_FORMAT_CHARACTER`.
    """

    MULTI_BIT_VALUE_FORMAT_CHARACTER = 'H'
    """ Format character used to (un)pack multibit values (values used for
    writing from and writing to registers) from structs.

    The format character depends on size of the value and whether values are
    signed or unsigned.

    By default multibit values are unsigned and use 16 bits. The default format
    character used for (un)packing structs is 'H'.

    .. note:: Its value should not be set directly. Instead use
        :attr:`SIGNED_VALUES` and :attr:`BIT_SIZE` to
        modify this value.

    """
    def __init__(self):
        self.SIGNED_VALUES = os.environ.get('UMODBUS_SIGNED_VALUES', False)
        self.BIT_SIZE = os.environ.get('UMODBUS_BIT_SIZE', 16)

    @property
    def TYPE_CHAR(self):
        if self.SIGNED_VALUES:
            return 'h'

        return 'H'

    def _set_multi_bit_value_format_character(self):
        """ Set format character for multibit values.

        The format character depends on size of the value and whether values
        are signed or unsigned.

        """
        self.MULTI_BIT_VALUE_FORMAT_CHARACTER = \
            self.MULTI_BIT_VALUE_FORMAT_CHARACTER.upper()

        if self.SIGNED_VALUES:
            self.MULTI_BIT_VALUE_FORMAT_CHARACTER = \
                self.MULTI_BIT_VALUE_FORMAT_CHARACTER.lower()

    @property
    def SIGNED_VALUES(self):
        """ Whether values are signed or not. Default is False.

        This value can also be set using the environment variable
        `UMODBUS_SIGNED_VALUES`.
        """
        return self._SIGNED_VALUES

    @SIGNED_VALUES.setter
    def SIGNED_VALUES(self, value):
        """ Set signedness of values.

        This method effects `Config.MULTI_BIT_VALUE_FORMAT_CHARACTER`.
        :param value: Boolean indicting if values are signed or not.
        """
        self._SIGNED_VALUES = value
        self._set_multi_bit_value_format_character()

    @property
    def BIT_SIZE(self):
        """ Bit size of values. Default is 16.

        This value can also be set using the environment variable
        `UMODBUS_BIT_SIZE`.
        """
        return self._BIT_SIZE

    @BIT_SIZE.setter
    def BIT_SIZE(self, value):
        """ Set bit size of values.

        This method effects `Config.MULTI_BIT_VALUE_FORMAT_CHARACTER`.
        :param value: Number indication bit size.
        """
        self._BIT_SIZE = value
        self._set_multi_bit_value_format_character()
