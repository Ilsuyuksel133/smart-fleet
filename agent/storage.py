"""Stores investigations and their reports in the agent's own SQLite database.

Kept separate from the fleet API's database (own file, own Docker volume):
the agent must keep working even if the API or its database is the problem.
"""

import os
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine, make_url, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from agent.report import Alert, RCAReport


class Base(DeclarativeBase):
    pass


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_name: Mapped[str] = mapped_column(String(200), index=True)
    alert_json: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(50))  # "alertmanager" or "manual"
    status: Mapped[str] = mapped_column(String(20))  # queued -> running -> done | failed
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Copied out of the report so the list view does not need to parse JSON
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self, include_report: bool = False) -> dict:
        data = {
            "id": self.id,
            "alert_name": self.alert_name,
            "trigger": self.trigger,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "category": self.category,
            "confidence": self.confidence,
            "summary": self.summary,
        }
        if include_report:
            data["alert"] = Alert.model_validate_json(self.alert_json).model_dump()
            data["report"] = (
                RCAReport.model_validate_json(self.report_json).model_dump(mode="json")
                if self.report_json
                else None
            )
            data["error"] = self.error
        return data


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ReportStore:
    def __init__(self, database_url: str):
        url = make_url(database_url)
        connect_args = {}
        if url.get_backend_name() == "sqlite":
            if url.database and url.database != ":memory:" and os.path.dirname(url.database):
                os.makedirs(os.path.dirname(url.database), exist_ok=True)
            # The worker thread and the web threads share the database
            connect_args = {"check_same_thread": False}
        self.engine = create_engine(database_url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create(self, alert: Alert, trigger: str) -> int:
        with self.sessions() as session, session.begin():
            row = Investigation(
                alert_name=alert.name,
                alert_json=alert.model_dump_json(),
                trigger=trigger,
                status="queued",
                created_at=now(),
            )
            session.add(row)
            session.flush()
            return row.id

    def mark_running(self, investigation_id: int) -> None:
        self._update(investigation_id, status="running")

    def save_report(self, investigation_id: int, report: RCAReport) -> None:
        self._update(
            investigation_id,
            status="done",
            finished_at=now(),
            category=report.root_cause_category.value,
            confidence=report.confidence,
            summary=report.summary,
            report_json=report.model_dump_json(),
        )

    def mark_failed(self, investigation_id: int, error: str) -> None:
        self._update(investigation_id, status="failed", finished_at=now(), error=error)

    def get(self, investigation_id: int) -> Investigation | None:
        with self.sessions() as session:
            return session.get(Investigation, investigation_id)

    def latest(self, limit: int = 50) -> list[Investigation]:
        with self.sessions() as session:
            query = select(Investigation).order_by(Investigation.id.desc()).limit(limit)
            return list(session.scalars(query))

    def _update(self, investigation_id: int, **fields) -> None:
        with self.sessions() as session, session.begin():
            row = session.get(Investigation, investigation_id)
            for name, value in fields.items():
                setattr(row, name, value)
