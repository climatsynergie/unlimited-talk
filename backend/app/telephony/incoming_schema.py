"""Shared admission also works on the preceding schema-11 compatibility image."""
from app.identity.service import query

TABLES=('inbound_lines','inbound_registrations','inbound_calls','inbound_offers',
        'inbound_call_events','inbound_recordings','inbound_archive_jobs')


def installed(db):
    return query(db,"SELECT to_regclass('staging.inbound_offers') IS NOT NULL").scalar_one()


def occupancy(db,account,actor):
    if not installed(db):return {'total':0,'actor_busy':False}
    return query(db,'''SELECT count(*) FILTER(WHERE c.account_sid=:account) AS total,
        coalesce(bool_or(o.actor_id=:actor),false) AS actor_busy
        FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id
        WHERE o.state<>'finished' ''',account=account,actor=actor).mappings().one()
