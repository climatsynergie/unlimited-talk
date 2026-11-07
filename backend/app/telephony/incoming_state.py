"""Signed provider outcomes; browser cancellation never releases an uncertain offer."""
from fastapi import HTTPException
from app.identity.service import query
from app.telephony import service
from app.telephony.incoming_runtime import event,lock_account
from app.telephony.twilio_voice import sid


def lookup(db,profile,offer_id,*,lock=False):
    pointer=query(db,'SELECT call_id FROM staging.inbound_offers WHERE id=:id',id=offer_id).scalar_one_or_none()
    if pointer is None:raise HTTPException(403,'Proposition d’appel inconnue.')
    call=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id'+(' FOR UPDATE' if lock else ''),id=pointer).mappings().one()
    offer=query(db,'SELECT * FROM staging.inbound_offers WHERE id=:id'+(' FOR UPDATE' if lock else ''),id=offer_id).mappings().one()
    if call['account_sid']!=profile.account_sid:raise HTTPException(403,'Compte de réception incohérent.')
    return call,offer


def bind_child(db,call,offer,child):
    if not sid(child,'CA') or child==call['parent_call_sid'] or offer['child_call_sid'] not in (None,child):
        raise HTTPException(403,'Branche d’appel incohérente.')
    if offer['child_call_sid'] is None:
        query(db,'UPDATE staging.inbound_offers SET child_call_sid=:child WHERE id=:id',id=offer['id'],child=child)


def finish_offer(db,offer,outcome):
    query(db,'''UPDATE staging.inbound_offers SET state='finished',outcome=coalesce(outcome,:outcome),
        terminal_at=coalesce(terminal_at,clock_timestamp()),ended_at=coalesce(ended_at,clock_timestamp()) WHERE id=:id''',id=offer['id'],outcome=outcome)
    query(db,'UPDATE staging.inbound_registrations SET ready_since=clock_timestamp() WHERE id=:id',id=offer['registration_id'])


def finish_call(db,call,outcome=None,*,definitive=False):
    if call['state']=='finished':
        # The agent whisper can succeed just as the caller hangs up, before the
        # bridge actually forms. A later authoritative DialBridged=false
        # corrects a provisional completed-child inference, without reviving it.
        if definitive and call['outcome']=='answered' and outcome=='abandoned':
            query(db,"UPDATE staging.inbound_calls SET outcome='abandoned' WHERE id=:id",id=call['id'])
            event(db,call['id'],'finished.corrected',{'outcome':'abandoned','source':'dial'})
        return
    # A separate CRM settlement transaction creates the missed-call follow-up.
    # Never lock a contact or queue while holding account admission.
    if outcome is None:
        winner=query(db,'SELECT outcome FROM staging.inbound_offers WHERE id=:id',id=call['current_offer_id']).scalar_one_or_none() if call['current_offer_id'] else None
        outcome=call['outcome'] or ('answered' if call['connected_at'] and winner=='completed' else 'abandoned')
    query(db,"UPDATE staging.inbound_calls SET state='finished',outcome=:outcome,finished_at=clock_timestamp() WHERE id=:id",id=call['id'],outcome=outcome)
    event(db,call['id'],'finished',{'outcome':outcome})


def child_status(db,profile,identifier,params):
    lock_account(db,profile)
    call,offer=lookup(db,profile,identifier,lock=True)
    if (params.get('ParentCallSid')!=call['parent_call_sid'] or params.get('From')!=call['called_number']
            or params.get('To')!='client:'+offer['client_identity']):
        raise HTTPException(403,'Identité de branche entrante incohérente.')
    bind_child(db,call,offer,params['CallSid'])
    status=params.get('CallStatus')
    if status not in service.OUTCOMES|{'queued','initiated','ringing','in-progress'}:
        raise HTTPException(400,'Statut d’appel invalide.')
    sequence=service.integer(params.get('SequenceNumber'),2147483647)
    if sequence<=offer['last_sequence']:return
    query(db,'UPDATE staging.inbound_offers SET last_sequence=:sequence WHERE id=:id',id=identifier,sequence=sequence)
    event(db,call['id'],'agent.status',{'offer_id':str(identifier),'status':status,'sequence':sequence})
    if offer['state']=='finished' or status not in service.OUTCOMES:return
    duration=service.integer(params['CallDuration'],1800) if 'CallDuration' in params else None
    query(db,'''UPDATE staging.inbound_offers SET terminal_at=coalesce(terminal_at,clock_timestamp()),
        outcome=:outcome,duration_seconds=coalesce(:duration,duration_seconds) WHERE id=:id''',id=identifier,outcome=status,duration=duration)
    if call['connected_at'] and call['current_offer_id']==identifier and not call['parent_terminal_at'] and call['state']!='finished':
        return
    finish_offer(db,offer,status)
    if call['parent_terminal_at'] or call['state']=='finished':
        if not query(db,"SELECT 1 FROM staging.inbound_offers WHERE call_id=:id AND state<>'finished' LIMIT 1",id=call['id']).first():finish_call(db,call)
    elif call['state']=='offered' and call['current_offer_id']==identifier:
        query(db,"UPDATE staging.inbound_calls SET state='waiting',current_offer_id=NULL WHERE id=:id",id=call['id'])


def dial_finished(db,profile,identifier,params):
    lock_account(db,profile)
    call,offer=lookup(db,profile,identifier,lock=True)
    if params['CallSid']!=call['parent_call_sid']:raise HTTPException(403,'Appel parent incohérent.')
    child=params.get('DialCallSid')
    if child:bind_child(db,call,offer,child)
    elif offer['child_call_sid'] is not None:raise HTTPException(403,'Branche d’appel manquante.')
    status=params.get('DialCallStatus')
    if status not in service.OUTCOMES:raise HTTPException(400,'Résultat de sonnerie invalide.')
    details={'offer_id':str(identifier),'status':status,'bridged':params.get('DialBridged')}
    previous=query(db,'''SELECT details FROM staging.inbound_call_events WHERE call_id=:call
        AND kind='agent.dial_result' AND details->>'offer_id'=:offer LIMIT 1''',call=call['id'],offer=str(identifier)).scalar_one_or_none()
    if previous is not None and previous!=details:raise HTTPException(403,'Résultat de liaison incohérent.')
    event(db,call['id'],'agent.dial_result',details)
    if offer['state']=='finished':
        if call['connected_at'] and call['current_offer_id']==identifier:
            finish_call(db,call,'answered' if status=='completed' and params.get('DialBridged')!='false' else 'abandoned',definitive=True)
        return dict(query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id',id=call['id']).mappings().one())
    duration=service.integer(params['DialCallDuration'],1800) if 'DialCallDuration' in params else None
    query(db,'UPDATE staging.inbound_offers SET outcome=:outcome,duration_seconds=coalesce(:duration,duration_seconds) WHERE id=:id',id=identifier,outcome=status,duration=duration)
    finish_offer(db,offer,status)
    event(db,call['id'],'agent.finished',{'offer_id':str(identifier),'outcome':status})
    if call['state']=='finished':return dict(call)
    if call['connected_at'] and call['current_offer_id']==identifier:
        finish_call(db,call,'answered' if status=='completed' and params.get('DialBridged')!='false' else 'abandoned')
    elif call['parent_terminal_at']:finish_call(db,call)
    elif call['state']=='offered' and call['current_offer_id']==identifier:
        query(db,"UPDATE staging.inbound_calls SET state='waiting',current_offer_id=NULL WHERE id=:id",id=call['id'])
    return dict(query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id',id=call['id']).mappings().one())


def parent_status(db,profile,params):
    lock_account(db,profile)
    call=query(db,'SELECT * FROM staging.inbound_calls WHERE account_sid=:account AND parent_call_sid=:sid FOR UPDATE',account=profile.account_sid,sid=params['CallSid']).mappings().first()
    if call is None:
        if params.get('CallStatus') not in service.OUTCOMES:return
        from app.telephony.incoming_runtime import receive
        call=receive(db,profile,params,verified_voice=False)
        # The initial voice request may have failed before persistence. The
        # signed terminal callback still preserves a missed-call follow-up.
        elapsed=service.integer(params.get('CallDuration','0'),86400)
        query(db,"UPDATE staging.inbound_calls SET received_at=clock_timestamp()-make_interval(secs=>:seconds) WHERE id=:id",id=call['id'],seconds=elapsed)
        event(db,call['id'],'received.recovered',{'time_estimated':True})
        call=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id FOR UPDATE',id=call['id']).mappings().one()
    binding=service.fingerprint(dict(account=profile.account_sid,parent=params['CallSid'],caller=params.get('From',''),called=params.get('To','')))
    if binding!=call['caller_fingerprint'] or params.get('Direction','inbound')!='inbound':
        raise HTTPException(403,'Identité d’appel entrant incohérente.')
    status=params.get('CallStatus')
    if status not in service.OUTCOMES:return
    query(db,'UPDATE staging.inbound_calls SET parent_terminal_at=coalesce(parent_terminal_at,clock_timestamp()) WHERE id=:id',id=call['id'])
    # An unknown child stays reserved until a signed terminal event or provider
    # reconciliation proves its end. Presence expiry is never that proof.
    offers=query(db,"SELECT * FROM staging.inbound_offers WHERE call_id=:id AND state<>'finished' ORDER BY id FOR UPDATE",id=call['id']).mappings().all()
    for offer in offers:
        if offer['terminal_at']:finish_offer(db,offer,offer['outcome'] or 'canceled')
    if not any(offer['terminal_at'] is None for offer in offers):finish_call(db,call)


def recording(db,profile,identifier,params):
    call=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id FOR UPDATE',id=identifier).mappings().first()
    if not call or call['account_sid']!=profile.account_sid or call['parent_call_sid']!=params['CallSid']:
        raise HTTPException(403,'Enregistrement sans appel entrant associé.')
    if params.get('RecordingStatus') in {'absent','failed'}:
        event(db,identifier,'recording.unavailable',{'status':params['RecordingStatus']});return
    if params.get('RecordingStatus')!='completed' or not sid(params.get('RecordingSid'),'RE'):
        raise HTTPException(400,'Enregistrement entrant invalide.')
    source=params.get('RecordingSource');channels=service.integer(params.get('RecordingChannels'),2)
    if source=='RecordVerb' and call['voicemail_emitted_at'] and channels==1:
        kind='voicemail';offer_id=None;maximum=120
    elif source=='DialVerb' and call['current_offer_id'] and call['connected_at'] and channels==2:
        kind='conversation';offer_id=call['current_offer_id'];maximum=1800
    else:raise HTTPException(403,'Source d’enregistrement incohérente.')
    duration=service.integer(params.get('RecordingDuration'),maximum)
    old=query(db,'SELECT * FROM staging.inbound_recordings WHERE sid=:sid',sid=params['RecordingSid']).mappings().first()
    binding=dict(call_id=identifier,offer_id=offer_id,call_sid=call['parent_call_sid'],kind=kind,duration=duration,channels=channels)
    if old:
        if any(old[key]!=value for key,value in binding.items()):raise HTTPException(403,'Enregistrement déjà associé à un autre appel.')
        return
    query(db,'''INSERT INTO staging.inbound_recordings(sid,call_id,offer_id,call_sid,kind,duration,channels)
        VALUES (:sid,:call_id,:offer_id,:call_sid,:kind,:duration,:channels)''',sid=params['RecordingSid'],**binding)
    query(db,'INSERT INTO staging.inbound_archive_jobs(recording_sid) VALUES (:sid)',sid=params['RecordingSid'])
    event(db,identifier,'recording.ready',{'recording_sid':params['RecordingSid'],'kind':kind})
