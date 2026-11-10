from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. No tables are defined yet -- Phase 0 only
    establishes connection/session infrastructure, per the approved scope
    (docs/04-DATABASE-DESIGN.md's tables arrive with Phase 1's migrations)."""
