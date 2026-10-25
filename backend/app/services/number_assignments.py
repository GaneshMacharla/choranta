"""
Giving a number from Choranta's pool to a client (optionally an AI employee and a SIP trunk), and taking it back.

Assigning creates the client's PhoneNumber routing record (models/phone_number.py), which inbound calls are matched
by, so the client sees it under Phone numbers. Unassigning retires that record (keeping its history) and returns the
number to the pool; it is not released at the carrier.

Carrier side: a trunk, when given, is assigned at Vobiz, and the number is (re)attached to Choranta's application so
inbound calls reach our answer URL. Vobiz has no "detach from application" call, so an unassigned number still
reaches Choranta, where calls to it are refused as an unconfigured number.
"""
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.client import Client
from app.models.numbers import NumberAssignment, NumberOperation, ProviderNumber
from app.models.phone_number import PhoneNumber
from app.models.subscription import NumberRental
from app.runtime.providers.numbers import NumberNotFound, NumberProviderError
from app.services import number_service as svc

logger = logging.getLogger("choranta.services.number_assignments")


def _published_version(db: Session, agent: Agent) -> AgentVersion:
    version = (db.query(AgentVersion)
               .filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "PUBLISHED")
               .order_by(AgentVersion.version_number.desc()).first())
    if not version:
        raise svc.NumberServiceError(400, "agent_not_published", f"{agent.name} has no published version yet.")
    return version


def _op(db: Session, pn: ProviderNumber, kind: str, actor: svc.Actor, client_id: Optional[str], request: dict) -> NumberOperation:
    op = NumberOperation(provider_number_id=pn.id, provider=pn.provider, e164=pn.e164, operation_type=kind,
                         actor=actor.label, actor_user_id=actor.user_id, client_id=client_id, is_mock=pn.is_mock,
                         request=request)
    db.add(op)
    db.commit()
    return op


def _failed(db: Session, op: NumberOperation, exc: NumberProviderError) -> svc.NumberServiceError:
    op.operation_status, op.error_code, op.error_message = (
        "UNCERTAIN" if exc.code == "provider_uncertain" else "FAILED"), exc.code, exc.message
    db.commit()
    return svc.NumberServiceError(exc.status_code, exc.code, exc.message, op)


def assign(db: Session, number_id: str, *, client_id: str, actor: svc.Actor, agent_id: Optional[str] = None,
           trunk_id: Optional[str] = None) -> PhoneNumber:
    """Gives an AVAILABLE number to a client. Returns the client's routing record (READY_TO_TEST)."""
    pn = svc.get_number(db, number_id)
    if svc.active_assignment(db, pn.id) or pn.internal_status == "ASSIGNED":
        raise svc.NumberServiceError(409, "already_assigned", f"{pn.e164} is already assigned. Unassign it first.")
    if pn.internal_status != "AVAILABLE":
        raise svc.NumberServiceError(409, "not_available", f"{pn.e164} can't be assigned while it's {pn.internal_status.lower().replace('_', ' ')}.")
    if pn.is_mock != svc.mock_mode():
        raise svc.NumberServiceError(409, "wrong_mode", "This number belongs to the other mode (mock vs real).")
    client = db.get(Client, client_id)
    if not client:
        raise svc.NumberServiceError(404, "client_not_found", "Client not found.")
    agent, version = None, None
    if agent_id:
        agent = db.query(Agent).filter(Agent.id == agent_id, Agent.client_id == client_id).first()
        if not agent:
            raise svc.NumberServiceError(400, "agent_not_found", "That AI employee doesn't belong to this client.")
        version = _published_version(db, agent)
    clash = db.query(PhoneNumber).filter(PhoneNumber.phone_number == pn.e164).first()
    if clash and clash.client_id != client_id:
        raise svc.NumberServiceError(409, "routing_conflict",
                                     f"{pn.e164} is still set up for another client in Telephony. Remove it there first.")

    op = _op(db, pn, "ASSIGN", actor, client_id, {"client_id": client_id, "agent_id": agent_id, "trunk_id": trunk_id})
    with svc.carrier(db) as provider:
        if trunk_id:
            try:
                provider.assign_trunk(pn.e164, trunk_id)
            except NumberProviderError as exc:
                raise _failed(db, op, exc)
        svc.attach_application(db, provider, pn, actor)

    try:
        routing = clash or PhoneNumber(id=generate_unique_id("phn", 10), client_id=client_id, provider=pn.provider,
                                       phone_number=pn.e164)
        routing.provider_number_id = pn.provider_number_id
        routing.country_code = pn.country or "IN"
        routing.status = "READY_TO_TEST"
        routing.agent_id = agent.id if agent else None
        routing.agent_version_id = version.id if version else None
        routing.metadata_ = {**(routing.metadata_ or {}), "number_type": pn.number_type, "provider_number": pn.id,
                             "bought_from_choranta": True}
        db.add(routing)
        db.flush()
        db.add(NumberAssignment(provider_number_id=pn.id, client_id=client_id, agent_id=agent.id if agent else None,
                                trunk_id=trunk_id, phone_number_id=routing.id, status="ACTIVE", assigned_by=actor.label))
        pn.internal_status = "ASSIGNED"
        pn.trunk_id = trunk_id or pn.trunk_id
        op.operation_status = "SUCCEEDED"
        op.result = {"phone_number_id": routing.id}
        db.commit()
    except IntegrityError:
        db.rollback()
        op = db.get(NumberOperation, op.id)
        op.operation_status, op.error_code, op.error_message = "FAILED", "already_assigned", "Assigned by someone else at the same time."
        db.commit()
        raise svc.NumberServiceError(409, "already_assigned", f"{pn.e164} was just assigned by someone else.", op)
    logger.info("%s assigned %s to client %s", actor.label, pn.e164, client_id)
    return routing


def retire_routing(db: Session, routing: PhoneNumber, suffix: str) -> None:
    """Keeps the client's routing record for history but frees the number (same scheme as services/phone_numbers.release)."""
    if "~" in routing.phone_number:
        return  # already retired
    original = routing.phone_number
    routing.metadata_ = {**(routing.metadata_ or {}), "released_number": original}
    routing.phone_number = f"{original}~{suffix[-8:]}"
    routing.status = "RELEASED"
    routing.agent_id = None
    routing.agent_version_id = None


def unassign(db: Session, number_id: str, *, actor: svc.Actor, reason: str = "UNASSIGNED") -> ProviderNumber:
    """Takes a number back from its client into the pool. The client's rental for it, if any, ends."""
    pn = svc.get_number(db, number_id)
    current = svc.active_assignment(db, pn.id)
    if not current:
        raise svc.NumberServiceError(409, "not_assigned", f"{pn.e164} isn't assigned to anyone.")
    op = _op(db, pn, "UNASSIGN", actor, current.client_id, {"reason": reason})
    if pn.trunk_id and pn.is_mock == svc.mock_mode():
        with svc.carrier(db) as provider:
            try:
                provider.unassign_trunk(pn.e164)
            except NumberNotFound:
                pass
            except NumberProviderError as exc:
                raise _failed(db, op, exc)

    routing = db.get(PhoneNumber, current.phone_number_id) if current.phone_number_id else None
    if routing:
        rental = db.query(NumberRental).filter(NumberRental.phone_number_id == routing.id).first()
        if rental and rental.status != "RELEASED":
            rental.status = "RELEASED"
            rental.released_at = svc.utcnow()
        retire_routing(db, routing, current.id)
    current.status = "ENDED"
    current.released_at = svc.utcnow()
    current.ended_by = actor.label
    current.end_reason = reason
    pn.internal_status = "AVAILABLE"
    pn.trunk_id = None
    if reason == "LAPSED":
        client = db.get(Client, current.client_id)
        pn.attention = (f"Returned to the pool after {client.name if client else 'the client'}'s rent lapsed. "
                        "Assign it to someone else or release it to stop paying for it.")
    op.operation_status = "SUCCEEDED"
    db.commit()
    logger.info("%s unassigned %s from client %s (%s)", actor.label, pn.e164, current.client_id, reason)
    return pn
