"""Семья, участники, приглашения (архитектура 7.3)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import Auth, get_auth, get_db, get_household_ctx, request_id, require_if_match, set_etag
from app.core.context import RequestContext
from app.core.email import send_email
from app.crud import household as hh
from app.crud._common import build_context
from app.schemas.auth import AcceptedOut, PasswordIn, TokenIn
from app.schemas.household import (
    HouseholdCreate, HouseholdOut, HouseholdPatch, InvitationCreate, InvitationOut, MemberOut, TransferOwnerIn,
)
from app.schemas.user import MembershipOut

router = APIRouter(tags=["households"])


@router.post("/households", status_code=201, response_model=HouseholdOut, operation_id="households_create")
def create_household(body: HouseholdCreate, response: Response, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    household, _ = hh.create_household(db, auth.user.id, body)
    out = HouseholdOut.model_validate(household)
    db.commit()
    set_etag(response, out.version)
    return out


# ВАЖНО: /households/current объявлен раньше /households/{h}, иначе "current" попытаются разобрать как UUID
@router.get("/households/current", response_model=HouseholdOut | None, operation_id="households_current")
def current_household(response: Response, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    found = hh.get_current_household(db, auth.user.id)
    db.commit()
    if found is None:
        return None
    out = HouseholdOut.model_validate(found[0])
    set_etag(response, out.version)
    return out


@router.patch("/households/{h}", response_model=HouseholdOut, operation_id="households_patch")
def patch_household(
    body: HouseholdPatch, response: Response, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    household = hh.update_household(db, ctx, body, version)
    out = HouseholdOut.model_validate(household)
    db.commit()
    set_etag(response, out.version)
    return out


@router.delete("/households/{h}", status_code=204, operation_id="households_delete")
def delete_household(
    body: PasswordIn, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    hh.delete_household(db, ctx, body.password, version)
    db.commit()
    return Response(status_code=204)


@router.get("/households/{h}/members", response_model=list[MemberOut], operation_id="members_list")
def list_members(ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    rows = hh.list_members(db, ctx)
    out = [
        MemberOut(id=m.id, household_id=m.household_id, user_id=m.user_id, display_name=name,
                  role=m.role, joined_at=m.joined_at)
        for m, name in rows
    ]
    db.commit()
    return out


@router.delete("/households/{h}/members/{member_id}", status_code=204, operation_id="members_remove")
def remove_member(member_id: uuid.UUID, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    hh.remove_member(db, ctx, member_id)
    db.commit()
    return Response(status_code=204)


@router.post("/households/{h}/leave", status_code=204, operation_id="households_leave")
def leave(ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    hh.leave_household(db, ctx)
    db.commit()
    return Response(status_code=204)


@router.post("/households/{h}/transfer-owner", response_model=HouseholdOut, operation_id="households_transfer_owner")
def transfer_owner(body: TransferOwnerIn, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    household = hh.transfer_owner(db, ctx, body.target_member_id, body.password)
    out = HouseholdOut.model_validate(household)
    db.commit()
    return out


# ------------------------------------------------------------------ приглашения
@router.post("/households/{h}/invitations", status_code=201, response_model=InvitationOut, operation_id="invitations_create")
def create_invitation(
    body: InvitationCreate, tasks: BackgroundTasks,
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    invitation, token = hh.create_invitation(db, ctx, body.email)
    out = InvitationOut.model_validate(invitation)
    db.commit()
    tasks.add_task(send_email, "invitation", invitation.email_normalized, {"token": token})
    return out  # токен в ответ не попадает — только в письмо


@router.get("/households/{h}/invitations", response_model=list[InvitationOut], operation_id="invitations_list")
def list_invitations(ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = [InvitationOut.model_validate(i) for i in hh.list_invitations(db, ctx)]
    db.commit()
    return out


@router.delete("/households/{h}/invitations/{invitation_id}", status_code=204, operation_id="invitations_cancel")
def cancel_invitation(invitation_id: uuid.UUID, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    hh.cancel_invitation(db, ctx, invitation_id)
    db.commit()
    return Response(status_code=204)


@router.post("/invitations/accept", response_model=MembershipOut, operation_id="invitations_accept")
def accept_invitation(body: TokenIn, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    member, _ = hh.accept_invitation(db, auth.user.id, body.token)
    out = MembershipOut.model_validate(member)
    db.commit()
    return out
