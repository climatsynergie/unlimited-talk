"""Bounded, read-only provider reconciliation for incoming calls and uncertain offers."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from urllib.parse import urlencode
from app.identity.service import query
from app.telephony import service
from app.telephony.incoming_schema import installed
from app.telephony.incoming_runtime import event,lock_account
from app.telephony.incoming_state import bind_child,finish_offer,finish_call
from app.telephony.reconciliation import configured_provider,ProviderReadError,KNOWN_STATUSES,ERROR_REASONS
from app.telephony.twilio_voice import sid


def duration(value):
    if isinstance(value,str) and value.isascii() and value.isdecimal() and len(value)<=5 and int(value)<=1800:
        return int(value)
    return None


def observe(provider,snapshot):
    call,offers=snapshot['call'],snapshot['offers']
    listing=provider._get('/Calls.json?'+urlencode({'ParentCallSid':call['parent_call_sid'],'PageSize':21}))
    children=listing.get('calls')
    if not isinstance(children,list) or len(children)>20 or listing.get('next_page_uri','missing') not in (None,''):
        raise ProviderReadError('provider_children_ambiguous')
    by_identity={offer['client_identity']:offer for offer in offers}
    found={}
    def validate(child,expected=None):
        if (not isinstance(child,dict) or not sid(child.get('sid'),'CA') or child['sid']==call['parent_call_sid']
                or child.get('account_sid')!=call['account_sid'] or child.get('parent_call_sid')!=call['parent_call_sid']
                or child.get('direction')!='outbound-dial' or child.get('from')!=call['called_number']
                or child.get('status') not in KNOWN_STATUSES or not isinstance(child.get('to'),str)
                or not child['to'].startswith('client:')):
            raise ProviderReadError('provider_child_mismatch')
        offer=by_identity.get(child['to'].removeprefix('client:'))
        if not offer or (expected is not None and child['sid']!=expected) or offer['child_call_sid'] not in (None,child['sid']):
            raise ProviderReadError('provider_child_mismatch')
        previous=found.get(offer['id'])
        if previous and previous['sid']!=child['sid']:raise ProviderReadError('provider_children_ambiguous')
        found[offer['id']]=child
    for child in children:validate(child)
    # A known child is read directly even when a list temporarily omits it.
    for offer in offers:
        if offer['state']=='finished':continue
        child=found.get(offer['id']);identifier=offer['child_call_sid'] or (child['sid'] if child else None)
        if identifier:validate(provider._get('/Calls/'+identifier+'.json'),identifier)
    parent=provider._get('/Calls/'+call['parent_call_sid']+'.json')
    fingerprint=service.fingerprint(dict(account=call['account_sid'],parent=call['parent_call_sid'],caller=parent.get('from',''),called=parent.get('to','')))
    if (parent.get('sid')!=call['parent_call_sid'] or parent.get('account_sid')!=call['account_sid']
            or parent.get('direction')!='inbound' or fingerprint!=call['caller_fingerprint'] or parent.get('status') not in KNOWN_STATUSES):
        raise ProviderReadError('provider_parent_mismatch')
    return {'call':call,'offers':offers,'parent_status':parent['status'],'children':found}


def apply(engine,profile,observation):
    expected=observation['call']
    with engine.begin() as db:
        lock_account(db,profile)
        call=query(db,'SELECT * FROM staging.inbound_calls WHERE id=:id FOR UPDATE',id=expected['id']).mappings().one()
        offers=query(db,'SELECT * FROM staging.inbound_offers WHERE call_id=:id ORDER BY id FOR UPDATE',id=expected['id']).mappings().all()
        if (call['account_sid']!=profile.account_sid or any(call[key]!=expected[key] for key in ('parent_call_sid','caller_fingerprint','called_number'))
                or {offer['id'] for offer in offers}!={offer['id'] for offer in observation['offers']}):return 'stale'
        children=observation['children']
        if any(offer['child_call_sid'] not in (None,children[offer['id']]['sid'] if offer['id'] in children else None)
                for offer in offers if offer['state']!='finished'):return 'stale'
        parent_ended=observation['parent_status'] in service.OUTCOMES or call['parent_terminal_at'] is not None or call['state']=='finished'
        if observation['parent_status'] in service.OUTCOMES:
            query(db,'UPDATE staging.inbound_calls SET parent_terminal_at=coalesce(parent_terminal_at,clock_timestamp()) WHERE id=:id',id=call['id'])
        for offer in offers:
            if offer['state']=='finished':continue
            child=children.get(offer['id'])
            if child:
                bind_child(db,call,offer,child['sid'])
                terminal=child['status'] in service.OUTCOMES
                if terminal:
                    query(db,'''UPDATE staging.inbound_offers SET terminal_at=coalesce(terminal_at,clock_timestamp()),
                        outcome=:outcome,duration_seconds=coalesce(:duration,duration_seconds) WHERE id=:id''',
                        id=offer['id'],outcome=child['status'],duration=duration(child.get('duration')))
                connected=call['connected_at'] is not None and call['current_offer_id']==offer['id']
                if terminal and (parent_ended or not connected):
                    finish_offer(db,offer,child['status'])
                    if not parent_ended and call['state']=='offered' and call['current_offer_id']==offer['id']:
                        query(db,"UPDATE staging.inbound_calls SET state='waiting',current_offer_id=NULL WHERE id=:id",id=call['id'])
            elif parent_ended:
                # The complete, bounded provider child list confirms no child
                # exists for this offer. No local timeout makes this decision.
                finish_offer(db,offer,'canceled')
        active=query(db,"SELECT 1 FROM staging.inbound_offers WHERE call_id=:id AND state<>'finished' LIMIT 1",id=call['id']).first()
        if parent_ended and not active:
            winner=children.get(call['current_offer_id'])
            outcome=call['outcome'] or ('answered' if call['connected_at'] and winner and winner['status']=='completed' else 'abandoned')
            finish_call(db,call,outcome)
        query(db,'UPDATE staging.inbound_calls SET reconciled_at=clock_timestamp() WHERE id=:id',id=call['id'])
        event(db,call['id'],'recovery.observed',{'parent_status':observation['parent_status'],
            'children':{str(identifier):child['status'] for identifier,child in children.items()}})
    return 'checked'


def process_once(engine,profile,provider=None):
    result={'checked':0,'failed':0,'stale':0}
    if profile is None:return result
    with engine.connect() as db:
        if not installed(db):return result
        rows=query(db,'''SELECT * FROM staging.inbound_calls c WHERE account_sid=:account
            AND (state<>'finished' OR EXISTS(SELECT 1 FROM staging.inbound_offers o WHERE o.call_id=c.id AND o.state<>'finished'))
            AND received_at<clock_timestamp()-interval '10 seconds'
            AND (reconciled_at IS NULL OR reconciled_at<clock_timestamp()-interval '10 seconds')
            ORDER BY reconciled_at NULLS FIRST,received_at,id LIMIT 20''',account=profile.account_sid).mappings().all()
        snapshots=[{'call':dict(row),'offers':[dict(offer) for offer in query(db,'SELECT * FROM staging.inbound_offers WHERE call_id=:id',id=row['id']).mappings()]} for row in rows]
    if not snapshots:return result
    provider=provider or configured_provider(profile)
    with ThreadPoolExecutor(max_workers=4) as executor:
        reads={executor.submit(observe,provider,snapshot):snapshot['call']['id'] for snapshot in snapshots}
        for future in as_completed(reads):
            identifier=reads[future]
            try:
                status=apply(engine,profile,future.result())
                result['stale' if status=='stale' else 'checked']+=1
            except Exception as error:
                reason=error.args[0] if isinstance(error,ProviderReadError) and error.args else 'unexpected_error'
                if reason not in ERROR_REASONS:reason='unexpected_error'
                # Fair retry ordering: a failing old call must not starve newer
                # calls. Its media reservation remains occupied throughout.
                with engine.begin() as db:
                    query(db,'UPDATE staging.inbound_calls SET reconciled_at=clock_timestamp() WHERE id=:id',id=identifier)
                    event(db,identifier,'recovery.failed',{'reason':reason})
                result['failed']+=1
    return result
