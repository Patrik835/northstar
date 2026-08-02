class ConnectorError(Exception):
    """A sanitized integration error safe to expose to service logs."""


class ConnectorAuthenticationError(ConnectorError):
    pass


class ConnectorRateLimitError(ConnectorError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("Broker API rate limit reached")

