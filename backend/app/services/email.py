"""Outbound email over SMTP, using the standard library.

`smtplib` and `email.message` ship with Python, so sending mail costs this
project no new dependency and no account with a sending service. Configuration
is five values: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM.

**Encryption is derived from the port, not configured.** Port 465 is implicit
TLS; every other port is STARTTLS, which covers Gmail on 587. A separate mode
setting would be one more thing to get wrong, and the cost of getting it wrong
is password reset links crossing the network in clear text. There is no
plaintext path: a server that will not negotiate TLS fails the send.

**Two things this module is careful about.**

*It never blocks the event loop.* `smtplib` is synchronous and a slow relay can
take seconds, so the whole conversation runs in a worker thread via
`asyncio.to_thread`. Calling it directly from an async request handler would
stall every other request on that worker for the duration.

*Not sending is not an error.* With no host configured, or a relay that refuses,
`send` logs and returns False. Callers treat that as "the email did not go out",
never as "the request failed" — because the one caller that matters, the forgot
password endpoint, must answer identically whether or not a mailbox exists.
Raising here would turn a delivery problem into an account-enumeration oracle:
a 500 for real addresses and a 200 for everything else tells an attacker exactly
which accounts exist.

Credentials are never logged. Failures are reported by exception *type* and, for
SMTP errors, by the server's numeric code — never its message, which commonly
echoes the username, and never the password.
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Callable, Optional

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

#: The one port that speaks TLS from the first byte. Anything else is upgraded
#: with STARTTLS after the greeting.
IMPLICIT_TLS_PORT = 465

#: Seconds to wait on the SMTP conversation. A constant rather than a setting:
#: sending already runs off the event loop, and the only thing a knob here would
#: change is how long a hung relay pins a worker thread.
SMTP_TIMEOUT_SECONDS = 15.0


class EmailService:
    """Sends transactional email over SMTP, or reports honestly that it could not."""

    def __init__(self, sender: Optional[Callable[[EmailMessage], None]] = None):
        #: Injectable so tests never open a socket. Defaults to real SMTP.
        self._sender = sender or self._send_via_smtp

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Whether a transport is usable right now.

        A username is deliberately not required: plenty of relays — a local
        Postfix, an internal smarthost — accept unauthenticated mail from known
        hosts, and demanding credentials would make those impossible to use.
        """
        return bool(settings.SMTP_HOST and settings.SMTP_FROM)

    @staticmethod
    def uses_implicit_tls() -> bool:
        """Whether this port expects TLS from the first byte (465) rather than
        a STARTTLS upgrade (587 and everything else)."""
        return int(settings.SMTP_PORT) == IMPLICIT_TLS_PORT

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, *, to: str, subject: str, html: str, text: str) -> bool:
        """Send one message. Returns whether the relay accepted it.

        Never raises for a delivery problem — see the module docstring.
        """
        if not self.is_configured():
            # Deliberately does not log the body: a reset link in a log file is
            # the same credential as a reset link in an inbox.
            logger.warning(
                "email_not_sent_transport_unconfigured",
                reason="SMTP_HOST or SMTP_FROM is not configured",
            )
            return False

        message = self._build_message(to=to, subject=subject, html=html, text=text)

        try:
            # smtplib is blocking; keep it off the event loop.
            await asyncio.to_thread(self._sender, message)
        except smtplib.SMTPAuthenticationError as exc:
            # `exc.smtp_error` often echoes the username back. Code only.
            logger.warning("email_send_auth_failed", smtp_code=getattr(exc, "smtp_code", None))
            return False
        except smtplib.SMTPException as exc:
            logger.warning(
                "email_send_rejected",
                error_type=type(exc).__name__,
                smtp_code=getattr(exc, "smtp_code", None),
            )
            return False
        except (OSError, ssl.SSLError) as exc:
            # Connection refused, DNS failure, TLS handshake, timeout.
            logger.warning("email_send_transport_failed", error_type=type(exc).__name__)
            return False
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("email_send_failed", error_type=type(exc).__name__)
            return False

        logger.info(
            "email_sent",
            tls="implicit" if self.uses_implicit_tls() else "starttls",
        )
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_message(self, *, to: str, subject: str, html: str, text: str) -> EmailMessage:
        """A multipart/alternative message.

        Plain text is set first and HTML added as the alternative, which is the
        order `EmailMessage` needs for clients to prefer HTML while leaving a
        readable fallback — and a text part is what keeps the message out of
        spam folders that distrust HTML-only mail.
        """
        message = EmailMessage()
        message["Subject"] = subject
        # The bare address. A display name would need a sixth setting, and an
        # invented one would misrepresent who the mail is from.
        message["From"] = settings.SMTP_FROM or ""
        message["To"] = to
        message["Message-ID"] = make_msgid()
        # Reset mail is a reply to nothing and should never be auto-answered.
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        return message

    def _send_via_smtp(self, message: EmailMessage) -> None:
        """One SMTP conversation. Runs in a worker thread; raises on failure."""
        host = settings.SMTP_HOST or ""
        port = int(settings.SMTP_PORT)
        context = ssl.create_default_context()

        if self.uses_implicit_tls():
            # Verifies certificate and hostname by default.
            with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context) as client:
                self._authenticate(client)
                client.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS) as client:
            client.ehlo()
            # Raises SMTPNotSupportedError if the server will not upgrade, which
            # `send` catches and reports as a failed delivery. Deliberately not
            # a fallback to plaintext: mail carrying a password reset link must
            # not go out unencrypted because a relay declined.
            client.starttls(context=context)
            # Re-introduce: capabilities change after the upgrade, and AUTH is
            # commonly only offered once the connection is encrypted.
            client.ehlo()
            self._authenticate(client)
            client.send_message(message)

    @staticmethod
    def _authenticate(client: smtplib.SMTP) -> None:
        """Log in when credentials are configured, otherwise send unauthenticated."""
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)


def password_reset_email(reset_url: str, ttl_minutes: int) -> tuple[str, str, str]:
    """Subject, HTML and plain-text for a reset message.

    Says plainly that an unexpected email can be ignored, because that is the
    only useful instruction for the person who did not request it — and states
    the expiry, so a stale link is understood rather than reported as a bug.
    """
    subject = "Reset your SEO Agent password"

    text = (
        "We received a request to reset the password for your SEO Agent account.\n\n"
        f"Open this link to choose a new password:\n{reset_url}\n\n"
        f"The link works once and expires in {ttl_minutes} minutes.\n\n"
        "If you did not ask for this, you can ignore this email — your password "
        "has not been changed and the link will expire on its own."
    )

    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:480px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:28px;">
          <tr><td style="font-size:18px;font-weight:600;color:#0f172a;padding-bottom:12px;">
            Reset your password
          </td></tr>
          <tr><td style="font-size:14px;line-height:1.6;color:#475569;">
            We received a request to reset the password for your SEO Agent account.
          </td></tr>
          <tr><td style="padding:22px 0 8px;">
            <a href="{reset_url}"
               style="display:inline-block;background:#1d4ed8;color:#ffffff;text-decoration:none;
                      font-weight:600;font-size:14px;padding:11px 22px;border-radius:8px;">
              Choose a new password
            </a>
          </td></tr>
          <tr><td style="font-size:12px;line-height:1.6;color:#64748b;padding-top:14px;">
            The link works once and expires in {ttl_minutes} minutes.<br>
            If you did not ask for this, you can ignore this email — your password
            has not been changed.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

    return subject, html, text
