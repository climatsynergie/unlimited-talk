"""Business scenarios before the durable inbound/provider coordinator is armed."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import unittest
from app.telephony.inbound import (Action, AgentMode, AgentSnapshot, AgentState,
    CallState, IncomingCall, OfferOutcome, QueuePolicy, decide)


class InboundRoutingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 31, 15, tzinfo=timezone.utc)
        self.agents = tuple(AgentSnapshot(UUID(int=i + 1), AgentState.READY, AgentMode.INBOUND,
            self.now, self.now - timedelta(minutes=20 - i)) for i in range(20))
        self.policy = QueuePolicy(frozenset(a.id for a in self.agents))
        self.call = IncomingCall(uuid4(), CallState.WAITING, self.now - timedelta(seconds=10))

    def route(self, **changes):
        args = dict(policy=self.policy, call=self.call, agents=self.agents, now=self.now, within_hours=True)
        return decide(**(args | changes))

    def test_twenty_agents_choose_longest_idle_among_explicit_assignments(self):
        policy = replace(self.policy, assigned_agents=frozenset([self.agents[7].id, self.agents[15].id]))
        result = self.route(policy=policy)
        self.assertEqual((result.action, result.agent_id, result.ring_seconds),
                         (Action.OFFER, self.agents[7].id, 20))

    def test_every_busy_or_paused_state_and_outbound_capacity_prevents_a_second_call(self):
        for state in AgentState:
            if state == AgentState.READY: continue
            with self.subTest(state=state):
                self.assertEqual(self.route(agents=tuple(replace(a, state=state) for a in self.agents)).action, Action.WAIT)
        for changes in [dict(mode=AgentMode.OUTBOUND), dict(reserved_call_id=uuid4()),
                        dict(outbound_intent_active=True), dict(active=False), dict(media_ready=False)]:
            with self.subTest(changes=changes):
                self.assertEqual(self.route(agents=tuple(replace(a, **changes) for a in self.agents)).action, Action.WAIT)

    def test_stale_or_future_presence_never_establishes_availability(self):
        for delta in [-31, -30, 1]:
            agents=tuple(replace(a, last_seen_at=self.now+timedelta(seconds=delta)) for a in self.agents)
            self.assertEqual(self.route(agents=agents).action, Action.WAIT)
        self.assertEqual(self.route(agents=tuple(replace(a, ready_since=self.now+timedelta(seconds=1)) for a in self.agents)).action, Action.WAIT)

    def test_mixed_agent_can_receive_while_available_without_interruption(self):
        agent=replace(self.agents[0], mode=AgentMode.MIXED)
        self.assertEqual(self.route(agents=(agent,)).agent_id, agent.id)
        self.assertEqual(self.route(agents=(replace(agent,outbound_intent_active=True),)).action, Action.WAIT)

    def test_rejected_or_verified_no_answer_offer_moves_to_next_agent(self):
        for outcome in [OfferOutcome.REJECTED, OfferOutcome.NO_ANSWER]:
            call=replace(self.call,state=CallState.OFFERED,offered_agent=self.agents[0].id,
                offered_at=self.now-timedelta(seconds=5),offer_outcome=outcome)
            self.assertEqual(self.route(call=call).agent_id,self.agents[1].id)

    def test_elapsed_or_uncertain_offer_requires_reconciliation_not_a_second_offer(self):
        for outcome, elapsed in [(OfferOutcome.UNCERTAIN, 1), (OfferOutcome.PENDING, 20),
                                  (OfferOutcome.ACCEPTED, 1)]:
            call=replace(self.call,received_at=self.now-timedelta(seconds=90),state=CallState.OFFERED,
                offered_agent=self.agents[0].id,offered_at=self.now-timedelta(seconds=elapsed),offer_outcome=outcome)
            self.assertEqual(self.route(call=call).action,Action.RECONCILE)
        call=replace(call,caller_waiting=False,offer_outcome=OfferOutcome.PENDING)
        self.assertEqual(self.route(call=call).action,Action.RECONCILE)

    def test_pending_offer_is_retained(self):
        call=replace(self.call,state=CallState.OFFERED,offered_agent=self.agents[0].id,
            offered_at=self.now-timedelta(seconds=2),offer_outcome=OfferOutcome.PENDING)
        self.assertEqual(self.route(call=call).action,Action.WAIT)

    def test_wait_limit_and_closed_hours_keep_followup_even_without_voicemail_result(self):
        for changes in [dict(call=replace(self.call,received_at=self.now-timedelta(seconds=60))),
                        dict(within_hours=False),dict(policy=replace(self.policy,enabled=False))]:
            result=self.route(**changes)
            self.assertEqual(result.action,Action.VOICEMAIL)
            self.assertTrue(result.follow_up_required)
        result=self.route(call=replace(self.call,caller_waiting=False))
        self.assertEqual(result.action,Action.FOLLOW_UP)
        self.assertTrue(result.follow_up_required)

    def test_connected_or_finished_call_cannot_reopen_as_a_missed_call(self):
        for state in [CallState.CONNECTED,CallState.FINISHED]:
            result=self.route(call=replace(self.call,state=state,caller_waiting=False),within_hours=False)
            self.assertEqual(result.action,Action.NONE)
            self.assertFalse(result.follow_up_required)

    def test_offer_does_not_exceed_the_remaining_queue_time(self):
        result=self.route(call=replace(self.call,received_at=self.now-timedelta(seconds=55)))
        self.assertEqual(result.ring_seconds,5)
        result=self.route(call=replace(self.call,received_at=self.now-timedelta(seconds=59.9)))
        self.assertEqual(result.action,Action.VOICEMAIL)
        call=replace(self.call,received_at=self.now-timedelta(seconds=60),state=CallState.OFFERED,
            offered_agent=self.agents[0].id,offered_at=self.now-timedelta(seconds=5),
            offer_outcome=OfferOutcome.PENDING)
        self.assertEqual(self.route(call=call).action,Action.RECONCILE)

    def test_attempted_agents_are_not_rung_again_and_ties_are_stable(self):
        call=replace(self.call,attempted_agents=self.policy.assigned_agents)
        self.assertEqual(self.route(call=call).action,Action.WAIT)
        agents=tuple(replace(a,ready_since=self.now-timedelta(minutes=1)) for a in reversed(self.agents))
        self.assertEqual(self.route(agents=agents).agent_id,self.agents[0].id)

    def test_bad_configuration_and_ambiguous_snapshots_are_rejected(self):
        for changes in [dict(max_wait_seconds=True),dict(offer_seconds=61),dict(assigned_agents=set()),
                        dict(max_wait_seconds=10,offer_seconds=20)]:
            with self.assertRaises(ValueError):replace(self.policy,**changes)
        for changes in [dict(now=self.now.replace(tzinfo=None)),dict(agents=(self.agents[0],self.agents[0])),
                        dict(now=self.call.received_at-timedelta(seconds=1))]:
            with self.assertRaises(ValueError):self.route(**changes)
        with self.assertRaises(ValueError):replace(self.call,state=CallState.OFFERED)
