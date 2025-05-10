from logging import getLogger, NullHandler

log = getLogger('uModbus')
log.addHandler(NullHandler())

from .config import Config  # NOQA
conf = Config()
