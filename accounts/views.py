
import hashlib
import json
import logging
import random
import re

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
)
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import (
    Wallet,
    Transaction,
    GameSession,
    Referral,
    DailyTaskClaim,
)


User = get_user_model()
logger = logging.getLogger(__name__)

DEPOSIT_ADDRESS = "0x4139d16c595fDEdbf0df47b171D11005B360e6C7"
REVIEW_HOURS = 2


# ============================================================
# NOTIFICACIONES
# ============================================================

def notify_admin(subject, body):
    """Envía un correo al administrador si el SMTP está configurado."""
    recipient = (
        getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "")
        or getattr(settings, "EMAIL_HOST_USER", "")
    )

    if not recipient:
        logger.warning(
            "No se envió el correo: configura ADMIN_NOTIFICATION_EMAIL."
        )
        return False

    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception(
            "No se pudo enviar el correo de notificación al administrador."
        )
        return False


# ============================================================
# PÁGINA PRINCIPAL Y UTILIDADES
# ============================================================

@ensure_csrf_cookie
def home(request):
    """Muestra la página y conserva el código de referido recibido."""
    code = (request.GET.get("ref") or "").strip().upper()

    if code and len(code) <= 16:
        request.session["pending_referral_code"] = code

    return render(request, "index.html")


def json_body(request):
    """Devuelve un diccionario JSON o None si el JSON es inválido."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def normalize_email(email):
    return (email or "").strip().lower()


def user_payload(user):
    """Construye los datos públicos básicos de un usuario."""
    wallet, _ = Wallet.objects.get_or_create(user=user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "balance": str(wallet.balance),
        "total_invested": str(wallet.total_invested),
        "vip_active": wallet.vip_active,
        "referral_code": wallet.referral_code,
    }


def transaction_payload(tx):
    """Convierte un movimiento en un diccionario serializable."""
    ready_at = None

    if (
        tx.status == Transaction.Status.PENDING
        and tx.kind in (
            Transaction.Kind.DEPOSIT,
            Transaction.Kind.WITHDRAWAL,
        )
    ):
        ready_at = tx.created_at + timedelta(hours=REVIEW_HOURS)

    now = timezone.now()

    return {
        "id": tx.id,
        "kind": tx.kind,
        "status": tx.status,
        "amount": str(tx.amount),
        "description": tx.description,
        "created_at": tx.created_at.isoformat(),
        "txid": tx.txid,
        "destination": tx.destination,
        "review_ready_at": ready_at.isoformat() if ready_at else None,
        "review_wait_seconds": (
            max(0, int((ready_at - now).total_seconds()))
            if ready_at
            else 0
        ),
    }


# ============================================================
# REGISTRO
# ============================================================

@require_POST
def register(request):
    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "La solicitud no contiene JSON válido."},
            status=400,
        )

    username = (data.get("username") or "").strip()
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not isinstance(password, str):
        password = ""

    errors = {}

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        errors["username"] = [
            "El nombre debe tener entre 3 y 30 caracteres y solo puede "
            "incluir letras, números, punto, guion o guion bajo."
        ]

    if (
        not email
        or len(email) > 254
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
    ):
        errors["email"] = [
            "Introduce un correo electrónico válido."
        ]

    if len(password) < 8:
        errors["password"] = [
            "La contraseña debe tener al menos 8 caracteres."
        ]

    if username and User.objects.filter(
        username__iexact=username
    ).exists():
        errors["username"] = [
            "Ese nombre de usuario ya está registrado."
        ]

    if email and User.objects.filter(
        email__iexact=email
    ).exists():
        errors["email"] = [
            "Ese correo electrónico ya está siendo usado por otra cuenta."
        ]

    if errors:
        duplicate = any(
            "registrado" in str(messages).lower()
            or "usado" in str(messages).lower()
            for messages in errors.values()
        )

        return JsonResponse(
            {
                "message": "Revisa los datos del formulario.",
                "errors": errors,
            },
            status=409 if duplicate else 400,
        )

    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse(
            {
                "message": (
                    "La contraseña no cumple los requisitos de seguridad."
                ),
                "errors": {"password": list(exc.messages)},
            },
            status=400,
        )

    with db_transaction.atomic():
        # Repetimos la comprobación dentro de la transacción.
        # Las restricciones de unicidad del modelo siguen siendo necesarias.
        if User.objects.filter(username__iexact=username).exists():
            return JsonResponse(
                {
                    "message": "Ese nombre de usuario ya está registrado.",
                    "errors": {
                        "username": ["Nombre de usuario duplicado."]
                    },
                },
                status=409,
            )

        if User.objects.filter(email__iexact=email).exists():
            return JsonResponse(
                {
                    "message": "Ese correo electrónico ya está registrado.",
                    "errors": {
                        "email": ["Correo electrónico duplicado."]
                    },
                },
                status=409,
            )

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

        Wallet.objects.get_or_create(user=user)

        code = (
            request.session.pop("pending_referral_code", "") or ""
        ).strip().upper()

        if code:
            inviter_wallet = (
                Wallet.objects.select_for_update()
                .filter(referral_code=code)
                .select_related("user")
                .first()
            )

            if (
                inviter_wallet
                and inviter_wallet.user_id != user.pk
                and not Referral.objects.filter(invited=user).exists()
            ):
                reward = Decimal("1.00")

                inviter_wallet.balance += reward
                inviter_wallet.save(update_fields=["balance"])

                tx = Transaction.objects.create(
                    user=inviter_wallet.user,
                    kind=Transaction.Kind.ADMIN_ADJUSTMENT,
                    status=Transaction.Status.APPROVED,
                    amount=reward,
                    description=(
                        f"Recompensa de referido por registro de "
                        f"{user.username}"
                    ),
                    reviewed_at=timezone.now(),
                )

                Referral.objects.create(
                    inviter=inviter_wallet.user,
                    invited=user,
                    reward=reward,
                    status=Referral.Status.CREDITED,
                    credited_at=timezone.now(),
                    transaction=tx,
                )

    login(request, user)

    return JsonResponse(
        {
            "message": "La cuenta se creó correctamente.",
            "user": user_payload(user),
        },
        status=201,
    )


# ============================================================
# INICIO Y CIERRE DE SESIÓN
# ============================================================

@require_POST
def login_view(request):
    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "La solicitud no contiene JSON válido."},
            status=400,
        )

    email = normalize_email(data.get("email"))
    password = data.get("password") or ""

    if not isinstance(password, str):
        password = ""

    if not email or not password:
        return JsonResponse(
            {
                "message": (
                    "Introduce tu correo electrónico y contraseña."
                )
            },
            status=400,
        )

    user_by_email = User.objects.filter(
        email__iexact=email
    ).first()

    if user_by_email is None:
        return JsonResponse(
            {
                "message": (
                    "No existe una cuenta con ese correo electrónico."
                )
            },
            status=401,
        )

    user = authenticate(
        request,
        username=user_by_email.username,
        password=password,
    )

    if user is None:
        return JsonResponse(
            {"message": "La contraseña no es correcta."},
            status=401,
        )

    login(request, user)

    return JsonResponse(
        {
            "message": "Sesión iniciada correctamente.",
            "user": user_payload(user),
        }
    )


@require_POST
def logout_view(request):
    logout(request)

    return JsonResponse(
        {"message": "Sesión cerrada correctamente."}
    )


@require_GET
def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False})

    return JsonResponse(
        {
            "authenticated": True,
            "user": user_payload(request.user),
        }
    )


# ============================================================
# PLANES Y LÍMITES DE RETIRO
# ============================================================

def withdrawal_limit_for(total_invested):
    """
    Calcula el límite máximo de retiro según la inversión acumulada.
    Es una función auxiliar, no una vista HTTP.
    """
    amount = Decimal(str(total_invested or "0.00"))

    if amount >= Decimal("180.00"):
        return Decimal("40.00")

    if amount >= Decimal("120.00"):
        return Decimal("20.00")

    if amount >= Decimal("60.00"):
        return Decimal("10.00")

    if amount >= Decimal("20.00"):
        return Decimal("4.00")

    return Decimal("2.00")


def investment_plan_for(total_invested):
    amount = Decimal(str(total_invested or "0.00"))

    if amount >= Decimal("180.00"):
        return {
            "name": "VIP 180",
            "investment": "180.00",
            "withdrawal_limit": "40.00",
        }

    if amount >= Decimal("120.00"):
        return {
            "name": "VIP 120",
            "investment": "120.00",
            "withdrawal_limit": "20.00",
        }

    if amount >= Decimal("60.00"):
        return {
            "name": "VIP 60",
            "investment": "60.00",
            "withdrawal_limit": "10.00",
        }

    if amount >= Decimal("20.00"):
        return {
            "name": "VIP 20",
            "investment": "20.00",
            "withdrawal_limit": "4.00",
        }

    if amount >= Decimal("10.00"):
        return {
            "name": "VIP 10",
            "investment": "10.00",
            "withdrawal_limit": "2.00",
        }

    return {
        "name": "Sin plan",
        "investment": "0.00",
        "withdrawal_limit": "0.00",
    }


# ============================================================
# ESTADO DE LA CUENTA
# ============================================================

@require_GET
def account_state(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    txs = Transaction.objects.filter(
        user=request.user
    ).order_by("-created_at")[:50]

    last_withdrawal = wallet.last_withdrawal_at

    next_withdrawal = (
        last_withdrawal + timedelta(hours=24)
        if last_withdrawal
        else None
    )

    now = timezone.now()

    referral_stats = Referral.objects.filter(
        inviter=request.user,
        status=Referral.Status.CREDITED,
    ).aggregate(total=Sum("reward"))

    referral_rewards = referral_stats["total"] or Decimal("0.00")

    return JsonResponse(
        {
            "wallet": {
                "balance": str(wallet.balance),
                "total_invested": str(wallet.total_invested),
                "vip_active": wallet.vip_active,
                "initial_investment_met": (
                    wallet.total_invested >= Decimal("10.00")
                ),
                "next_withdrawal_at": (
                    next_withdrawal.isoformat()
                    if next_withdrawal
                    else None
                ),
                "withdrawal_wait_seconds": (
                    max(
                        0,
                        int((next_withdrawal - now).total_seconds()),
                    )
                    if next_withdrawal
                    else 0
                ),
                "withdrawal_limit": str(
                    withdrawal_limit_for(wallet.total_invested)
                ),
                "investment_plan": investment_plan_for(
                    wallet.total_invested
                ),
                "referral_code": wallet.referral_code,
                "referral_count": Referral.objects.filter(
                    inviter=request.user,
                    status=Referral.Status.CREDITED,
                ).count(),
                "referral_rewards": str(referral_rewards),
            },
            "daily_tasks": daily_tasks_payload(
                request.user,
                wallet,
            ),
            "transactions": [
                transaction_payload(tx)
                for tx in txs
            ],
        }
    )


# ============================================================
# TAREAS DIARIAS
# ============================================================

DAILY_TASKS = [
    (
        "Revisa el panel de seguridad y lee las recomendaciones",
        "security",
    ),
    (
        "Actualiza tu perfil y comprueba que el correo sea correcto",
        "profile",
    ),
    (
        "Lee las condiciones de recompensas y retiros",
        "terms",
    ),
    (
        "Consulta tu historial de movimientos",
        "history",
    ),
    (
        "Completa la revisión diaria de tu campamento",
        "camp",
    ),
    (
        "Repasa cómo proteger tu cuenta y contraseña",
        "account",
    ),
    (
        "Revisa el estado de tus misiones",
        "missions",
    ),
    (
        "Consulta las normas para evitar enlaces sospechosos",
        "links",
    ),
    (
        "Comprueba los datos de tu billetera",
        "wallet",
    ),
    (
        "Lee el resumen de tu membresía",
        "membership",
    ),
]


def daily_tasks_payload(user, wallet):
    today = timezone.localdate()

    count = 4 if wallet.vip_active else 2
    reward = (
        Decimal("5.00")
        if wallet.vip_active
        else Decimal("1.00")
    )

    seed = f"{user.pk}:{today.isoformat()}".encode()
    offset = int(
        hashlib.sha256(seed).hexdigest()[:8],
        16,
    ) % len(DAILY_TASKS)

    ordered = DAILY_TASKS[offset:] + DAILY_TASKS[:offset]

    claims = {
        claim.slot: claim
        for claim in DailyTaskClaim.objects.filter(
            user=user,
            task_date=today,
        )
    }

    tasks = []

    for slot in range(1, count + 1):
        title = ordered[slot - 1][0]
        claim = claims.get(slot)

        tasks.append(
            {
                "slot": slot,
                "title": title,
                "reward": str(reward),
                "completed": bool(claim),
                "completed_at": (
                    claim.completed_at.isoformat()
                    if claim
                    else None
                ),
            }
        )

    return {
        "date": today.isoformat(),
        "plan": "VIP" if wallet.vip_active else "Normal",
        "daily_limit": count,
        "reward_per_task": str(reward),
        "tasks": tasks,
        "notice": (
            "La tarea se registra cuando pulsas completar. "
            "Las actividades informativas no son una prueba "
            "independiente de una acción externa."
        ),
    }


@require_GET
def daily_tasks(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    return JsonResponse(
        daily_tasks_payload(request.user, wallet)
    )


@require_POST
def daily_task_claim(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "JSON inválido."},
            status=400,
        )

    try:
        slot = int(data.get("slot"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"message": "Tarea no válida."},
            status=400,
        )

    today = timezone.localdate()

    with db_transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user=request.user
        )

        payload = daily_tasks_payload(request.user, wallet)

        task = next(
            (
                item
                for item in payload["tasks"]
                if item["slot"] == slot
            ),
            None,
        )

        if not task:
            return JsonResponse(
                {
                    "message": (
                        "Esta tarea no pertenece al plan actual."
                    )
                },
                status=400,
            )

        if task["completed"]:
            return JsonResponse(
                {"message": "Esta tarea ya fue reclamada hoy."},
                status=409,
            )

        title = task["title"]
        reward = Decimal(task["reward"])

        wallet.balance += reward
        wallet.save(update_fields=["balance"])

        tx = Transaction.objects.create(
            user=request.user,
            kind=Transaction.Kind.GAME_REWARD,
            status=Transaction.Status.APPROVED,
            amount=reward,
            description=f"Recompensa tarea diaria: {title}",
            reviewed_at=timezone.now(),
        )

        DailyTaskClaim.objects.create(
            user=request.user,
            task_date=today,
            slot=slot,
            title=title,
            reward=reward,
            transaction=tx,
        )

    return JsonResponse(
        {
            "message": "Tarea registrada y recompensa acreditada.",
            "reward": str(reward),
            "balance": str(wallet.balance),
        }
    )


# ============================================================
# DEPÓSITOS
# ============================================================

@require_POST
def deposit_request(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "JSON inválido."},
            status=400,
        )

    try:
        amount = Decimal(
            str(data.get("amount", "10"))
        ).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return JsonResponse(
            {"message": "Importe no válido."},
            status=400,
        )

    if not amount.is_finite():
        return JsonResponse(
            {"message": "Importe no válido."},
            status=400,
        )

    if amount < Decimal("10.00"):
        return JsonResponse(
            {
                "message": (
                    "La inversión inicial mínima es de 10 USDT."
                )
            },
            status=400,
        )

    if amount > Decimal("1000000.00"):
        return JsonResponse(
            {
                "message": (
                    "El importe supera el máximo permitido; "
                    "contacta con administración."
                )
            },
            status=400,
        )

    if Transaction.objects.filter(
        user=request.user,
        kind=Transaction.Kind.DEPOSIT,
        status=Transaction.Status.PENDING,
    ).exists():
        return JsonResponse(
            {"message": "Ya tienes un depósito pendiente de revisión."},
            status=409,
        )

    tx = Transaction.objects.create(
        user=request.user,
        kind=Transaction.Kind.DEPOSIT,
        amount=amount,
        destination=DEPOSIT_ADDRESS,
        description=(
            "Solicitud de depósito USDT BEP20 "
            "pendiente de verificación manual"
        ),
    )

    ready = tx.created_at + timedelta(hours=REVIEW_HOURS)

    subject = (
        f"[bear.litle] Depósito pendiente #{tx.id} — {amount} USDT"
    )

    body = (
        "Se ha registrado una solicitud de depósito en bear.litle.\n\n"
        f"Usuario: {request.user.username}\n"
        f"Correo: {request.user.email}\n"
        f"ID usuario: {request.user.pk}\n"
        f"Importe declarado: {amount} USDT\n"
        "Red: BEP20 / BNB Smart Chain\n"
        f"Wallet receptora: {DEPOSIT_ADDRESS}\n"
        f"Solicitud: #{tx.id}\n"
        f"Fecha: {timezone.localtime(tx.created_at).isoformat()}\n"
        f"Revisión programada desde: "
        f"{timezone.localtime(ready).isoformat()}\n\n"
        "Verifica la transferencia y ajusta el importe real en "
        "Django Admin antes de aprobar. La solicitud por sí sola "
        "no confirma un pago on-chain."
    )

    sent = notify_admin(subject, body)

    if sent:
        message = (
            "Solicitud registrada y correo enviado al administrador. "
            "El saldo se acreditará solo tras verificar la transferencia; "
            "el plazo estimado de revisión es de hasta 2 horas."
        )
    else:
        message = (
            "Solicitud registrada, pero no se pudo enviar el correo. "
            "La cuenta de correo del administrador debe configurarse "
            "en el servidor; contacta con administración por otro medio."
        )

    return JsonResponse(
        {
            "message": message,
            "email_notification_sent": sent,
            "review_ready_at": ready.isoformat(),
            "transaction": transaction_payload(tx),
        },
        status=201,
    )


# ============================================================
# RETIROS
# ============================================================

@require_POST
def withdraw_request(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "JSON inválido."},
            status=400,
        )

    try:
        amount = Decimal(
            str(data.get("amount", "0"))
        ).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return JsonResponse(
            {"message": "Importe no válido."},
            status=400,
        )

    if not amount.is_finite() or amount <= Decimal("0.00"):
        return JsonResponse(
            {"message": "El importe debe ser mayor que cero."},
            status=400,
        )

    destination = (data.get("destination") or "").strip()

    if amount < Decimal("2.00"):
        return JsonResponse(
            {"message": "El retiro mínimo es de 2 USDT."},
            status=400,
        )

    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", destination):
        return JsonResponse(
            {"message": "Introduce una dirección BEP20 válida."},
            status=400,
        )

    with db_transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user=request.user
        )

        if wallet.total_invested < Decimal("10.00"):
            return JsonResponse(
                {
                    "message": (
                        "Debes completar una inversión inicial "
                        "verificada de 10 USDT antes de retirar."
                    )
                },
                status=403,
            )

        if Transaction.objects.filter(
            user=request.user,
            kind=Transaction.Kind.WITHDRAWAL,
            status=Transaction.Status.PENDING,
        ).exists():
            return JsonResponse(
                {
                    "message": (
                        "Ya tienes un retiro pendiente de revisión. "
                        "Espera a que se procese antes de solicitar otro."
                    )
                },
                status=409,
            )

        if (
            wallet.last_withdrawal_at
            and timezone.now()
            < wallet.last_withdrawal_at + timedelta(hours=24)
        ):
            ready = wallet.last_withdrawal_at + timedelta(hours=24)

            return JsonResponse(
                {
                    "message": (
                        "Aún está activo el período de espera "
                        "de 24 horas."
                    ),
                    "next_withdrawal_at": ready.isoformat(),
                },
                status=429,
            )

        limit = withdrawal_limit_for(wallet.total_invested)

        if amount > limit:
            return JsonResponse(
                {
                    "message": (
                        f"El límite por retiro para tu cuenta actual "
                        f"es {limit} USDT."
                    )
                },
                status=400,
            )

        available_balance = wallet.balance

        if amount > available_balance:
            return JsonResponse(
                {
                    "message": (
                        "Saldo insuficiente. No puedes retirar "
                        "más de tu saldo disponible."
                    ),
                    "available_balance": str(available_balance),
                    "requested_amount": str(amount),
                },
                status=400,
            )

        balance_after_withdrawal = (
            available_balance - amount
        ).quantize(Decimal("0.01"))

        if balance_after_withdrawal < Decimal("0.00"):
            return JsonResponse(
                {
                    "message": (
                        "El retiro no puede dejar el saldo negativo."
                    )
                },
                status=400,
            )

        wallet.balance = balance_after_withdrawal
        wallet.save(update_fields=["balance"])

        tx = Transaction.objects.create(
            user=request.user,
            kind=Transaction.Kind.WITHDRAWAL,
            amount=amount,
            destination=destination,
            description="Retiro pendiente de revisión y envío manual",
        )

    ready = tx.created_at + timedelta(hours=REVIEW_HOURS)

    subject = (
        f"[bear.litle] Retiro pendiente #{tx.id} — {amount} USDT"
    )

    body = (
        "Se ha registrado una solicitud de retiro.\n\n"
        f"Usuario: {request.user.username}\n"
        f"Correo: {request.user.email}\n"
        f"ID usuario: {request.user.pk}\n"
        f"Importe: {amount} USDT\n"
        f"Destino BEP20: {destination}\n"
        f"Solicitud: #{tx.id}\n"
        f"Recibida: {timezone.localtime(tx.created_at).isoformat()}\n"
        f"No procesar antes de: "
        f"{timezone.localtime(ready).isoformat()}\n\n"
        "Realiza la transferencia manualmente y confirma la solicitud "
        "en Django Admin cuando corresponda."
    )

    sent = notify_admin(subject, body)

    if sent:
        message = (
            "Solicitud de retiro registrada y correo enviado al "
            "administrador. Podrá procesarse después del plazo "
            "de revisión de 2 horas."
        )
    else:
        message = (
            "Solicitud de retiro registrada, pero no se pudo enviar "
            "el correo. La cuenta de correo del administrador debe "
            "configurarse en el servidor."
        )

    return JsonResponse(
        {
            "message": message,
            "email_notification_sent": sent,
            "review_ready_at": ready.isoformat(),
            "balance_after_withdrawal": str(
                balance_after_withdrawal
            ),
            "transaction": transaction_payload(tx),
        },
        status=201,
    )


# ============================================================
# MINIJUEGOS
# ============================================================

@require_POST
def game_start(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "JSON inválido."},
            status=400,
        )

    game_type = data.get("game_type", "captcha")

    if game_type not in ("captcha", "loading", "memory"):
        return JsonResponse(
            {"message": "Minijuego no válido."},
            status=400,
        )

    a = random.randint(2, 9)
    b = random.randint(2, 9)
    wait = random.choice([10, 15, 20, 30, 45, 60])

    if game_type == "captcha":
        question = f"¿Cuánto es {a} + {b}?"
        answer = str(a + b)
    elif game_type == "loading":
        question = "Escribe LISTO cuando termine la barra."
        answer = "LISTO"
    else:
        question = "Escribe la palabra OSITO en mayúsculas."
        answer = "OSITO"

    game = GameSession.objects.create(
        user=request.user,
        game_type=game_type,
        question=question,
        answer=answer,
        wait_seconds=wait,
    )

    return JsonResponse(
        {
            "game_id": game.id,
            "game_type": game_type,
            "question": question,
            "wait_seconds": wait,
            "reward": str(game.reward),
            "started_at": game.started_at.isoformat(),
        }
    )


@require_POST
def game_claim(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"message": "Inicia sesión."},
            status=401,
        )

    data = json_body(request)

    if data is None:
        return JsonResponse(
            {"message": "JSON inválido."},
            status=400,
        )

    try:
        game_id = int(data.get("game_id"))
    except (TypeError, ValueError):
        return JsonResponse(
            {"message": "Minijuego no encontrado."},
            status=404,
        )

    with db_transaction.atomic():
        try:
            game = GameSession.objects.select_for_update().get(
                id=game_id,
                user=request.user,
            )
        except GameSession.DoesNotExist:
            return JsonResponse(
                {"message": "Minijuego no encontrado."},
                status=404,
            )

        if game.claimed_at:
            return JsonResponse(
                {"message": "Este minijuego ya fue reclamado."},
                status=409,
            )

        if timezone.now() < (
            game.started_at + timedelta(seconds=game.wait_seconds)
        ):
            return JsonResponse(
                {
                    "message": (
                        "Todavía no ha terminado el tiempo de espera."
                    )
                },
                status=429,
            )

        submitted_answer = str(
            data.get("answer", "")
        ).strip().upper()

        if submitted_answer != game.answer.upper():
            return JsonResponse(
                {"message": "Respuesta incorrecta."},
                status=400,
            )

        today = timezone.localdate()

        already = Transaction.objects.filter(
            user=request.user,
            kind=Transaction.Kind.GAME_REWARD,
            status=Transaction.Status.APPROVED,
            created_at__date=today,
        ).count()

        if already >= 10:
            return JsonResponse(
                {
                    "message": (
                        "Has alcanzado el máximo de 10 recompensas "
                        "de minijuegos por hoy."
                    )
                },
                status=429,
            )

        wallet, _ = Wallet.objects.select_for_update().get_or_create(
            user=request.user
        )

        wallet.balance += game.reward
        wallet.save(update_fields=["balance"])

        game.claimed_at = timezone.now()
        game.save(update_fields=["claimed_at"])

        tx = Transaction.objects.create(
            user=request.user,
            kind=Transaction.Kind.GAME_REWARD,
            status=Transaction.Status.APPROVED,
            amount=game.reward,
            description=f"Recompensa de minijuego: {game.game_type}",
        )

    return JsonResponse(
        {
            "message": "Recompensa acreditada.",
            "reward": str(game.reward),
            "balance": str(wallet.balance),
            "transaction": transaction_payload(tx),
        }
    )
