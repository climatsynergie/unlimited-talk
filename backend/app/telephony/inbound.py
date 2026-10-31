"""Inbound routing decisions from trusted, durable call/agent snapshots.

This policy never calls Twilio, claims an agent, changes a card or releases a
reservation. Its future transactional coordinator must lock/recheck the shared
agent capacity before persisting an offer, then deliver it through durable work.
Uncertain offers require provider reconciliation before any second offer.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AgentState(StrEnum):
    OFFLINE = 'offline'
    READY = 'ready'
    RESERVED = 'reserved'
    RINGING = 'ringing'
    TALKING = 'talking'
    WRAP_UP = 'wrap_up'
    APPOINTMENT = 'appointment'
    PAUSED = 'paused'
    STOPPED = 'stopped'


class AgentMode(StrEnum):
    INBOUND = 'inbound'
    OUTBOUND = 'outbound'
    MIXED = 'mixed'


class CallState(StrEnum):
    WAITING = 'waiting'
    OFFERED = 'offered'
    CONNECTED = 'connected'
    FINISHED = 'finished'


class OfferOutcome(StrEnum):
    PENDING = 'pending'
    REJECTED = 'rejected'
    NO_ANSWER = 'no_answer'
    ACCEPTED = 'accepted'
    UNCERTAIN = 'uncertain'


class Action(StrEnum):
    OFFER = 'offer'
    WAIT = 'wait'
    VOICEMAIL = 'voicemail'
    FOLLOW_UP = 'follow_up'
    RECONCILE = 'reconcile'
    NONE = 'none'


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Un instant avec fuseau horaire est requis.')
    return value


@dataclass(frozen=True)
class QueuePolicy:
    # Administrative assignments and the already-evaluated schedule come from
    # server configuration, never from a Voice SDK/browser request.
    assigned_agents: frozenset[UUID]
    enabled: bool = True
    max_wait_seconds: int = 60
    offer_seconds: int = 20
    presence_seconds: int = 30

    def __post_init__(self):
        if (not isinstance(self.assigned_agents, frozenset)
                or any(not isinstance(a, UUID) for a in self.assigned_agents)
                or type(self.enabled) is not bool):
            raise ValueError('Configuration de file invalide.')
        for value, low, high in [(self.max_wait_seconds, 10, 600),
                                  (self.offer_seconds, 5, 60), (self.presence_seconds, 10, 120)]:
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Délai de file invalide.')
        if self.offer_seconds > self.max_wait_seconds:
            raise ValueError("La sonnerie ne peut pas dépasser l'attente maximale.")


@dataclass(frozen=True, repr=False)
class AgentSnapshot:
    id: UUID
    state: AgentState
    mode: AgentMode
    last_seen_at: datetime
    ready_since: datetime
    active: bool = True
    media_ready: bool = True
    # Both directions must consult the SAME durable capacity. Presence expiry
    # does not clear these fields or prove a provider call has ended.
    reserved_call_id: UUID | None = None
    outbound_intent_active: bool = False

    def __post_init__(self):
        if (not isinstance(self.id, UUID) or not isinstance(self.state, AgentState)
                or not isinstance(self.mode, AgentMode)
                or any(type(v) is not bool for v in (self.active, self.media_ready, self.outbound_intent_active))
                or (self.reserved_call_id is not None and not isinstance(self.reserved_call_id, UUID))):
            raise ValueError("État d'agent invalide.")
        aware(self.last_seen_at); aware(self.ready_since)


@dataclass(frozen=True, repr=False)
class IncomingCall:
    id: UUID
    state: CallState
    received_at: datetime
    caller_waiting: bool = True
    attempted_agents: frozenset[UUID] = frozenset()
    offered_agent: UUID | None = None
    offered_at: datetime | None = None
    offer_outcome: OfferOutcome | None = None

    def __post_init__(self):
        if (not isinstance(self.id, UUID) or not isinstance(self.state, CallState)
                or type(self.caller_waiting) is not bool
                or not isinstance(self.attempted_agents, frozenset)
                or any(not isinstance(a, UUID) for a in self.attempted_agents)):
            raise ValueError("État d'appel invalide.")
        aware(self.received_at)
        if self.state == CallState.OFFERED:
            if not isinstance(self.offered_agent, UUID) or not isinstance(self.offer_outcome, OfferOutcome):
                raise ValueError("Offre d'appel incomplète.")
            if aware(self.offered_at) < self.received_at:
                raise ValueError("Date d'offre invalide.")
        elif any(v is not None for v in (self.offered_agent, self.offered_at, self.offer_outcome)):
            raise ValueError("Offre incohérente avec l'état de l'appel.")


@dataclass(frozen=True, repr=False)
class Decision:
    action: Action
    reason: str
    agent_id: UUID | None = None
    ring_seconds: int | None = None
    follow_up_required: bool = False


def decide(policy: QueuePolicy, call: IncomingCall, agents: tuple[AgentSnapshot, ...],
           now: datetime, *, within_hours: bool):
    """A proposal only; the shared reservation transaction must still arbitrate."""
    aware(now)
    if (not isinstance(policy, QueuePolicy) or not isinstance(call, IncomingCall)
            or not isinstance(agents, tuple) or any(not isinstance(a, AgentSnapshot) for a in agents)
            or type(within_hours) is not bool or now < call.received_at
            or len({a.id for a in agents}) != len(agents)):
        raise ValueError('Instantané de distribution invalide.')
    if call.state in {CallState.CONNECTED, CallState.FINISHED}:
        return Decision(Action.NONE, 'already_connected_or_finished')
    attempted = call.attempted_agents
    if call.state == CallState.OFFERED:
        if now < call.offered_at:
            raise ValueError("L'offre est dans le futur.")
        if call.offer_outcome == OfferOutcome.ACCEPTED:
            return Decision(Action.RECONCILE, 'bridge_confirmation_required')
        if call.offer_outcome == OfferOutcome.UNCERTAIN:
            return Decision(Action.RECONCILE, 'offer_result_uncertain')
        if call.offer_outcome == OfferOutcome.PENDING:
            if ((now - call.offered_at).total_seconds() >= policy.offer_seconds
                    or (now - call.received_at).total_seconds() >= policy.max_wait_seconds
                    or not call.caller_waiting):
                return Decision(Action.RECONCILE, 'offer_final_state_required')
            return Decision(Action.WAIT, 'offer_pending')
        # Only a verified terminal offer permits selecting a second agent.
        attempted = attempted | {call.offered_agent}
    if not call.caller_waiting:
        return Decision(Action.FOLLOW_UP, 'caller_abandoned', follow_up_required=True)
    if not policy.enabled:
        return Decision(Action.VOICEMAIL, 'queue_disabled', follow_up_required=True)
    if not within_hours:
        return Decision(Action.VOICEMAIL, 'outside_hours', follow_up_required=True)
    remaining = policy.max_wait_seconds - (now - call.received_at).total_seconds()
    if remaining < 1:
        return Decision(Action.VOICEMAIL, 'wait_limit_reached', follow_up_required=True)
    eligible = [a for a in agents if a.id in policy.assigned_agents and a.id not in attempted
                and a.active and a.media_ready and a.state == AgentState.READY
                and a.mode in {AgentMode.INBOUND, AgentMode.MIXED}
                and a.reserved_call_id is None and not a.outbound_intent_active
                and 0 <= (now - a.last_seen_at).total_seconds() < policy.presence_seconds
                and a.ready_since <= a.last_seen_at]
    if not eligible:
        return Decision(Action.WAIT, 'no_eligible_agent')
    agent = min(eligible, key=lambda a: (a.ready_since, a.id.int))
    return Decision(Action.OFFER, 'longest_idle_assigned_agent', agent.id,
                    min(policy.offer_seconds, int(remaining)))
