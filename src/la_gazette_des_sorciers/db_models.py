from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Sources(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(nullable=False)
    region: Mapped[str] = mapped_column(nullable=False)
    url_flux: Mapped[str] = mapped_column(nullable=False)
    conditions: Mapped[str] = mapped_column(nullable=False)
    notes: Mapped[str] = mapped_column(nullable=False)
    actif: Mapped[bool] = mapped_column(nullable=False)
    derniere_reussite: Mapped[datetime] = mapped_column(nullable=True)
    echecs_consecutifs: Mapped[int] = mapped_column(nullable=True)
    etag: Mapped[str] = mapped_column(nullable=True)
    last_modified: Mapped[datetime] = mapped_column(nullable=True)
