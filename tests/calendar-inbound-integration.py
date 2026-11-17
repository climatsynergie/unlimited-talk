from urllib.parse import urlencode
from app.telephony import inbound_service

class CalendarInboundTests(BackendReconfirmationTests):
    def setUp(self):
        super().setUp()
        with engine.connect() as db:
            self.queue_phone=next('+1800555'+str(n) for n in range(1000,9999) if not query(db,'SELECT 1 FROM staging.inbound_queues WHERE phone=:p',p='+1800555'+str(n)).first())
        self.queue=self.admin.request('POST','/api/inbound/queues',dict(id=str(uuid4()),name='QA inbound book '+uuid4().hex,phone=self.queue_phone,timezone='America/Toronto',hours=[],max_wait_seconds=60,offer_seconds=20,is_active=True,agents=[dict(user_id=str(self.agent.id),mode='mixed')]),201)
        self.incoming=self.missed(self.card()['phone'])
        self.inbound_path='/api/inbound/followups/'+str(self.incoming)
    def missed(self,phone):
        with engine.begin() as db:
            return inbound_service.record_missed(db,queue_id=__import__('uuid').UUID(self.queue['id']),account_sid='AC'+uuid4().hex,call_sid='CA'+uuid4().hex,caller_number=phone,called_number=self.queue_phone,outcome='missed',received_at=datetime.now(timezone.utc)-timedelta(minutes=1),ended_at=datetime.now(timezone.utc))
    def context(self,actor=None,followup=None,request=None,campaign=None,expected=200):
        return (actor or self.agent).request('POST','/api/inbound/followups/'+str(followup or self.incoming)+'/booking-context',dict(campaign_id=campaign or self.campaign['id'],request_id=str(request or uuid4())),expected)
    def body(self,c):
        return dict(id=str(uuid4()),**{k:c[k] for k in ['campaign_id','contact_id','membership_version','source_followup_id','source_followup_version']},qualification_revision=c['qualification']['revision'] if c['qualification'] else None,qualification=dict(schema_version=3,answers={'postal_code':'  à confirmer  ','comments':'Texte libre'}),**self.schedule)
    def test_inbound_options_and_context_use_existing_contact_once(self):
        options=self.agent.request('GET',self.inbound_path+'/booking-options')
        self.assertTrue(next(c for c in options['items'] if c['id']==self.campaign['id'])['already_enrolled'])
        rid=uuid4();first=self.context(request=rid);again=self.context(request=rid)
        self.assertEqual(first,again);self.assertEqual(first['contact_id'],str(self.contact))
        with engine.connect() as db:
            self.assertEqual(query(db,"SELECT count(*) FROM staging.inbound_followup_events WHERE followup_id=:id AND details->>'reason'='qualification.opened'",id=self.incoming).scalar_one(),1)
    def test_unknown_inbound_caller_can_qualify_and_book_atomically(self):
        phone='+1907555'+f'{uuid4().int%10000:04d}';incoming=self.missed(phone);c=self.context(followup=incoming);body=self.body(c)
        created=self.agent.request('POST','/api/calendar',body,201)
        self.assertEqual(created['phone'],phone);self.assertEqual(created['qualification']['answers']['postal_code'],'  à confirmer  ')
        self.assertEqual(self.agent.request('POST','/api/calendar',body,201),created)
        row=self.agent.request('GET','/api/inbound/followups/'+str(incoming))['followup']
        self.assertEqual(row['stage'],'handled');self.assertEqual(row['owner_id'],str(self.agent.id));self.assertIsNone(row['callback_at'])
        with engine.connect() as db:
            self.assertEqual(query(db,'SELECT count(*) FROM staging.contacts WHERE phone=:p',p=phone).scalar_one(),1)
            self.assertEqual(query(db,"SELECT count(*) FROM staging.inbound_followup_events WHERE followup_id=:id AND details->>'reason'='appointment.booked'",id=incoming).scalar_one(),1)
        card=self.agent.request('GET','/api/campaigns/'+c['campaign_id']+'/contacts/'+c['contact_id'])['contact']
        self.assertEqual(card['stage_id'],str(self.stages['appointment']['id']))
    def test_booking_wrong_contact_or_stale_source_is_atomic(self):
        incoming=self.missed('+1907555'+f'{uuid4().int%10000:04d}');c=self.context(followup=incoming);body=self.body(c)
        body['contact_id']=str(self.contact);self.agent.request('POST','/api/calendar',body,409)
        body=self.body(c);body['source_followup_version']+=1;self.agent.request('POST','/api/calendar',body,409)
        self.assertEqual(self.agent.request('GET','/api/inbound/followups/'+str(incoming))['followup']['stage'],'pending')
        with engine.connect() as db:self.assertEqual(query(db,'SELECT count(*) FROM staging.appointments WHERE id=:id',id=body['id']).scalar_one(),0)
    def test_inbound_booking_permissions_and_optouts_are_enforced(self):
        outsider=Browser('agent');self.context(actor=outsider,expected=403)
        outsider.request('GET',self.inbound_path+'/booking-options',expected=403)
        other=self.admin.request('POST','/api/campaigns',dict(name='Unassigned '+uuid4().hex),201)
        self.context(campaign=other['id'],expected=403)
        with engine.begin() as db:query(db,'UPDATE staging.contacts SET do_not_contact=true WHERE id=:id',id=self.contact)
        self.context(expected=409)
    def test_hidden_caller_and_other_owner_cannot_prepare(self):
        hidden=self.missed(None);self.context(followup=hidden,expected=409)
        owner=Browser('agent')
        with engine.begin() as db:query(db,"INSERT INTO staging.inbound_queue_agents(queue_id,user_id,mode,assigned_by) VALUES (:queue,:actor,'mixed',:admin)",queue=self.queue['id'],actor=owner.id,admin=self.admin.id)
        self.admin.request('POST',self.inbound_path,dict(request_id=str(uuid4()),version=0,stage='claimed',owner_id=str(owner.id)))
        self.context(expected=409)
    def test_concurrent_inbound_books_commit_exactly_one_appointment(self):
        other=Browser('agent');self.admin.request('PUT',self.path+'/agents/'+str(other.id),dict(is_active=True))
        with engine.begin() as db:query(db,"INSERT INTO staging.inbound_queue_agents(queue_id,user_id,mode,assigned_by) VALUES (:queue,:actor,'mixed',:admin)",queue=self.queue['id'],actor=other.id,admin=self.admin.id)
        contexts=[self.context(),self.context(actor=other)];bodies=[self.body(c) for c in contexts]
        def submit(item):
            actor,body=item
            try:actor.request('POST','/api/calendar',body,201);return 201
            except AssertionError as e:
                self.assertEqual(e.args[0][2],409);return 409
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(submit,zip([self.agent,other],bodies))),[201,409])
        with engine.connect() as db:self.assertEqual(query(db,'SELECT count(*) FROM staging.appointments WHERE id=ANY(CAST(:ids AS uuid[]))',ids=[b['id'] for b in bodies]).scalar_one(),1)
    def test_new_phases_persist_filter_and_keep_legacy_lifecycle(self):
        row=self.book();path='/api/calendar/'+row['id']
        for phase,status in [('confirmed','booked'),('sold','completed'),('invalid','cancelled'),('non_compliant','cancelled'),('cancelled','cancelled')]:
            row=self.agent.request('PATCH',path,dict(version=row['version'],status=status,phase=phase,**self.schedule))
            self.assertEqual((row['phase'],row['status']),(phase,status))
            detail=self.agent.request('GET',path);self.assertEqual(detail['appointment']['phase'],phase)
            period=urlencode(dict(start=row['starts_at'],end=(datetime.fromisoformat(row['ends_at'].replace('Z','+00:00'))+timedelta(minutes=1)).isoformat(),phase=phase))
            self.assertIn(row['id'],[r['id'] for r in self.agent.request('GET','/api/calendar?'+period)['items']])
            self.assertEqual(detail['events'][0]['details']['after']['phase'],phase)
        self.agent.request('PATCH',path,dict(version=row['version'],status='booked',phase='sold',**self.schedule),422)
    def test_legacy_status_edit_preserves_phase_and_can_cancel_confirmed(self):
        row=self.book();path='/api/calendar/'+row['id']
        row=self.agent.request('PATCH',path,dict(version=row['version'],status='booked',phase='confirmed',**self.schedule))
        row=self.agent.request('PATCH',path,dict(version=row['version'],status='booked',**self.schedule));self.assertEqual(row['phase'],'confirmed')
        row=self.agent.request('PATCH',path,dict(version=row['version'],status='cancelled',**self.schedule));self.assertEqual(row['phase'],'cancelled')

    def test_live_and_answered_incoming_calls_without_followup_can_prepare(self):
        ids=[]
        with engine.begin() as db:
            for state in ['connected','finished']:
                identifier=uuid4();ids.append(identifier)
                query(db,"""INSERT INTO staging.inbound_calls(id,queue_id,account_sid,parent_call_sid,caller_number,called_number,caller_fingerprint,state,outcome,agent_id,connected_at,finished_at)
                    VALUES (:id,:queue,:account,:sid,:phone,:called,:fingerprint,:state,'answered',:agent,clock_timestamp(),CASE WHEN :state='finished' THEN clock_timestamp() ELSE NULL END)""",id=identifier,queue=self.queue['id'],account='AC'+uuid4().hex,sid='CA'+uuid4().hex,phone=self.card()['phone'],called=self.queue_phone,fingerprint='a'*64,state=state,agent=self.agent.id)
        for identifier in ids:
            path='/api/inbound/calls/'+str(identifier)
            self.assertTrue(self.agent.request('GET',path+'/booking-options')['items'])
            body=dict(campaign_id=self.campaign['id'],request_id=str(uuid4()))
            c=self.agent.request('POST',path+'/booking-context',body)
            self.assertEqual(c,self.agent.request('POST',path+'/booking-context',body))
            self.assertEqual(c['contact_id'],str(self.contact));self.assertNotIn('source_followup_id',c)
            outsider=Browser('agent');outsider.request('GET',path+'/booking-options',expected=403)
            outsider.request('POST',path+'/booking-context',body,403)
        # Preparing CRM data does not end a live conversation or invent a missed call.
        with engine.connect() as db:
            self.assertEqual(query(db,'SELECT state FROM staging.inbound_calls WHERE id=:id',id=ids[0]).scalar_one(),'connected')
            self.assertIsNone(query(db,'SELECT followup_id FROM staging.inbound_calls WHERE id=:id',id=ids[0]).scalar_one())

    def test_inbound_booking_requires_authentication_and_csrf(self):
        path=self.inbound_path+'/booking-options'
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(base+path,timeout=10)
        self.assertEqual(error.exception.code,401)
        req=urllib.request.Request(base+self.inbound_path+'/booking-context',method='POST',data=json.dumps(dict(campaign_id=self.campaign['id'],request_id=str(uuid4()))).encode(),headers={'Origin':origin,'Content-Type':'application/json','Cookie':COOKIE+'='+self.agent.token+'; '+CSRF_COOKIE+'='+self.agent.csrf,'X-CSRF-Token':'wrong'})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req,timeout=10)
        self.assertEqual(error.exception.code,403)

try:
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CalendarInboundTests))
finally:engine.dispose()
raise SystemExit(0 if result.wasSuccessful() else 1)
