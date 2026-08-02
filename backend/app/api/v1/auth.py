from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.integrations.email import EmailDeliveryError, SMTPEmailSender
from app.schemas.auth import (
    EmailVerificationRequest,
    LoginRequest,
    MessageResponse,
    PasswordChangeRequest,
    RegistrationRequest,
    ResendVerificationRequest,
)
from app.schemas.user import UserRead
from app.services.auth import (
    AccountLockedError,
    AuthService,
    EmailNotVerifiedError,
    InvalidCredentialsError,
)
from app.services.registration import (
    InvalidVerificationTokenError,
    RegistrationConflictError,
    RegistrationService,
    SignupDisabledError,
)

router = APIRouter()


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest, response: Response, db: DbSession, settings: AppSettings
) -> UserRead:
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


@router.post(
    "/register", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
async def register(
    payload: RegistrationRequest, db: DbSession, settings: AppSettings
) -> MessageResponse:
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
    payload: ResendVerificationRequest, db: DbSession, settings: AppSettings
) -> MessageResponse:
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
    response: Response,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> MessageResponse:
    try:
        await AuthService(db, settings).change_password(
            user, payload.current_password, payload.new_password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect") from exc
    response.delete_cookie(settings.cookie_name, path="/")
    return MessageResponse(message="Password changed; please sign in again")
