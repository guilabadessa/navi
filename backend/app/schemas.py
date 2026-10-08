from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from .formats import fmt_cnpj, fmt_phone

Role = Literal["ADMIN", "GESTOR", "ANALISTA_NOC", "VISUALIZADOR"]


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2, max_length=255)
    role: Role = "VISUALIZADOR"
    active: bool = True
    password: str | None = Field(default=None, min_length=10, max_length=256)


class ClientIn(BaseModel):
    trade_name: str = Field(min_length=2, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    cnpj: str | None = Field(default=None, max_length=32)
    state_registration: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=512)
    city: str | None = Field(default=None, max_length=128)
    state: str | None = Field(default=None, max_length=2)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    whatsapp: str | None = Field(default=None, max_length=64)
    whatsapp_group_jid: str | None = Field(default=None, max_length=128)
    report_emails: str | None = None
    notes: str | None = None
    sla_target: float = Field(default=99.5, ge=0, le=100)
    service_hours: str | None = Field(default=None, max_length=255)
    status: Literal["ativo", "inativo"] = "ativo"
    wa_enabled: bool = False
    wa_min_severity: int = Field(default=3, ge=0, le=5)
    wa_delay_s: int = Field(default=0, ge=0, le=86400)
    wa_send_recovery: bool = True
    wa_hours: str | None = Field(default=None, max_length=64)
    maintenance_until: datetime | None = None
    wa_problem_template_id: int | None = None
    wa_recovery_template_id: int | None = None
    group_ids: list[str] = []
    host_ids: list[str] = []
    contacts: list[dict] = []

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v):
        return fmt_cnpj(v)

    @field_validator("phone", "whatsapp")
    @classmethod
    def _phone(cls, v):
        return fmt_phone(v)

    @field_validator("whatsapp_group_jid")
    @classmethod
    def jid(cls, v):
        if v and "@" not in v:
            v = f"{v}@g.us"
        return v or None


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    client_id: int | None = None
    host_pattern: str | None = Field(default=None, max_length=255)
    trigger_pattern: str | None = Field(default=None, max_length=255)
    severities: list[int] | None = None
    min_severity: int = Field(default=0, ge=0, le=5)
    on_problem: bool = True
    on_recovery: bool = True
    delay_s: int = Field(default=0, ge=0, le=86400)
    dest_jid: str | None = Field(default=None, max_length=128)
    problem_template_id: int | None = None
    recovery_template_id: int | None = None
    quote_recovery: bool = True
    enabled: bool = True


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    kind: Literal["problem", "recovery"] = "problem"
    body: str = Field(min_length=3, max_length=4000)
    is_default: bool = False


class ReportIn(BaseModel):
    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v):
        return fmt_cnpj(v)

    name: str = Field(min_length=2, max_length=255)
    client_id: int | None = None
    cnpj: str | None = Field(default=None, max_length=32)
    period_start: datetime | None = None
    period_end: datetime | None = None
    host_ids: list[str] = []
    group_ids: list[str] = []
    triggers: list[str] = []
    items: list[str] = []
    severities: list[int] = []
    include_resolved: bool = True
    include_open: bool = True
    include_charts: bool = True
    include_kpis: bool = True
    letterhead: str = "orca"
    notes: str | None = None
    wa_dest: str | None = Field(default=None, max_length=128)
    email_dest: str | None = None


class GenerateIn(BaseModel):
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_mode: Literal["prev_day", "prev_week", "prev_month", "last_n_days"] | None = None
    period_days: int | None = Field(default=None, ge=1, le=366)
    send_wa: bool = False
    send_email: bool = False


class SendIn(BaseModel):
    wa_dest: str | None = None
    email_to: str | None = None
    email_cc: str | None = None
    email_bcc: str | None = None
    subject: str | None = None


class ScheduleIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    report_id: int
    frequency: Literal["daily", "weekly", "monthly", "custom"] = "monthly"
    run_time: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    month_day: int | None = Field(default=1, ge=1, le=31)
    interval_days: int | None = Field(default=None, ge=1, le=365)
    period_mode: Literal["prev_day", "prev_week", "prev_month", "last_n_days"] = "prev_month"
    period_days: int | None = Field(default=None, ge=1, le=366)
    wa_dest: str | None = None
    email_to: str | None = None
    email_cc: str | None = None
    email_bcc: str | None = None
    subject: str = Field(default="Relatório de Disponibilidade — {CLIENTE} — {PERIODO}", max_length=512)
    enabled: bool = True


class ZabbixSettingsIn(BaseModel):
    url: str = Field(max_length=512)
    token: str | None = None  # vazio = manter


class EvolutionSettingsIn(BaseModel):
    url: str = Field(max_length=512)
    instance: str = Field(max_length=128)
    api_key: str | None = None


class SmtpSettingsIn(BaseModel):
    host: str = Field(max_length=255)
    port: int = Field(ge=1, le=65535)
    user: str | None = Field(default=None, max_length=255)
    password: str | None = None
    from_: str | None = Field(default=None, alias="from", max_length=255)


class LetterheadIn(BaseModel):
    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v):
        return fmt_cnpj(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return fmt_phone(v)

    company: str = Field(max_length=255)
    cnpj: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=512)
    phone: str | None = Field(default=None, max_length=64)
    site: str | None = Field(default=None, max_length=255)
    text: str | None = Field(default=None, max_length=1000)


class TestSend(BaseModel):
    to: str = Field(max_length=255)
    text: str = Field(default="Teste de envio — NAVI Orca TI ✅", max_length=2000)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
