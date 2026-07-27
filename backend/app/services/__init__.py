"""Business-logic layer."""

from app.services.audit import AuditService
from app.services.auth import AuthService, RequestContext
from app.services.crash import CrashService, IngestResult
from app.services.crash_parser import (
    PARSER_VERSION,
    CrashParseError,
    CrashParser,
    ParsedCrash,
    crash_parser,
)
from app.services.device import DeviceService
from app.services.email import (
    ConsoleEmailSender,
    EmailSender,
    InMemoryEmailSender,
    OutgoingEmail,
    SMTPEmailSender,
    get_email_sender,
)
from app.services.user import UserService

__all__ = [
    "PARSER_VERSION",
    "AuditService",
    "AuthService",
    "ConsoleEmailSender",
    "CrashParseError",
    "CrashParser",
    "CrashService",
    "DeviceService",
    "EmailSender",
    "InMemoryEmailSender",
    "IngestResult",
    "OutgoingEmail",
    "ParsedCrash",
    "RequestContext",
    "SMTPEmailSender",
    "UserService",
    "crash_parser",
    "get_email_sender",
]
