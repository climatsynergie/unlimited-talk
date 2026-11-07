"""Canonical signed incoming TwiML; every external Dial follows a committed offer."""
from datetime import timedelta
from uuid import UUID
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from twilio.twiml.voice_response import VoiceResponse
from app.identity.service import query
from app.identity.security import IDLE_SECONDS
from app.telephony.routes import signed_form
from app.telephony import incoming_runtime as runtime,incoming_state as state
from app.telephony.incoming_schema import installed
from app.telephony.twilio_voice import webhook_url,ManualVoiceProfile

router=APIRouter(prefix='/api/telephony/twilio')


def render(profile,decision):
    response=VoiceResponse();action=decision['action'];call=decision.get('call')
    if action=='answer':return str(response)
    if action=='hangup':response.hangup();return str(response)
    if action=='offer':
        offer=decision['offer'];identifier=offer['id']
        dial=response.dial(caller_id=call['called_number'],answer_on_bridge=True,timeout=decision['seconds'],time_limit=1800,
            action=webhook_url(profile,'incoming-dial-finish',identifier),method='POST',record='record-from-answer-dual',
            recording_status_callback=webhook_url(profile,'incoming-recording',call['id']),recording_status_callback_method='POST',
            recording_status_callback_event='completed absent')
        client=dial.client(url=webhook_url(profile,'incoming-agent-answer',identifier),method='POST',
            status_callback=webhook_url(profile,'incoming-agent-status',identifier),status_callback_method='POST',
            status_callback_event='initiated ringing answered completed')
        client.identity(offer['client_identity']);client.parameter(name='Offer',value=str(identifier))
        return str(response)
    if action=='voicemail':
        response.say('Tous nos agents sont actuellement indisponibles. Après le signal sonore, laissez votre nom, votre numéro et votre message. Nous vous rappellerons.',language='fr-CA',voice='Polly.Chantal')
        response.record(max_length=120,play_beep=True,trim='do-not-trim',finish_on_key='#',
            action=webhook_url(profile,'incoming-voicemail-finish',call['id']),method='POST',
            recording_status_callback=webhook_url(profile,'incoming-recording',call['id']),recording_status_callback_method='POST',
            recording_status_callback_event='completed absent')
        response.hangup();return str(response)
    if action=='initial':
        response.say('Bienvenue chez Unlimited Talks. Cet appel est enregistré. Nous vous mettons en relation avec notre équipe.',language='fr-CA',voice='Polly.Chantal')
    if action=='wait':response.play(profile.public_origin+'/assets/attente-b35f49d9e70c.wav')
    response.redirect(webhook_url(profile,'incoming-step',call['id']),method='POST')
    return str(response)


def answer(db,profile,identifier,params):
    pointer=query(db,'SELECT actor_id FROM staging.inbound_offers WHERE id=:id',id=identifier).scalar_one_or_none()
    if pointer is None:return False
    # Same actor -> account -> call -> offer order as outgoing admission.
    actor=query(db,'SELECT * FROM staging.identity_users WHERE id=:id FOR UPDATE',id=pointer).mappings().one()
    runtime.lock_account(db,profile)
    call,offer=state.lookup(db,profile,identifier,lock=True)
    if (params.get('ParentCallSid')!=call['parent_call_sid'] or params.get('From')!=call['called_number']
            or params.get('To')!='client:'+offer['client_identity']):return False
    state.bind_child(db,call,offer,params['CallSid'])
    now=query(db,'SELECT clock_timestamp()').scalar_one()
    registration=query(db,'SELECT * FROM staging.inbound_registrations WHERE id=:id',id=offer['registration_id']).mappings().one()
    live_session=query(db,'''SELECT 1 FROM staging.identity_sessions WHERE token_hash=:token AND user_id=:actor
        AND mfa_verified AND expires_at>clock_timestamp() AND last_seen_at>clock_timestamp()-make_interval(secs=>:idle)''',
        token=offer['session_hash'],actor=actor['id'],idle=IDLE_SECONDS).first()
    membership=query(db,'''SELECT q.offer_seconds FROM staging.inbound_queue_agents a JOIN staging.inbound_queues q ON q.id=a.queue_id
        WHERE a.user_id=:actor AND a.queue_id=:queue AND a.is_active AND q.is_active''',actor=actor['id'],queue=call['queue_id']).mappings().first()
    if (not actor['is_active'] or (actor['role']=='admin' and not actor['mfa_secret']) or not live_session or not membership
            or registration['closed_at'] or not registration['media_ready'] or registration['lease_until']<=now
            or registration['session_hash']!=offer['session_hash'] or offer['state'] not in {'accepted','connected'}
            or offer['accepted_at'] is None or offer['reject_requested_at'] or offer['terminal_at']
            or call['state'] not in {'offered','connected'} or call['current_offer_id']!=identifier
            or call['parent_terminal_at'] or (offer['state']!='connected' and now>offer['offered_at']+timedelta(seconds=membership['offer_seconds']+5))):
        return False
    # Repeating an empty whisper response for the SAME bound child cannot emit
    # another Dial. It also avoids dropping a bridge when its HTTP ack was lost.
    if offer['state']=='connected':return True
    query(db,"UPDATE staging.inbound_offers SET state='connected',connected_at=clock_timestamp() WHERE id=:id",id=identifier)
    query(db,"UPDATE staging.inbound_calls SET state='connected',agent_id=:actor,connected_at=clock_timestamp() WHERE id=:id",id=call['id'],actor=actor['id'])
    runtime.event(db,call['id'],'agent.connected',{'offer_id':str(identifier),'actor_id':str(actor['id'])})
    return True


def apply(request,profile,kind,identifier,params):
    with request.app.state.engine.begin() as db:
        if not installed(db) or not isinstance(profile,ManualVoiceProfile):
            raise HTTPException(503,'La réception des appels est indisponible.')
        if kind=='incoming':
            call=runtime.receive(db,profile,params)
            return {'action':'hangup' if call['state']=='finished' else 'initial','call':call}
        if kind=='incoming-step':
            return runtime.step(db,profile,identifier,params,enabled=getattr(request.app.state,'voice_calling_enabled',False))
        if kind=='incoming-agent-answer':
            return {'action':'answer' if answer(db,profile,identifier,params) else 'hangup'}
        if kind=='incoming-agent-status':state.child_status(db,profile,identifier,params)
        elif kind=='incoming-dial-finish':
            call=state.dial_finished(db,profile,identifier,params)
            return {'action':'hangup' if call['state']=='finished' else 'redirect','call':call}
        elif kind=='incoming-parent-status':state.parent_status(db,profile,params)
        elif kind=='incoming-recording':state.recording(db,profile,identifier,params)
        elif kind=='incoming-voicemail-finish':
            call=runtime.parent(db,profile,identifier,params,lock=True)
            if not call['voicemail_emitted_at']:raise HTTPException(403,'Aucun message vocal attendu pour cet appel.')
            state.finish_call(db,call)
        return {'action':'hangup'}


async def callback(request,kind,identifier=None):
    profile,params=await signed_form(request,kind,identifier)
    try:decision=await run_in_threadpool(apply,request,profile,kind,identifier,params)
    except IntegrityError:raise HTTPException(403,'Notification entrante incohérente.') from None
    return Response(render(profile,decision),media_type='application/xml')


@router.post('/incoming')
async def receive(request:Request):return await callback(request,'incoming')


@router.post('/incoming-parent-status')
async def parent_status(request:Request):return await callback(request,'incoming-parent-status')


@router.post('/incoming-step/{identifier}')
async def step(identifier:UUID,request:Request):return await callback(request,'incoming-step',identifier)


@router.post('/incoming-agent-answer/{identifier}')
async def agent_answer(identifier:UUID,request:Request):return await callback(request,'incoming-agent-answer',identifier)


@router.post('/incoming-agent-status/{identifier}')
async def agent_status(identifier:UUID,request:Request):return await callback(request,'incoming-agent-status',identifier)


@router.post('/incoming-dial-finish/{identifier}')
async def dial_finish(identifier:UUID,request:Request):return await callback(request,'incoming-dial-finish',identifier)


@router.post('/incoming-recording/{identifier}')
async def recording(identifier:UUID,request:Request):return await callback(request,'incoming-recording',identifier)


@router.post('/incoming-voicemail-finish/{identifier}')
async def voicemail_finish(identifier:UUID,request:Request):return await callback(request,'incoming-voicemail-finish',identifier)
