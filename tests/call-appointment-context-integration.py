from app.telephony import inbound_service


class CallAppointmentContextTests(unittest.TestCase):
    card=BackendReconfirmationTests.card
    book=BackendReconfirmationTests.book

    def setUp(self):
        BackendReconfirmationTests.setUp(self)
        with engine.connect() as db:
            phone=next('+1800555'+str(n) for n in range(1000,9999)
                       if not query(db,'SELECT 1 FROM staging.inbound_queues WHERE phone=:p',p='+1800555'+str(n)).first())
        self.queue=self.admin.request('POST','/api/inbound/queues',dict(id=str(uuid4()),name='QA call context '+uuid4().hex,
            phone=phone,timezone='America/Toronto',hours=[],max_wait_seconds=60,offer_seconds=20,is_active=True,
            agents=[dict(user_id=str(self.agent.id),mode='mixed')]),201)
        self.account='AC'+uuid4().hex;self.parent='CA'+uuid4().hex
        self.call=uuid4();self.intent=uuid4();self.recording='RE'+uuid4().hex
        self.phone=self.card()['phone']
        with engine.begin() as db:
            self.followup=inbound_service.record_missed(db,queue_id=__import__('uuid').UUID(self.queue['id']),
                account_sid=self.account,call_sid=self.parent,caller_number=self.phone,called_number=phone,outcome='missed',
                received_at=datetime.now(timezone.utc)-timedelta(minutes=5),ended_at=datetime.now(timezone.utc)-timedelta(minutes=4))
            query(db,"""INSERT INTO staging.inbound_calls(id,queue_id,account_sid,parent_call_sid,caller_number,called_number,
                caller_fingerprint,state,outcome,followup_id,finished_at)
                VALUES (:id,:queue,:account,:sid,:phone,:called,:hash,'finished','missed',:followup,clock_timestamp())""",
                id=self.call,queue=self.queue['id'],account=self.account,sid=self.parent,phone=self.phone,called=phone,hash='a'*64,followup=self.followup)
            query(db,"""INSERT INTO staging.inbound_recordings(sid,call_id,call_sid,kind,duration,channels)
                VALUES (:sid,:call,:parent,'voicemail',30,1)""",sid=self.recording,call=self.call,parent=self.parent)
            query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,
                caller_number,destination,state,outcome,expires_at,finished_at,consumed_at,parent_call_sid)
                VALUES (:id,:actor,:session,:profile,:account,:app,:caller,:phone,'finished','completed',
                    clock_timestamp()+interval '1 minute',clock_timestamp(),clock_timestamp(),:parent)""",id=self.intent,actor=self.agent.id,
                session=digest(self.agent.token),profile='b'*64,account=self.account,app='AP'+uuid4().hex,caller=phone,phone=self.phone,parent='CA'+uuid4().hex)
        self.history='/api/inbound/queues/'+self.queue['id']+'/calls'
        self.followup_path='/api/inbound/followups/'+str(self.followup)

    def contexts(self):
        incoming=next(c for c in self.agent.request('GET',self.history)['items'] if c['id']==str(self.call))
        followup=self.agent.request('GET',self.followup_path)['followup']
        interaction=self.agent.request('GET',self.followup_path+'/calls')['items'][0]
        outgoing=next(c for c in self.agent.request('GET','/api/telephony/calls')['items'] if c['id']==str(self.intent))
        return incoming,followup,interaction,outgoing

    def test_existing_booking_matches_canonical_phone_in_all_history_views(self):
        booked=self.book('booked')
        for row in self.contexts():
            with self.subTest(view=list(row)):
                appointment=row['client_appointment']
                self.assertEqual(appointment['id'],booked['id'])
                self.assertEqual(appointment['starts_at'],booked['starts_at'])
                self.assertEqual(appointment['ends_at'],booked['ends_at'])
                self.assertEqual(appointment['timezone'],'UTC')
                self.assertEqual(appointment['notes'],self.schedule['notes'])
                self.assertEqual(appointment['creator_name'],'QA reconfirmation')
                self.assertEqual(appointment['campaign_name'],self.campaign['name'])
        self.assertEqual(self.contexts()[0]['recordings'][0]['sid'],self.recording)
        self.assertIsNone(self.contexts()[-1]['campaign_id'])  # manual call, matched by canonical phone

    def test_latest_booking_and_current_cancelled_phase_are_not_an_older_booked_visit(self):
        first=self.book('booked');second=self.book('booked')
        updated=self.agent.request('PATCH','/api/calendar/'+second['id'],dict(version=second['version'],
            status='cancelled',phase='invalid',**{**self.schedule,'notes':'Coordonnées à revoir'}))
        for row in self.contexts():
            appointment=row['client_appointment']
            self.assertEqual(appointment['id'],second['id']);self.assertNotEqual(appointment['id'],first['id'])
            self.assertEqual(appointment['phase'],'invalid');self.assertEqual(appointment['status'],'cancelled')
            self.assertEqual(appointment['notes'],updated['notes'])

    def test_no_booking_is_explicit_and_gets_do_not_create_or_change_business_rows(self):
        def snapshot():
            with engine.connect() as db:
                return (query(db,'SELECT count(*) FROM staging.appointments').scalar_one(),
                    query(db,'SELECT version FROM staging.inbound_followups WHERE id=:id',id=self.followup).scalar_one(),
                    query(db,'SELECT version FROM staging.campaign_contacts WHERE contact_id=:id',id=self.contact).scalar_one())
        before=snapshot()
        self.assertTrue(all(row['client_appointment'] is None for row in self.contexts()))
        self.assertEqual(before,snapshot())

    def test_other_contacts_booking_does_not_leak_and_hidden_caller_has_no_match(self):
        self.book('booked')
        with engine.begin() as db:
            query(db,"UPDATE staging.inbound_calls SET caller_number=NULL WHERE id=:id",id=self.call)
            query(db,"UPDATE staging.voice_intents SET destination='+19005550199' WHERE id=:id",id=self.intent)
        self.assertIsNone(self.agent.request('GET',self.history)['items'][0]['client_appointment'])
        self.assertIsNone(next(c for c in self.agent.request('GET','/api/telephony/calls')['items']
                              if c['id']==str(self.intent))['client_appointment'])

    def test_queue_and_call_permissions_survive_context_enrichment(self):
        self.book('booked');outsider=Browser('agent')
        outsider.request('GET',self.history,expected=403)
        outsider.request('GET',self.followup_path,expected=403)
        outsider.request('GET',self.followup_path+'/calls',expected=403)
        self.assertNotIn(str(self.intent),[c['id'] for c in outsider.request('GET','/api/telephony/calls')['items']])
        with engine.begin() as db:
            query(db,'UPDATE staging.inbound_queue_agents SET is_active=false WHERE queue_id=:queue AND user_id=:user',
                  queue=self.queue['id'],user=self.agent.id)
        self.agent.request('GET',self.history,expected=403)
        self.agent.request('GET',self.followup_path,expected=403)


try:
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CallAppointmentContextTests))
finally:engine.dispose()
raise SystemExit(0 if result.wasSuccessful() else 1)
