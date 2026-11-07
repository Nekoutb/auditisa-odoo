import logging
import os
import re
import threading
import traceback

from odoo import api, models
from odoo.tools import config

from ..services import errors

_DB = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_installed = threading.Lock()
_handler = None


def errors_file(dbname):
    """One file per database, in Odoo's own data folder, which only Odoo writes."""
    if not dbname or not _DB.match(dbname):
        return None
    return os.path.join(config["data_dir"], "auditisa", f"errors-{dbname}.log")


class ErrorCodeHandler(logging.Handler):
    """Writes one line of codes per technical error. It never writes a message or a value."""

    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, record):
        try:
            if record.levelno < logging.ERROR or not record.exc_info or not record.exc_info[0]:
                return
            exception_type, _value, tb = record.exc_info
            paths = [frame.filename for frame in traceback.extract_tb(tb, limit=60)] if tb else []
            module = errors.module_of(paths)
            model = "-"
            try:
                from odoo.http import request
                if request and getattr(request, "registry", None) is not None:
                    params = getattr(request, "params", None) or {}
                    model = errors.model_code(params.get("model"), request.registry)
            except Exception:  # noqa: BLE001 - no request, or none we can read: no model
                model = "-"
            path = errors_file(getattr(threading.current_thread(), "dbname", None))
            if not path:
                return
            os.makedirs(os.path.dirname(path), mode=0o750, exist_ok=True)
            text = errors.line(module, model, errors.kind_code(exception_type)).encode("ascii")
            handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                os.write(handle, text)
            finally:
                os.close(handle)
        except Exception:  # noqa: BLE001 - recording an error must never cause one
            return


def install_handler():
    global _handler
    with _installed:
        if _handler is None:
            _handler = ErrorCodeHandler()
            logging.getLogger("odoo").addHandler(_handler)
    return _handler


class EaFirmErrorCapture(models.AbstractModel):
    _name = "ea.firm.error.capture"
    _description = "Technical errors of this server, as codes"

    def _register_hook(self):
        install_handler()
        return super()._register_hook()

    @api.model
    def _take(self):
        """The lines since the last heartbeat. They stay in a side file until one is delivered."""
        path = errors_file(self.env.cr.dbname)
        if not path:
            return [], None
        sending = path + ".sending"
        try:
            if os.path.exists(path):
                with open(path, "rb") as source, open(sending, "ab") as target:
                    target.write(source.read())
                os.truncate(path, 0)
            with open(sending, encoding="ascii", errors="replace") as handle:
                return handle.read(512 * 1024).splitlines(), sending
        except OSError:
            return [], None

    @api.model
    def _delivered(self, sending):
        if sending:
            try:
                os.remove(sending)
            except OSError:
                pass
