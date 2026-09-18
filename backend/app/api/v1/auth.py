import json
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.integrations.email import EmailDeliveryError, SMTPEmailSender
from app.schemas.auth import (
    AccountDeletionRequest,
    AccountEmailRequest,
    AccountPasswordRequest,
    EmailVerificationRequest,
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegistrationRequest,
    ResendVerificationRequest,
)
from app.schemas.user import UserRead
from app.services.account_data import (
    AccountDataService,
    AccountPasswordError,
    LastAdministratorError,
)
from app.services.auth import (
    AccountLockedError,
    AuthService,
    EmailNotVerifiedError,
    InvalidCredentialsError,
)
from app.services.auth_rate_limit import AuthRateLimiter, AuthRateLimitExceeded
from app.services.password_recovery import (
    InvalidPasswordResetTokenError,
    PasswordRecoveryService,
)
from app.services.registration import (
    InvalidVerificationTokenError,
    RegistrationConflictError,
    RegistrationService,
    SignupDisabledError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _throttle(
    db: DbSession,
    settings: AppSettings,
    request: Request,
    action: str,
    *,
    subject: str | None = None,
    ip_limit: int,
    subject_limit: int | None = None,
    window_minutes: int | None = None,
) -> None:
    try:
        await AuthRateLimiter(db, settings).check(
            action,
            request,
            subject=subject,
            ip_limit=ip_limit,
            subject_limit=subject_limit,
            window_minutes=window_minutes,
        )
    except AuthRateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> UserRead:
    await _throttle(
        db,
        settings,
        request,
        "login",
        subject=payload.username,
        ip_limit=settings.auth_login_ip_limit,
        subject_limit=settings.auth_login_account_limit,
    )
    try:
        user, token = await AuthService(db, settings).login(payload.username, payload.password)
    except AccountLockedError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Account temporarily locked"
        ) from exc
    except EmailNotVerifiedError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email address before signing in"
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password") from exc

    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return UserRead.model_validate(user)


@router.post("/register", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def register(
    payload: RegistrationRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "register",
        ip_limit=settings.auth_registration_ip_limit,
        window_minutes=60,
    )
    service = RegistrationService(db, settings, SMTPEmailSender(settings))
    try:
        await service.register(payload.username, str(payload.email), payload.password)
    except SignupDisabledError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Registration is unavailable") from exc
    except RegistrationConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Username or email is already registered"
        ) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Account created, but the verification email could not be sent. Try resending it.",
        ) from exc
    return MessageResponse(message="Check your email to verify your account")


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: EmailVerificationRequest, db: DbSession, settings: AppSettings
) -> MessageResponse:
    try:
        await RegistrationService(db, settings, SMTPEmailSender(settings)).verify(payload.token)
    except InvalidVerificationTokenError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Verification link is invalid or has expired"
        ) from exc
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "verification-email",
        subject=str(payload.email),
        ip_limit=settings.auth_email_ip_limit,
        subject_limit=settings.auth_email_account_limit,
        window_minutes=60,
    )
    try:
        await RegistrationService(db, settings, SMTPEmailSender(settings)).resend(
            str(payload.email)
        )
    except EmailDeliveryError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Verification email could not be sent"
        ) from exc
    return MessageResponse(
        message="If that account is awaiting verification, a new email has been sent"
    )


@router.post(
    "/account-email",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def set_account_email(
    payload: AccountEmailRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "account-email",
        subject=str(user.id),
        ip_limit=settings.auth_email_ip_limit,
        subject_limit=settings.auth_email_account_limit,
        window_minutes=60,
    )
    try:
        await RegistrationService(db, settings, SMTPEmailSender(settings)).set_account_email(
            user, str(payload.email)
        )
    except RegistrationConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from exc
    except EmailDeliveryError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Email saved, but the verification message could not be sent",
        ) from exc
    return MessageResponse(message="Check your inbox to verify the email address")


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request, response: Response, db: DbSession, settings: AppSettings
) -> MessageResponse:
    token = request.cookies.get(settings.cookie_name)
    if token:
        await AuthService(db, settings).logout(token)
    response.delete_cookie(settings.cookie_name, path="/")
    return MessageResponse(message="Signed out")


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post("/password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "account-reauth",
        subject=str(user.id),
        ip_limit=settings.auth_login_ip_limit,
        subject_limit=settings.auth_login_account_limit,
    )
    try:
        await AuthService(db, settings).change_password(
            user, payload.current_password, payload.new_password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect") from exc
    response.delete_cookie(settings.cookie_name, path="/")
    return MessageResponse(message="Password changed; please sign in again")


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "password-reset-email",
        subject=str(payload.email),
        ip_limit=settings.auth_email_ip_limit,
        subject_limit=settings.auth_email_account_limit,
        window_minutes=60,
    )
    try:
        await PasswordRecoveryService(db, settings, SMTPEmailSender(settings)).request(
            str(payload.email)
        )
    except EmailDeliveryError:
        logger.warning("Password reset email delivery failed")
    return MessageResponse(
        message="If an account exists for that email, a reset link has been sent"
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "password-reset-confirm",
        ip_limit=settings.auth_email_ip_limit,
        window_minutes=60,
    )
    try:
        await PasswordRecoveryService(db, settings, SMTPEmailSender(settings)).reset(
            payload.token, payload.new_password
        )
    except InvalidPasswordResetTokenError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Reset link is invalid or has expired"
        ) from exc
    response.delete_cookie(settings.cookie_name, path="/")
    return MessageResponse(message="Password reset. You can now sign in.")


@router.post("/account/export")
async def export_account_data(
    payload: AccountPasswordRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> Response:
    await _throttle(
        db,
        settings,
        request,
        "account-reauth",
        subject=str(user.id),
        ip_limit=settings.auth_login_ip_limit,
        subject_limit=settings.auth_login_account_limit,
    )
    try:
        exported = await AccountDataService(db).export(user, payload.current_password)
    except AccountPasswordError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect") from exc
    filename = f"northstar-account-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(exported, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/account", response_model=MessageResponse)
async def delete_account(
    payload: AccountDeletionRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    await _throttle(
        db,
        settings,
        request,
        "account-reauth",
        subject=str(user.id),
        ip_limit=settings.auth_login_ip_limit,
        subject_limit=settings.auth_login_account_limit,
    )
    try:
        await AccountDataService(db).delete(user, payload.current_password)
    except AccountPasswordError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect") from exc
    except LastAdministratorError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Create another administrator before deleting this account",
        ) from exc
    response.delete_cookie(settings.cookie_name, path="/")
    return MessageResponse(message="Account permanently deleted")
