"""One bounded aggregate query; reservations and cancelled preparations are not calls."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from app.identity.service import query

COUNTERS = ('calls','answered','voicemail','no_answer','busy','failed','cancelled','in_progress','manual','automatic',
            'contacts','bookings','cancelled_bookings','pauses','stops','starts','automatic_pauses',
            'talk_seconds','duration_known','duration_missing','incoming_calls','incoming_answered','incoming_talk_seconds')

@dataclass(frozen=True)
class Period:
    start: date
    end: date
    zone: str

    def bounds(self):
        try: zone=ZoneInfo(self.zone)
        except (ValueError,ZoneInfoNotFoundError):raise HTTPException(422,'Fuseau horaire invalide.') from None
        if self.start.year<2000:
            raise HTTPException(422,'Les rapports commencent au 1er janvier 2000.')
        if self.end<self.start or self.end>datetime.now(zone).date():
            raise HTTPException(422,'Choisissez des dates passées ou la date du jour, dans l’ordre chronologique.')
        shifted=self.start.month+2
        year=self.start.year+shifted//12;month=shifted%12+1
        limit=date(year,month,min(self.start.day,monthrange(year,month)[1]))
        if self.end>limit:
            raise HTTPException(422,'Choisissez une période de trois mois maximum, avec une fin après le début.')
        return datetime.combine(self.start,time.min,zone).astimezone(timezone.utc),datetime.combine(self.end+timedelta(days=1),time.min,zone).astimezone(timezone.utc)


def agents(db, since, until, *, include_incoming=False):
    return [dict(row) for row in query(db,'''SELECT u.id,u.display_name,u.email,u.role,u.is_active
        FROM staging.identity_users u WHERE u.role='agent'
        OR EXISTS(SELECT 1 FROM staging.voice_intents i WHERE i.actor_id=u.id AND i.consumed_at>=:since AND i.consumed_at<:until)
        OR EXISTS(SELECT 1 FROM staging.appointments a WHERE a.created_by=u.id AND a.created_at>=:since AND a.created_at<:until)
        '''+(" OR EXISTS(SELECT 1 FROM staging.inbound_offers o WHERE o.actor_id=u.id AND o.offered_at>=:since AND o.offered_at<:until)" if include_incoming else '')+'''
        ORDER BY lower(u.display_name),u.id''',since=since,until=until).mappings()]


AGGREGATE = '''WITH chosen_calls AS MATERIALIZED (
 SELECT i.id,i.actor_id,i.consumed_at,i.destination,i.outcome,i.state,i.dialer_generation
 FROM staging.voice_intents i WHERE i.actor_id=ANY(CAST(:actors AS uuid[]))
 AND i.consumed_at>=:since AND i.consumed_at<:until
), recorded AS (
 SELECT r.intent_id,max(r.duration) AS seconds FROM staging.voice_recordings r
 JOIN chosen_calls i ON i.id=r.intent_id GROUP BY r.intent_id
), progress AS (
 SELECT e.intent_id,bool_or(e.kind='status' AND e.details->>'status'='in-progress') AS answered,
 bool_or(e.kind='disposition.voicemail') AS voicemail,
 max(CASE WHEN e.kind='status' AND e.details->>'status'='completed' THEN
   CASE WHEN e.details->>'duration_seconds' ~ '^[0-9]{1,5}$' THEN
    CASE WHEN (e.details->>'duration_seconds')::integer<=86400
     THEN (e.details->>'duration_seconds')::integer END END END) AS seconds
 FROM staging.voice_events e JOIN chosen_calls i ON i.id=e.intent_id GROUP BY e.intent_id
), __INCOMING_CTES__ facts AS (
 SELECT i.actor_id,i.consumed_at AS at,'call' AS kind,i.destination,i.outcome,
 i.state IN ('authorized','ringing','answered') AS ongoing,i.dialer_generation IS NOT NULL AS automatic,
 ((i.outcome='completed' OR i.state='answered' OR coalesce(p.answered,false) OR coalesce(r.seconds,0)>0) AND NOT coalesce(p.voicemail,false)) AS answered,
 coalesce(p.seconds,r.seconds) AS seconds,false AS cancelled_booking,coalesce(p.voicemail,false) AS voicemail
 FROM chosen_calls i LEFT JOIN progress p ON p.intent_id=i.id LEFT JOIN recorded r ON r.intent_id=i.id
 UNION ALL
 SELECT a.created_by,a.created_at,'booking',NULL,NULL,false,false,false,NULL,a.status='cancelled',false
 FROM staging.appointments a WHERE a.created_by=ANY(CAST(:actors AS uuid[])) AND a.created_at>=:since AND a.created_at<:until
 UNION ALL
 SELECT a.actor_id,a.created_at,a.action,NULL,NULL,false,false,false,NULL,false,false
 FROM staging.identity_audit a WHERE a.actor_id=ANY(CAST(:actors AS uuid[])) AND a.created_at>=:since AND a.created_at<:until
 AND a.action IN ('dialer.pause','dialer.stop','dialer.start','dialer.pause_automatic')
 __INCOMING_FACTS__
), buckets AS (
 SELECT *,(at AT TIME ZONE :zone)::date AS day,
 date_bin(interval '1 hour',at,CAST(:since AS timestamptz)) AS hour FROM facts
)
SELECT actor_id,CASE WHEN grouping(actor_id)=1 THEN 'global' WHEN grouping(day)=0 THEN 'day' __HOUR_CASE__ ELSE 'total' END AS grain,
 day::text AS day,__HOUR_VALUE__,
 count(*) FILTER(WHERE kind='call') AS calls,
 count(*) FILTER(WHERE kind='call' AND answered) AS answered,
 count(*) FILTER(WHERE kind='call' AND voicemail) AS voicemail,
 count(*) FILTER(WHERE kind='call' AND outcome='no-answer') AS no_answer,
 count(*) FILTER(WHERE kind='call' AND outcome='busy') AS busy,
 count(*) FILTER(WHERE kind='call' AND outcome='failed') AS failed,
 count(*) FILTER(WHERE kind='call' AND outcome='canceled') AS cancelled,
 count(*) FILTER(WHERE kind='call' AND ongoing) AS in_progress,
 count(*) FILTER(WHERE kind='call' AND NOT automatic) AS manual,
 count(*) FILTER(WHERE kind='call' AND automatic) AS automatic,
 count(DISTINCT destination) FILTER(WHERE kind='call') AS contacts,
 count(*) FILTER(WHERE kind='booking') AS bookings,
 count(*) FILTER(WHERE kind='booking' AND cancelled_booking) AS cancelled_bookings,
 count(*) FILTER(WHERE kind='dialer.pause') AS pauses,
 count(*) FILTER(WHERE kind='dialer.stop') AS stops,
 count(*) FILTER(WHERE kind='dialer.start') AS starts,
 count(*) FILTER(WHERE kind='dialer.pause_automatic') AS automatic_pauses,
 coalesce(sum(seconds) FILTER(WHERE kind='call' AND answered),0) AS talk_seconds,
 count(*) FILTER(WHERE kind='call' AND answered AND seconds IS NOT NULL) AS duration_known,
 count(*) FILTER(WHERE kind='call' AND answered AND seconds IS NULL) AS duration_missing,
 count(*) FILTER(WHERE kind='incoming') AS incoming_calls,
 count(*) FILTER(WHERE kind='incoming' AND answered) AS incoming_answered,
 coalesce(sum(seconds) FILTER(WHERE kind='incoming' AND answered),0) AS incoming_talk_seconds,
 min(at) FILTER(WHERE kind='call') AS first_call_at,max(at) FILTER(WHERE kind='call') AS last_call_at
FROM buckets GROUP BY GROUPING SETS ((),(actor_id),(actor_id,day)__HOUR_GROUP__)
'''


INCOMING_CTES = """chosen_incoming AS MATERIALIZED (
 SELECT o.id,o.actor_id,o.offered_at,o.outcome,o.connected_at,o.duration_seconds
 FROM staging.inbound_offers o WHERE o.actor_id=ANY(CAST(:actors AS uuid[]))
 AND o.offered_at>=:since AND o.offered_at<:until
), incoming_recorded AS (
 SELECT r.offer_id,max(r.duration) AS seconds FROM staging.inbound_recordings r
 JOIN chosen_incoming o ON o.id=r.offer_id WHERE r.kind='conversation' GROUP BY r.offer_id
), """

INCOMING_FACTS = """UNION ALL
 SELECT o.actor_id,o.offered_at,'incoming',NULL,o.outcome,false,false,
 o.connected_at IS NOT NULL,coalesce(o.duration_seconds,r.seconds),false,false
 FROM chosen_incoming o LEFT JOIN incoming_recorded r ON r.offer_id=o.id
"""


def metrics(row=None):
    result={key:int((row or {}).get(key) or 0) for key in COUNTERS}
    result.update({key:(row or {}).get(key) for key in ('first_call_at','last_call_at')})
    result['answer_rate']=round(result['answered']*100/result['calls'],1) if result['calls'] else None
    result['bookings_per_100_calls']=round(result['bookings']*100/result['calls'],1) if result['calls'] else None
    result['average_talk_seconds']=round(result['talk_seconds']/result['duration_known']) if result['duration_known'] else None
    return result


def report(db,period,agent_id=None):
    since,until=period.bounds()
    from app.telephony.incoming_schema import installed
    include_incoming=installed(db)
    roster=agents(db,since,until,include_incoming=include_incoming)
    if agent_id is not None:
        roster=[dict(row) for row in query(db,'SELECT id,display_name,email,role,is_active FROM staging.identity_users WHERE id=:id',id=agent_id).mappings()]
        if not roster:raise HTTPException(404,'Agent introuvable.')
    # All metrics derive from the same PostgreSQL statement snapshot.
    query(db,"SET LOCAL statement_timeout='15s'")
    # Team views only need daily aggregates. Hour buckets are requested for a
    # single selected agent, keeping three-month responses and exports bounded.
    sql=(AGGREGATE.replace('__INCOMING_CTES__',INCOMING_CTES if include_incoming else '').replace('__INCOMING_FACTS__',INCOMING_FACTS if include_incoming else '').replace('__HOUR_CASE__',"WHEN grouping(hour)=0 THEN 'hour'" if agent_id else '')
        .replace('__HOUR_VALUE__','hour' if agent_id else 'NULL::timestamptz AS hour')
        .replace('__HOUR_GROUP__',',(actor_id,hour)' if agent_id else ''))
    rows=list(query(db,sql,actors=[str(agent['id']) for agent in roster],since=since,until=until,zone=period.zone).mappings()) if roster else []
    totals={str(row['actor_id']):metrics(row) for row in rows if row['grain']=='total'}
    daily={(str(row['actor_id']),row['day']):metrics(row) for row in rows if row['grain']=='day'}
    dates=[];day=period.start
    while day<=period.end:
        dates.append(day.isoformat());day+=timedelta(days=1)
    summaries=[{**agent,'metrics':totals.get(str(agent['id']),metrics())} for agent in roster]
    days=[dict(agent_id=str(agent['id']),date=day,**daily.get((str(agent['id']),day),metrics())) for agent in roster for day in dates]
    hours=[]
    if agent_id is not None:
        hour_rows={row['hour']:row for row in rows if row['grain']=='hour'}
        bucket=since
        while bucket<until:
            local=bucket.astimezone(ZoneInfo(period.zone))
            hours.append(dict(starts_at=bucket,date=local.date().isoformat(),label=local.strftime('%H:%M'),
                utc_offset=local.strftime('%z'),**metrics(hour_rows.get(bucket))))
            bucket+=timedelta(hours=1)
    combined=metrics(next((row for row in rows if row['grain']=='global'),None))
    return dict(period=dict(start=period.start,end=period.end,timezone=period.zone),generated_at=datetime.now(timezone.utc),
        agents=summaries,daily=days,hourly=hours,totals=combined,
        definitions={
            'calls':'Appels lancés : réservations effectivement autorisées par Twilio ; les préparations annulées sont exclues.',
            'answered':'Connexions téléphoniques établies, hors boîtes vocales signalées par les agents. Une boîte vocale non signalée ne peut pas être reconnue automatiquement.',
            'voicemail':'Boîtes vocales signalées par les agents ; une seule par appel, exclue des décrochés clients et des durées de conversation.',
            'talk':'Durée fournisseur, sinon durée de l’enregistrement, hors boîtes vocales signalées. Une durée absente reste inconnue.',
            'incoming':'Appels entrants proposés aux agents, attribués à leur heure de présentation. Chaque agent sollicité compte une proposition ; les décrochés et durées connues sont indiqués séparément des appels sortants. Les appels restés dans la file sans agent ne sont pas attribués.',
            'bookings':'RDV comptés à leur création, au nom de leur créateur ; les annulations indiquent le statut actuel.',
            'pauses':'Actions de pause et d’arrêt journalisées. Des pauses automatiques peuvent être incluses dans les anciens journaux.',
            'time':'Appels attribués à leur heure de lancement, durées à leur appel d’origine. Présence récente ≠ temps travaillé.'})


def live(db):
    from app.telephony.incoming_schema import installed
    include_incoming=installed(db)
    rows=query(db,'''SELECT u.id,u.display_name,u.email,u.role,u.is_active,
        seen.last_seen_at,coalesce(u.is_active AND seen.last_seen_at>clock_timestamp()-interval '90 seconds',false) AS online,
        d.mode AS dialer_mode,d.lease_until>clock_timestamp() AS dialer_alive,c.name AS campaign_name,
        i.id AS call_id,i.state AS call_state,i.destination,i.consumed_at,i.created_at AS call_created_at
        FROM staging.identity_users u
        LEFT JOIN LATERAL(SELECT max(s.last_seen_at) AS last_seen_at FROM staging.identity_sessions s
          WHERE s.user_id=u.id AND s.mfa_verified AND s.expires_at>clock_timestamp()) seen ON true
        LEFT JOIN staging.voice_dialer_sessions d ON d.actor_id=u.id
        LEFT JOIN staging.campaigns c ON c.id=d.campaign_id
        LEFT JOIN LATERAL(SELECT id,state,destination,consumed_at,created_at FROM staging.voice_intents v WHERE v.actor_id=u.id
          AND v.state IN ('reserved','authorized','ringing','answered') AND (v.state<>'reserved' OR v.expires_at>clock_timestamp())
          ORDER BY v.created_at DESC LIMIT 1) i ON true
        WHERE u.role='agent' OR i.id IS NOT NULL
        '''+(" OR EXISTS(SELECT 1 FROM staging.inbound_offers o WHERE o.actor_id=u.id AND o.state<>'finished')" if include_incoming else '')+'''
        ORDER BY lower(u.display_name),u.id''').mappings().all()
    reception={}
    if include_incoming:
        reception={row['actor_id']:row for row in query(db,'''SELECT o.actor_id,o.id AS call_id,o.state AS call_state,
            c.caller_number AS destination,c.connected_at AS consumed_at,o.offered_at AS call_created_at,
            q.name AS campaign_name FROM staging.inbound_offers o JOIN staging.inbound_calls c ON c.id=o.call_id
            JOIN staging.inbound_queues q ON q.id=c.queue_id WHERE o.state<>'finished'
            ''').mappings()}
    items=[]
    for row in rows:
        item=dict(row)
        incoming=reception.get(row['id'])
        if incoming:
            item.update(incoming);item['call_state']='answered' if incoming['call_state']=='connected' else 'ringing'
        item['direction']='incoming' if incoming else 'outgoing' if item['call_id'] else None
        row=item
        item['status']=('connected' if row['call_state']=='answered' else 'calling') if row['call_id'] else (
            'offline' if not row['online'] else 'booking' if row['dialer_mode']=='booking' and row['dialer_alive'] else
            'dialing' if row['dialer_mode']=='running' and row['dialer_alive'] else
            'paused' if row['dialer_mode']=='paused' else 'available')
        items.append(item)
    priority={name:index for index,name in enumerate(('connected','calling','dialing','booking','paused','available','offline'))}
    items.sort(key=lambda item:(priority[item['status']],item['display_name'].casefold(),str(item['id'])))
    return dict(generated_at=datetime.now(timezone.utc),items=items,online=sum(item['online'] for item in items),
        in_calls=sum(item['call_id'] is not None for item in items),connected=sum(item['status']=='connected' for item in items),
        paused=sum(item['status']=='paused' for item in items))
