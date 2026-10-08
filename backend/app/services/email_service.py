import smtplib
import ssl
from email.message import EmailMessage


class EmailError(Exception):
    pass


def split_addrs(v: str | None) -> list[str]:
    if not v:
        return []
    return [a.strip() for a in v.replace(";", ",").replace("\n", ",").split(",") if a.strip()]


class EmailService:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, int(port or 587), user, password, sender

    def _connect(self):
        if not self.host:
            raise EmailError("SMTP não configurado")
        ctx = ssl.create_default_context()
        try:
            if self.port == 465:
                s = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=ctx)
            else:
                s = smtplib.SMTP(self.host, self.port, timeout=30)
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
            if self.user:
                s.login(self.user, self.password)
            return s
        except (smtplib.SMTPException, OSError) as e:
            raise EmailError(f"{type(e).__name__}: {e}") from e

    def test(self):
        s = self._connect()
        s.quit()

    def send(self, to: list[str], subject: str, body: str, cc: list[str] | None = None, bcc: list[str] | None = None,
             attachments: list[tuple[str, bytes, str]] | None = None, html: str | None = None):
        if not to:
            raise EmailError("Sem destinatários")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender or self.user, ", ".join(to), subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
        for name, data, mime in attachments or []:
            main, sub = mime.split("/", 1)
            msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
        s = self._connect()
        try:
            s.send_message(msg, to_addrs=to + (cc or []) + (bcc or []))
        except (smtplib.SMTPException, OSError) as e:
            raise EmailError(f"{type(e).__name__}: {e}") from e
        finally:
            try:
                s.quit()
            except Exception:
                pass
