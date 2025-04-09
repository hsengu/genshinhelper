import logging

# Configure logging module. If not set, pycord will not show any logging.
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# Provide a logger for our own application
logger = logging.getLogger()
