"""Refusals raised by the services. The message is the source's kebab-case code,
so a caller maps it to a translated message exactly as the action layer did."""


class ServiceError(Exception):
    """A plain ``throw new Error("some-code")`` in the source."""

    def __init__(self, code=""):
        super().__init__(code)
        self.code = code


class JsRangeError(ServiceError):
    """``RangeError``: for instance ``toISOString`` on an invalid date."""


class EngineError(ServiceError):
    """``EngineError`` of lib/engines.ts."""


class TbError(ServiceError):
    """``TbError`` of lib/tb.ts."""


class SubLedgerError(ServiceError):
    """``SubLedgerError`` of lib/subledgers.ts."""


class LegalError(ServiceError):
    """``LegalError`` of lib/legal.ts."""


class RetentionError(ServiceError):
    """``RetentionError`` of lib/retention.ts."""


class EmailDomainError(ServiceError):
    """An address outside the firm's allowed domains."""

    def __init__(self, allowed):
        super().__init__("email-domain-not-allowed")
        self.allowed = allowed
