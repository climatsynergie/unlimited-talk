from urllib.parse import urlencode
from app.calendar import text_export

class ConversationAgendaTests(unittest.TestCase):
    setUp=BackendReconfirmationTests.setUp
    def export(self,actor=None,day='2026-11-19',expected=200,**params):
        actor=actor or self.agent
        headers={'Cookie':COOKIE+'='+actor.token+'; '+CSRF_COOKIE+'='+actor.csrf}
        url=base+'/api/calendar/export.txt?'+urlencode(dict(day=day,timezone='America/Toronto',**params))
        try:r=urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=20)
        except urllib.error.HTTPError as error:r=error
        with r:
            data=r.read();self.assertEqual(r.status,expected,data[:400])
            return data.decode('utf-8-sig'),r.headers
    def appointment(self,at='2026-11-20T00:00:00Z',owner=None,answers=None,status='booked',phase=None):
        identifier=uuid4();owner=owner or self.agent
        with engine.begin() as db:
            query(db,"""INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone,status,notes)
              VALUES (:id,:campaign,:contact,:actor,:hash,CAST(:at AS timestamptz),CAST(:at AS timestamptz)+interval '30 minutes','America/Toronto',:status,'Notes QA export')""",id=identifier,campaign=self.campaign['id'],contact=self.contact,actor=owner.id,hash=uuid4().hex,at=at,status=status)
            if answers is not None or phase:
                after=dict(status=status)
                if answers is not None:after['qualification']={'schema_version':3,'answers':answers}
                if phase:after['phase']=phase
                query(db,"INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details) VALUES (:id,:actor,'appointment.created',CAST(:details AS jsonb))",id=identifier,actor=owner.id,details=json.dumps({'after':after}))
        return identifier
    def calls(self,durations,actor=None):
        actor=actor or self.agent;ids=[]
        with engine.begin() as db:
            for i,seconds in enumerate(durations):
                identifier=uuid4();ids.append(identifier);parent='CA'+uuid4().hex
                at=datetime(2026,11,19,12,tzinfo=timezone.utc)+timedelta(seconds=i)
                query(db,"""INSERT INTO staging.voice_intents(id,actor_id,session_hash,profile_hash,account_sid,application_sid,caller_number,destination,state,parent_call_sid,created_at,expires_at,consumed_at,finished_at,outcome)
                 VALUES (:id,:actor,:session,:profile,:account,:application,'+14165550100',:destination,'finished',:parent,:at,:at+interval '2 minutes',:at,:at+interval '2 minutes','completed')""",id=identifier,actor=actor.id,session=digest(actor.token),profile='b'*64,account='AC'+'a'*32,application='AP'+'b'*32,destination='+1514'+str(1000000+uuid4().int%8000000),parent=parent,at=at)
                if seconds is not None:
                    query(db,"INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels) VALUES (:sid,:id,:parent,:seconds,2)",sid='RE'+uuid4().hex,id=identifier,parent=parent,seconds=seconds)
        return ids
    def history(self,actor=None,**params):
        return (actor or self.agent).request('GET','/api/telephony/calls?'+urlencode(params))
    def test_recording_threshold_is_strict_and_does_not_use_total_call_duration(self):
        ids=self.calls([None,0,19,20,21,30,31,60])
        self.assertEqual({r['id'] for r in self.history()['items']},set(map(str,ids)))
        self.assertEqual({r['id'] for r in self.history(recording_min_seconds=20)['items']},set(map(str,ids[4:])))
        self.assertEqual({r['id'] for r in self.history(recording_min_seconds=30)['items']},set(map(str,ids[6:])))
        for row in self.history(recording_min_seconds=30)['items']:
            self.assertTrue(all(r['duration']>30 for r in row['recordings']))
    def test_filter_applies_before_keyset_pagination_and_recordings_are_not_duplicated(self):
        ids=self.calls([31]*25+[1]*25)
        with engine.begin() as db:
            query(db,"INSERT INTO staging.voice_recordings(sid,intent_id,call_sid,duration,channels) SELECT :sid,id,parent_call_sid,2,2 FROM staging.voice_intents WHERE id=:id",sid='RE'+uuid4().hex,id=ids[0])
        first=self.history(recording_min_seconds=30);self.assertEqual(len(first['items']),20)
        cursor=first['next_cursor'];self.assertIsNotNone(cursor)
        second=self.history(recording_min_seconds=30,before_id=cursor['id'],before_created_at=cursor['created_at'])
        self.assertEqual(len(second['items']),5);self.assertIsNone(second['next_cursor'])
        both=first['items']+second['items'];self.assertEqual(len({r['id'] for r in both}),25)
        self.assertTrue(all(len(r['recordings'])==1 and r['recordings'][0]['duration']==31 for r in both))
    def test_threshold_preserves_agent_permissions_and_other_filters(self):
        self.calls([21,31]);other=Browser('agent');self.calls([60],other)
        self.assertEqual(len(self.history(recording_min_seconds=30)['items']),1)
        self.assertEqual(len(self.history(self.admin,recording_min_seconds=30,actor_id=self.agent.id)['items']),1)
        self.agent.request('GET','/api/telephony/calls?'+urlencode(dict(recording_min_seconds=30,actor_id=other.id)),expected=403)
        self.assertEqual(self.history(recording_min_seconds=30,recordings_only='true',outcome='no-answer')['items'],[])
        for value in ['-1','1.5','86401','hello']:
            self.agent.request('GET','/api/telephony/calls?recording_min_seconds='+value,expected=422)
    def test_daily_export_has_complete_saved_qualification_and_headers(self):
        with engine.begin() as db:
            query(db,"UPDATE staging.contacts SET profile=CAST(:profile AS jsonb) WHERE id=:id",id=self.contact,profile=json.dumps(dict(display_name='Émilie synthétique',address='Ancienne adresse')))
        self.appointment(answers=dict(civic_number='12',street='Rue QA',city='Québec',postal_code='Texte libre',construction_year='2019',hydro_bill='330 $ par mois',comments='Décision dans une semaine ou deux.'))
        body,headers=self.export(creator=self.agent.id)
        for text in ['jeudi 19 novembre 2026 à 19 h 00','Émilie synthétique','12 Rue QA, Québec Texte libre','Année de construction : 2019','330 $ par mois','Décision dans une semaine ou deux.','Booker par : QA reconfirmation']:
            self.assertIn(text,body)
        self.assertNotIn('Ancienne adresse',body)
        self.assertEqual(headers['Cache-Control'],'no-store');self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
        self.assertIn('text/plain',headers['Content-Type']);self.assertIn('2026-11-19.txt',headers['Content-Disposition'])
    def test_export_uses_appointment_snapshot_not_new_contact_draft_and_legacy_is_supported(self):
        id=self.appointment(answers={'hydro_bill':'Ancienne facture RDV'})
        with engine.begin() as db:
            query(db,"INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details) VALUES (:id,:actor,'appointment.updated',CAST(:details AS jsonb))",id=id,actor=self.agent.id,details=json.dumps({'after':{'status':'booked','qualification':{'schema_version':3,'answers':{'hydro_bill':'Facture corrigée RDV'}}}}))
            query(db,"INSERT INTO staging.campaign_events(campaign_id,contact_id,actor_id,action,details) VALUES (:campaign,:contact,:actor,'contact.qualification_saved',CAST(:details AS jsonb))",campaign=self.campaign['id'],contact=self.contact,actor=self.agent.id,details=json.dumps({'qualification':{'schema_version':3,'answers':{'hydro_bill':'Brouillon futur'}}}))
        self.appointment()
        body,_=self.export(creator=self.agent.id)
        self.assertIn('Facture corrigée RDV',body);self.assertNotIn('Brouillon futur',body)
        self.assertNotIn('Ancienne facture RDV',body);self.assertIn('Qualification : non renseignée',body)
    def test_export_contains_more_than_one_list_page_and_honors_creator_and_phase(self):
        for i in range(105):self.appointment(answers={'comments':'Fiche '+str(i)})
        self.appointment(owner=self.admin,status='cancelled',phase='invalid',answers={'comments':'ANNULÉ QA'})
        body,_=self.export(creator=self.agent.id)
        self.assertEqual(body.count('Booker par :'),105);self.assertIn('Fiche 104',body);self.assertNotIn('ANNULÉ QA',body)
        body,_=self.export(creator=self.admin.id,phase='invalid')
        self.assertEqual(body.count('Booker par :'),1);self.assertIn('Statut : Non valide',body)
        self.export(creator=self.admin.id,exclude_cancelled='true',expected=404)
    def test_export_respects_local_midnight_boundaries(self):
        for at in ['2026-11-19T04:59:00Z','2026-11-19T05:00:00Z','2026-11-20T04:59:00Z','2026-11-20T05:00:00Z']:
            self.appointment(at=at)
        body,_=self.export(creator=self.agent.id)
        self.assertEqual(body.count('Booker par :'),2)
        self.assertIn('00 h 00',body);self.assertIn('23 h 59',body)
    def test_shared_calendar_export_permissions_revocation_and_invalid_arguments(self):
        self.appointment()
        outsider=Browser('agent');body,_=self.export(outsider,creator=self.agent.id)
        self.assertIn('Booker par :',body) # Existing shared-calendar visibility.
        anonymous=type('Anonymous',(),dict(token='',csrf=''))()
        self.export(anonymous,creator=self.agent.id,expected=401)
        with engine.begin() as db:query(db,'UPDATE staging.identity_users SET is_active=false WHERE id=:id',id=outsider.id)
        self.export(outsider,creator=self.agent.id,expected=401)
        self.export(day='2026-02-30',expected=422)
        self.export(day='1999-01-01',expected=422)
        self.export(creator='not-a-uuid',expected=422)
        self.agent.request('GET','/api/calendar/export.txt?day=2026-11-19&timezone=Bad%2FZone',expected=422)
    def test_daily_export_bound_rejects_instead_of_silently_truncating(self):
        with engine.begin() as db:
            query(db,"""INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone)
              SELECT md5(:seed||i)::uuid,:campaign,:contact,:actor,md5(:seed||i),'2026-11-19T15:00:00Z','2026-11-19T15:30:00Z','America/Toronto' FROM generate_series(1,1001)i""",seed=uuid4().hex,campaign=self.campaign['id'],contact=self.contact,actor=self.agent.id)
        self.export(creator=self.agent.id,expected=422)

    def test_oversized_qualification_export_is_rejected_and_slot_is_released(self):
        with engine.begin() as db:
            query(db,"""WITH inserted AS (
              INSERT INTO staging.appointments(id,campaign_id,contact_id,created_by,request_hash,starts_at,ends_at,timezone)
              SELECT md5(:seed||i)::uuid,:campaign,:contact,:actor,md5(:seed||i),'2026-11-19T15:00:00Z','2026-11-19T15:30:00Z','America/Toronto' FROM generate_series(1,20)i RETURNING id)
              INSERT INTO staging.appointment_events(appointment_id,actor_id,action,details)
              SELECT id,:actor,'appointment.created',jsonb_build_object('after',jsonb_build_object('status','booked','qualification',jsonb_build_object('schema_version',3,'answers',jsonb_build_object('comments',repeat('q',500000))))) FROM inserted""",seed=uuid4().hex,campaign=self.campaign['id'],contact=self.contact,actor=self.agent.id)
        self.export(creator=self.agent.id,expected=422)
        self.export(creator=self.admin.id,expected=404) # Failed export released its slot.

result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConversationAgendaTests))
engine.dispose()
if not result.wasSuccessful():raise SystemExit(1)
