"""Read-only calendar context for already-authorized call/contact histories.

The calendar is shared with authenticated users. Match the canonical phone,
never infer that a particular call created a booking. Return only the most
recently created appointment, with its current lifecycle and phase.
"""
from app.identity.service import query
from app.calendar.phases import PHASE_SQL


def enrich(db, items, *, phone_key):
    phones = list({row.get(phone_key) for row in items if row.get(phone_key)})
    appointments = {}
    if phones:
        rows = query(db, '''SELECT c.phone, found.* FROM staging.contacts c
            CROSS JOIN LATERAL (
                SELECT a.id,a.created_at,a.starts_at,a.ends_at,a.timezone,a.status,a.notes,
                    '''+PHASE_SQL+''' AS phase,ca.name AS campaign_name,u.display_name AS creator_name
                FROM staging.appointments a
                JOIN staging.campaigns ca ON ca.id=a.campaign_id
                JOIN staging.identity_users u ON u.id=a.created_by
                LEFT JOIN LATERAL (SELECT e.details FROM staging.appointment_events e
                    WHERE e.appointment_id=a.id AND e.action IN ('appointment.created','appointment.updated')
                    ORDER BY e.id DESC LIMIT 1) latest ON true
                WHERE a.contact_id=c.id ORDER BY a.created_at DESC,a.id DESC LIMIT 1
            ) found WHERE c.phone=ANY(CAST(:phones AS text[]))''', phones=phones).mappings()
        appointments = {row['phone']: {key: value for key, value in row.items() if key != 'phone'} for row in rows}
    return [dict(row, client_appointment=appointments.get(row.get(phone_key))) for row in items]
