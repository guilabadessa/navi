from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


ROLES = ("ADMIN", "GESTOR", "ANALISTA_NOC", "VISUALIZADOR", "CLIENTE")
SEVERITIES = {0: "Não classificado", 1: "Informação", 2: "Atenção", 3: "Média", 4: "Alta", 5: "Desastre"}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="VISUALIZADOR")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)  # perfil CLIENTE
    invite_pending: Mapped[bool] = mapped_column(Boolean, default=False)  # convite enviado e ainda nao aceito
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    user_email: Mapped[str | None] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), default="ok")
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(String(255))


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    trade_name: Mapped[str] = mapped_column(String(255), index=True)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    cnpj: Mapped[str | None] = mapped_column(String(32))
    state_registration: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(512))
    city: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(2))
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    whatsapp: Mapped[str | None] = mapped_column(String(64))
    whatsapp_group_jid: Mapped[str | None] = mapped_column(String(128))
    report_emails: Mapped[str | None] = mapped_column(Text)
    logo_path: Mapped[str | None] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    sla_target: Mapped[float] = mapped_column(Float, default=99.5)
    service_hours: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="ativo")
    # Alertas WhatsApp (padrao do cliente)
    wa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    wa_min_severity: Mapped[int] = mapped_column(Integer, default=3)
    wa_delay_s: Mapped[int] = mapped_column(Integer, default=0)
    wa_send_recovery: Mapped[bool] = mapped_column(Boolean, default=True)
    wa_hours: Mapped[str | None] = mapped_column(String(64))  # ex: "08:00-18:00" (vazio = 24x7)
    maintenance_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wa_problem_template_id: Mapped[int | None] = mapped_column(Integer)
    wa_recovery_template_id: Mapped[int | None] = mapped_column(Integer)
    mail_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # alertas por e-mail (usa mesma severidade/atraso/horario)
    alert_emails: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    groups: Mapped[list["ClientHostGroup"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    hosts: Mapped[list["ClientHost"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    contacts: Mapped[list["ClientContact"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ClientHostGroup(Base):
    __tablename__ = "client_host_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    zbx_groupid: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (UniqueConstraint("client_id", "zbx_groupid"),)


class ClientHost(Base):
    __tablename__ = "client_hosts"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    zbx_hostid: Mapped[str] = mapped_column(String(32), index=True)
    __table_args__ = (UniqueConstraint("client_id", "zbx_hostid"),)


class ClientContact(Base):
    __tablename__ = "client_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))


class ZbxHostGroup(Base):
    __tablename__ = "zbx_host_groups"
    groupid: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    host_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ZbxHost(Base):
    __tablename__ = "zbx_hosts"
    hostid: Mapped[str] = mapped_column(String(32), primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[int] = mapped_column(Integer, default=0)  # 0 monitorado, 1 desabilitado
    ip: Mapped[str | None] = mapped_column(String(64), index=True)
    dns: Mapped[str | None] = mapped_column(String(255))
    available: Mapped[int] = mapped_column(Integer, default=0)  # 0 desconhecido 1 ok 2 indisponivel
    interfaces: Mapped[list | None] = mapped_column(JSON)
    group_ids: Mapped[list | None] = mapped_column(JSON)
    templates: Mapped[list | None] = mapped_column(JSON)
    tags: Mapped[list | None] = mapped_column(JSON)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zbx_eventid: Mapped[str] = mapped_column(String(96), unique=True, index=True)  # Zabbix: id numerico; outras fontes: "origem:id"
    kind: Mapped[str] = mapped_column(String(12), default="infra", index=True)  # infra (Zabbix) | backup (Acronis) | endpoint (EMS)
    r_eventid: Mapped[str | None] = mapped_column(String(32))
    hostid: Mapped[str | None] = mapped_column(String(64), index=True)
    host: Mapped[str | None] = mapped_column(String(255), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    triggerid: Mapped[str | None] = mapped_column(String(64), index=True)
    trigger_name: Mapped[str | None] = mapped_column(String(1024))
    itemid: Mapped[str | None] = mapped_column(String(32))
    item_name: Mapped[str | None] = mapped_column(String(1024))
    severity: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(16), default="PROBLEM", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    group_ids: Mapped[list | None] = mapped_column(JSON)
    group_names: Mapped[list | None] = mapped_column(JSON)
    tags: Mapped[list | None] = mapped_column(JSON)
    opdata: Mapped[str | None] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    wa_message_id: Mapped[str | None] = mapped_column(String(255))
    wa_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wa_status: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_events_client_started", "client_id", "started_at"),)


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), default="problem")  # problem | recovery
    body: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ExtTenant(Base):
    """Cliente (tenant) de uma plataforma externa (Acronis, EMS) e a associacao com o cliente da NAVI."""
    __tablename__ = "ext_tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # acronis | ems
    ext_id: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str | None] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("source", "ext_id"),)


class ExtAsset(Base):
    """Maquina/caixa postal/endpoint monitorado por uma plataforma externa."""
    __tablename__ = "ext_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    ext_id: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(32))
    ext_tenant_id: Mapped[int | None] = mapped_column(ForeignKey("ext_tenants.id", ondelete="SET NULL"), index=True)
    policy_name: Mapped[str | None] = mapped_column(String(255))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_result: Mapped[str | None] = mapped_column(String(64))
    online: Mapped[bool | None] = mapped_column(Boolean)
    offline_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)  # nao alertar "sem backup" / "offline"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("source", "ext_id"),)


class MaintenanceWindow(Base):
    """Janela de manutencao: suprime alertas e descontada do SLA. 'once' (inicio/fim) ou 'weekly' (dias + hora + duracao)."""
    __tablename__ = "maintenance_windows"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)  # vazio = todos
    kind: Mapped[str] = mapped_column(String(8), default="once")  # once | weekly
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weekdays: Mapped[list | None] = mapped_column(JSON)  # 0=segunda ... 6=domingo
    start_time: Mapped[str | None] = mapped_column(String(5))  # HH:MM (horario local)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SeverityRule(Base):
    """Reclassifica a severidade de eventos (ex.: triggers SD-WAN 'Nao classificado' tratadas como Alta)."""
    __tablename__ = "severity_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    host_pattern: Mapped[str | None] = mapped_column(String(255))
    trigger_pattern: Mapped[str | None] = mapped_column(String(255))
    from_max: Mapped[int] = mapped_column(Integer, default=0)  # so reclassifica se a severidade original for <= este valor
    severity: Mapped[int] = mapped_column(Integer, default=4)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    host_pattern: Mapped[str | None] = mapped_column(String(255))  # substring/glob, case-insensitive
    trigger_pattern: Mapped[str | None] = mapped_column(String(255))
    severities: Mapped[list | None] = mapped_column(JSON)  # lista de ints; vazio = qualquer >= min_severity
    min_severity: Mapped[int] = mapped_column(Integer, default=0)
    on_problem: Mapped[bool] = mapped_column(Boolean, default=True)
    on_recovery: Mapped[bool] = mapped_column(Boolean, default=True)
    delay_s: Mapped[int] = mapped_column(Integer, default=0)
    dest_jid: Mapped[str | None] = mapped_column(String(128))  # vazio = grupo do cliente
    problem_template_id: Mapped[int | None] = mapped_column(Integer)
    recovery_template_id: Mapped[int | None] = mapped_column(Integer)
    quote_recovery: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_whatsapp: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    email_to: Mapped[str | None] = mapped_column(Text)  # vazio = e-mails de alerta do cliente do evento
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Dispatch(Base):
    __tablename__ = "dispatches"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # problem | recovery | escalation
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")  # whatsapp | email
    dest_jid: Mapped[str] = mapped_column(String(512))  # JID/numero (whatsapp) ou enderecos separados por virgula (email)
    template_id: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), index=True)
    cnpj: Mapped[str | None] = mapped_column(String(32))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    host_ids: Mapped[list | None] = mapped_column(JSON)
    group_ids: Mapped[list | None] = mapped_column(JSON)
    triggers: Mapped[list | None] = mapped_column(JSON)
    items: Mapped[list | None] = mapped_column(JSON)
    severities: Mapped[list | None] = mapped_column(JSON)
    include_resolved: Mapped[bool] = mapped_column(Boolean, default=True)
    include_open: Mapped[bool] = mapped_column(Boolean, default=True)
    include_charts: Mapped[bool] = mapped_column(Boolean, default=True)
    include_kpis: Mapped[bool] = mapped_column(Boolean, default=True)
    letterhead: Mapped[str] = mapped_column(String(64), default="orca")
    notes: Mapped[str | None] = mapped_column(Text)
    wa_dest: Mapped[str | None] = mapped_column(String(128))
    email_dest: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportRun(Base):
    __tablename__ = "report_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"), index=True)
    client_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    generated_by: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(512))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    wa_status: Mapped[str | None] = mapped_column(String(255))
    email_status: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    kpis: Mapped[dict | None] = mapped_column(JSON)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    frequency: Mapped[str] = mapped_column(String(16), default="monthly")  # daily|weekly|monthly|custom
    run_time: Mapped[str] = mapped_column(String(5), default="08:00")
    weekday: Mapped[int | None] = mapped_column(Integer)  # 0=segunda
    month_day: Mapped[int | None] = mapped_column(Integer, default=1)
    interval_days: Mapped[int | None] = mapped_column(Integer)  # custom
    period_mode: Mapped[str] = mapped_column(String(24), default="prev_month")
    # prev_day | prev_week | prev_month | last_n_days
    period_days: Mapped[int | None] = mapped_column(Integer)
    wa_dest: Mapped[str | None] = mapped_column(String(128))
    email_to: Mapped[str | None] = mapped_column(Text)
    email_cc: Mapped[str | None] = mapped_column(Text)
    email_bcc: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(512), default="Relatório de Disponibilidade — {CLIENTE} — {PERIODO}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_status: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JobStatus(Base):
    __tablename__ = "job_status"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(255))
    interval_s: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    counts: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")


class HealthCheck(Base):
    __tablename__ = "health_checks"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)  # zabbix | evolution | email | navi
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str | None] = mapped_column(String(512))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
