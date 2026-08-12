from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Iterable

from ..config import Settings


class EmailDeliveryError(RuntimeError):
    pass


class EmailClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def healthcheck(self) -> bool:
        if not self.settings.smtp_enabled:
            return True
        server = self._connect()
        try:
            server.noop()
        finally:
            try:
                server.quit()
            except Exception:
                server.close()
        return True

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.settings.smtp_use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=30,
                context=context,
            )
        else:
            server = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30)
            server.ehlo()
            if self.settings.smtp_starttls:
                server.starttls(context=context)
                server.ehlo()
        if self.settings.smtp_username:
            server.login(self.settings.smtp_username, self.settings.smtp_password)
        return server

    @staticmethod
    def _clean_addresses(values: Iterable[str]) -> list[str]:
        addresses: list[str] = []
        for value in values:
            address = (value or "").strip()
            if not address or "\n" in address or "\r" in address:
                continue
            addresses.append(address)
        return addresses

    def send(
        self,
        *,
        to: Iterable[str],
        subject: str,
        text_body: str,
        html_body: str | None = None,
        reply_to: str | None = None,
    ) -> str:
        if not self.settings.smtp_enabled:
            raise EmailDeliveryError("SMTP delivery is disabled")
        recipients = self._clean_addresses(to)
        if not recipients:
            raise EmailDeliveryError("Email message has no recipients")
        safe_subject = subject.replace("\r", " ").replace("\n", " ")[:300]
        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = ", ".join(recipients)
        message["Subject"] = safe_subject
        message["Date"] = formatdate(localtime=False)
        message_id = make_msgid(domain=self.settings.smtp_from_email.split("@")[-1])
        message["Message-ID"] = message_id
        chosen_reply_to = reply_to or self.settings.smtp_reply_to
        if chosen_reply_to:
            message["Reply-To"] = chosen_reply_to
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")
        server = self._connect()
        try:
            refused = server.send_message(message)
            if refused:
                raise EmailDeliveryError(f"SMTP refused recipients: {sorted(refused)}")
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(str(exc)) from exc
        finally:
            try:
                server.quit()
            except Exception:
                server.close()
        return message_id
