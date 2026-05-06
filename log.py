import logging
from logging.handlers import RotatingFileHandler
import os
import sys

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, 'app_debug.log')

logger = logging.getLogger("crypto_dashboard")
logger.setLevel(logging.DEBUG)

# Stream handler (console)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))

# File handler with rotation
# Max 10MB per file, keep 5 backup files
file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))

# Remove all handlers first (prevents duplicate logs on reload)
if logger.hasHandlers():
    logger.handlers.clear()

logger.addHandler(stream_handler)
logger.addHandler(file_handler)