"""Serialize authority mutations with managed claims; legacy policy stays advisory."""

from models import Engagement


def begin_write(db):
    if db.get_bind().dialect.name != "sqlite":
        return
    connection = db.connection()
    driver = connection.connection.driver_connection
    transaction = db.get_transaction()
    if db.info.get("managed_sqlite_writer") is transaction and driver.in_transaction:
        return
    if driver.in_transaction:
        raise RuntimeError("unowned_sqlite_transaction")
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    db.info["managed_sqlite_writer"] = db.get_transaction()


def require_clean_issuer_session(db):
    if db.get_bind().dialect.name != "sqlite":
        return
    # Flushed data can leave empty ORM tracking sets. Check before independent
    # clock work or auth helpers; neither may commit/discard caller-owned data.
    connection = db.connection()
    if connection.connection.driver_connection.in_transaction or db.new or db.dirty or db.deleted:
        raise RuntimeError("clean_sqlite_issuer_session_required")


def lock(db, engagement):
    # Call before changing ORM state: autoflush must not precede the parent lock.
    begin_write(db)
    return (
        db.query(Engagement).filter_by(id=engagement.id).with_for_update().populate_existing().one()
    )


def advance(db, engagement):
    row = lock(db, engagement)
    row.managed_authority_revision += 1
    return row
