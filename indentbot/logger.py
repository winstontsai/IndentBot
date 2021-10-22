import logging

logger = logging.getLogger('indentbot_logger')

file_handler = logging.FileHandler(filename = "logs/indentbot.log")
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

logger.addHandler(file_handler)
logger.setLevel(logging.INFO)

logger.propagate = False
