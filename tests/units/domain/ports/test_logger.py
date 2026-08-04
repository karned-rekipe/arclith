from arclith.domain.ports.outbound.logger import LogLevel


def test_debug(logger):
    logger.debug("msg", x = 1)
    assert logger.records[-1]["level"] == LogLevel.DEBUG


def test_info(logger):
    logger.info("msg")
    assert logger.records[-1]["level"] == LogLevel.INFO


def test_warning(logger):
    logger.warning("msg")
    assert logger.records[-1]["level"] == LogLevel.WARNING


def test_error(logger):
    logger.error("msg")
    assert logger.records[-1]["level"] == LogLevel.ERROR


def test_critical(logger):
    logger.critical("msg")
    assert logger.records[-1]["level"] == LogLevel.CRITICAL
