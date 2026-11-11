"""Prevent request targets and other untrusted fields entering access logs."""
import logging


class _PrivateAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn supplies peer, method, request target, HTTP version and status.
        # Keep the formatter's tuple shape and use only fixed or bounded fields.
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            return False
        _, method, target, version, status = record.args
        if type(status) is not int or not 100 <= status <= 599:
            return False
        method = method if method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") else "OTHER"
        version = version if version in ("1.0", "1.1", "2", "3") else "?"
        record.msg = '%s - "%s %s HTTP/%s" %d'
        # Keep a fixed webhook route label for operational diagnostics.
        # Never reuse the raw path, token, or query string.
        webhook = "/channels/sms/inbound/"
        label = webhook + "***" if isinstance(target, str) and target.startswith(webhook) else "[redacted]"
        record.args = ("client", method, label, version, status)
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def protect_uvicorn_access() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _PrivateAccessLogFilter) for f in access.filters):
        access.addFilter(_PrivateAccessLogFilter())
