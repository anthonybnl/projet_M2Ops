from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from la_gazette_des_sorciers.database.db_models import Sources


def create_source(session: Session, **fields: Any) -> Sources:
    source = Sources(**fields)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def get_source(session: Session, source_id: str) -> Sources | None:
    return session.get(Sources, source_id)


def list_sources(session: Session, actif: bool | None = None) -> list[Sources]:
    stmt = select(Sources).order_by(Sources.id)
    if actif is not None:
        stmt = stmt.where(Sources.actif == actif)
    return list(session.scalars(stmt))


def update_source(session: Session, source_id: str, **fields: Any) -> Sources | None:
    source = session.get(Sources, source_id)
    if source is None:
        return None
    for key, value in fields.items():
        setattr(source, key, value)
    session.commit()
    session.refresh(source)
    return source


def delete_source(session: Session, source_id: str) -> bool:
    source = session.get(Sources, source_id)
    if source is None:
        return False
    session.delete(source)
    session.commit()
    return True


def upsert_sources(
    session: Session,
    rows: Iterable[Mapping[str, Any]],
    update_columns: Iterable[str],
) -> int:
    """Insère ou met à jour les lignes sur `id`"""
    rows = list(rows)
    if not rows:
        return 0
    stmt = insert(Sources).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Sources.id],
        set_={col: stmt.excluded[col] for col in update_columns},
    )
    session.execute(stmt)
    session.commit()
    return len(rows)
