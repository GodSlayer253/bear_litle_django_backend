import json
import re
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.conf import settings
from django.core.mail import send_mail
import logging
from django.db import transaction as db_transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import random
from .models import Wallet, Transaction, GameSession
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

User = get_user_model()
logger = logging.getLogger(__name__)
DEPOSIT_ADDRESS = "0x4139d16c595fDEdbf0df47b171D11005B360e6C7"
REVIEW_HOURS = 2

def notify_admin(subject, body):
    """Notifica por SMTP si está configurado; si no, Django usa el backend de consola."""
    recipient = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", "") or getattr(settings, "EMAIL_HOST_USER", "")
    if not recipient:
        logger.warning("No se envió correo: configura ADMIN_NOTIFICATION_EMAIL y el SMTP de Gmail.")
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
        return True
    except Exception:
        logger.exception("No se pudo enviar el correo de notificación al administrador.")
        return False

@ensure_csrf_cookie
def home(request):
    return render(request, "index.html")

def json_body(request):
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

def user_payload(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return {"id": user.id, "username": user.username, "email": user.email,
            "balance": str(wallet.balance), "total_invested": str(wallet.total_invested), "vip_active": wallet.vip_active}

def transaction_payload(tx):
    ready_at = tx.created_at + timedelta(hours=REVIEW_HOURS) if tx.status == Transaction.Status.PENDING and tx.kind in (Transaction.Kind.DEPOSIT, Transaction.Kind.WITHDRAWAL) else None
    now = timezone.now()
    return {"id": tx.id, "kind": tx.kind, "status": tx.status, "amount": str(tx.amount),
            "description": tx.description, "created_at": tx.created_at.isoformat(), "txid": tx.txid,
            "review_ready_at": ready_at.isoformat() if ready_at else None,
            "review_wait_seconds": max(0, int((ready_at-now).total_seconds())) if ready_at else 0}

def normalize_email(email):
    return (email or "").strip().lower()

@require_POST
def register(request):
    data = json_body(request)
    if data is None:
        return JsonResponse({"message": "La solicitud no contiene JSON válido."}, status=400)
    username = (data.get("username") or "").strip()
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""
    errors = {}
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        errors["username"] = ["El nombre debe tener entre 3 y 30 caracteres y solo puede incluir letras, números, punto, guion o guion bajo."]
    if not email or len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        errors["email"] = ["Introduce un correo electrónico válido."]
    if len(password) < 8:
        errors["password"] = ["La contraseña debe tener al menos 8 caracteres."]
    if username and User.objects.filter(username__iexact=username).exists():
        errors["username"] = ["Ese nombre de usuario ya está registrado."]
    if email and User.objects.filter(email__iexact=email).exists():
        errors["email"] = ["Ese correo electrónico ya está siendo usado por otra cuenta."]
    if errors:
        return JsonResponse({"message": "Revisa los datos del formulario.", "errors": errors}, status=409 if any("registrado" in str(v) or "usado" in str(v) for v in errors.values()) else 400)
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({"message": "La contraseña no cumple los requisitos de seguridad.", "errors": {"password": list(exc.messages)}}, status=400)
    user = User.objects.create_user(username=username, email=email, password=password)
    login(request, user)
    return JsonResponse({"message": "La cuenta se creó correctamente.", "user": user_payload(user)}, status=201)

@require_POST
def login_view(request):
    data = json_body(request)
    if data is None:
        return JsonResponse({"message": "La solicitud no contiene JSON válido."}, status=400)
    email = normalize_email(data.get("email"))
    password = data.get("password") or ""
    if not email or not password:
        return JsonResponse({"message": "Introduce tu correo electrónico y contraseña."}, status=400)
    user_by_email = User.objects.filter(email__iexact=email).first()
    if not user_by_email:
        return JsonResponse({"message": "No existe una cuenta con ese correo electrónico."}, status=401)
    user = authenticate(request, username=user_by_email.username, password=password)
    if user is None:
        return JsonResponse({"message": "La contraseña no es correcta."}, status=401)
    login(request, user)
    return JsonResponse({"message": "Sesión iniciada correctamente.", "user": user_payload(user)})

@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"message": "Sesión cerrada correctamente."})

@require_GET
def me(request):
    if not request.user.is_authenticated:
        return JsonResponse({"authenticated": False}, status=200)
    return JsonResponse({"authenticated": True, "user": user_payload(request.user)})

@require_GET
def account_state(request):
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Inicia sesión."}, status=401)
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    txs = Transaction.objects.filter(user=request.user).order_by('-created_at')[:50]
    last_withdrawal = wallet.last_withdrawal_at
    next_withdrawal = (last_withdrawal + timedelta(hours=24)) if last_withdrawal else None
    now = timezone.now()
    return JsonResponse({"wallet": {"balance": str(wallet.balance), "total_invested": str(wallet.total_invested),
        "vip_active": wallet.vip_active, "initial_investment_met": wallet.total_invested >= Decimal('10.00'),
        "next_withdrawal_at": next_withdrawal.isoformat() if next_withdrawal else None,
        "withdrawal_wait_seconds": max(0, int((next_withdrawal-now).total_seconds())) if next_withdrawal else 0,
        "withdrawal_limit": "20.00" if wallet.vip_active else "2.00"},
        "transactions": [transaction_payload(t) for t in txs]})

@require_POST
def deposit_request(request):
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Inicia sesión."}, status=401)
    data = json_body(request)
    if data is None:
        return JsonResponse({"message": "JSON inválido."}, status=400)
    try:
        amount = Decimal(str(data.get('amount', '10'))).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return JsonResponse({"message": "Importe no válido."}, status=400)
    if amount < Decimal('10.00'):
        return JsonResponse({"message": "La inversión inicial mínima es de 10 USDT."}, status=400)
    if amount > Decimal('1000000.00'):
        return JsonResponse({"message": "El importe supera el máximo permitido; contacta con administración."}, status=400)
    if Transaction.objects.filter(user=request.user, kind=Transaction.Kind.DEPOSIT, status=Transaction.Status.PENDING).exists():
        return JsonResponse({"message": "Ya tienes un depósito pendiente de revisión."}, status=409)
    tx = Transaction.objects.create(user=request.user, kind=Transaction.Kind.DEPOSIT, amount=amount,
        destination=DEPOSIT_ADDRESS, description='Solicitud de depósito USDT BEP20 pendiente de verificación manual')
    ready = tx.created_at + timedelta(hours=REVIEW_HOURS)
    subject = f'[bear.litle] Depósito pendiente #{tx.id} — {amount} USDT'
    body = (f'Se ha registrado una solicitud de depósito en bear.litle.\n\n'
            f'Usuario: {request.user.username}\nCorreo: {request.user.email}\nID usuario: {request.user.pk}\n'
            f'Importe declarado: {amount} USDT\nRed: BEP20 / BNB Smart Chain\nWallet receptora: {DEPOSIT_ADDRESS}\n'
            f'Solicitud: #{tx.id}\nFecha: {timezone.localtime(tx.created_at).isoformat()}\n'
            f'Revisión programada desde: {timezone.localtime(ready).isoformat()}\n\n'
            'Verifica la transferencia y ajusta el importe real en Django Admin antes de aprobar. La solicitud por sí sola no confirma un pago on-chain.')
    sent = notify_admin(subject, body)
    message = ("Solicitud registrada y correo enviado al administrador. El saldo se acreditará solo tras verificar la transferencia; el plazo estimado de revisión es de hasta 2 horas." if sent else
               "Solicitud registrada, pero no se pudo enviar el correo. La cuenta de correo del administrador debe configurarse en el servidor; contacta con administración por otro medio.")
    return JsonResponse({"message": message, "email_notification_sent": sent,
                         "review_ready_at": ready.isoformat(), "transaction": transaction_payload(tx)}, status=201)

@require_POST
def withdraw_request(request):
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Inicia sesión."}, status=401)
    data = json_body(request)
    if data is None:
        return JsonResponse({"message": "JSON inválido."}, status=400)
    try:
        amount = Decimal(str(data.get('amount', '0'))).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return JsonResponse({"message": "Importe no válido."}, status=400)
    destination = (data.get('destination') or '').strip()
    if amount < Decimal('2.00'):
        return JsonResponse({"message": "El retiro mínimo es de 2 USDT."}, status=400)
    if not re.fullmatch(r'0x[a-fA-F0-9]{40}', destination):
        return JsonResponse({"message": "Introduce una dirección BEP20 válida."}, status=400)
    with db_transaction.atomic():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=request.user)
        if wallet.total_invested < Decimal('10.00'):
            return JsonResponse({"message": "Debes completar una inversión inicial verificada de 10 USDT antes de retirar."}, status=403)
        if Transaction.objects.filter(user=request.user, kind=Transaction.Kind.WITHDRAWAL, status=Transaction.Status.PENDING).exists():
            return JsonResponse({"message": "Ya tienes un retiro pendiente de revisión. Espera a que se procese antes de solicitar otro."}, status=409)
        if wallet.last_withdrawal_at and timezone.now() < wallet.last_withdrawal_at + timedelta(hours=24):
            ready = wallet.last_withdrawal_at + timedelta(hours=24)
            return JsonResponse({"message": "Aún está activo el período de espera de 24 horas.", "next_withdrawal_at": ready.isoformat()}, status=429)
        limit = Decimal('20.00') if wallet.vip_active else Decimal('2.00')
        if amount > limit:
            return JsonResponse({"message": f'El límite por retiro para tu cuenta actual es {limit} USDT.'}, status=400)
        if amount > wallet.balance:
            return JsonResponse({"message": "El saldo disponible verificado es insuficiente."}, status=400)
        wallet.balance -= amount
        wallet.save(update_fields=['balance'])
        tx = Transaction.objects.create(user=request.user, kind=Transaction.Kind.WITHDRAWAL, amount=amount,
            destination=destination, description='Retiro pendiente de revisión y envío manual')
    ready = tx.created_at + timedelta(hours=REVIEW_HOURS)
    subject = f'[bear.litle] Retiro pendiente #{tx.id} — {amount} USDT'
    body = (f'Se ha registrado una solicitud de retiro.\n\nUsuario: {request.user.username}\n'
            f'Correo: {request.user.email}\nID usuario: {request.user.pk}\nImporte: {amount} USDT\n'
            f'Destino BEP20: {destination}\nSolicitud: #{tx.id}\n'
            f'Recibida: {timezone.localtime(tx.created_at).isoformat()}\nNo procesar antes de: {timezone.localtime(ready).isoformat()}\n\n'
            'Realiza la transferencia manualmente y confirma la solicitud en Django Admin cuando corresponda.')
    sent = notify_admin(subject, body)
    message = ("Solicitud de retiro registrada y correo enviado al administrador. Podrá procesarse después del plazo de revisión de 2 horas." if sent else
               "Solicitud de retiro registrada, pero no se pudo enviar el correo. La cuenta de correo del administrador debe configurarse en el servidor.")
    return JsonResponse({"message": message, "email_notification_sent": sent,
                         "review_ready_at": ready.isoformat(), "transaction": transaction_payload(tx)}, status=201)

@require_POST
def game_start(request):
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Inicia sesión."}, status=401)
    data = json_body(request) or {}
    game_type = data.get('game_type', 'captcha')
    if game_type not in ('captcha', 'loading', 'memory'):
        return JsonResponse({"message": "Minijuego no válido."}, status=400)
    a, b = random.randint(2, 9), random.randint(2, 9)
    wait = random.choice([10, 15, 20, 30, 45, 60])
    question = f'¿Cuánto es {a} + {b}?' if game_type == 'captcha' else ('Escribe LISTO cuando termine la barra.' if game_type == 'loading' else f'Escribe la palabra OSITO en mayúsculas.')
    answer = str(a+b) if game_type == 'captcha' else ('LISTO' if game_type == 'loading' else 'OSITO')
    session = GameSession.objects.create(user=request.user, game_type=game_type, question=question, answer=answer, wait_seconds=wait)
    return JsonResponse({"game_id": session.id, "game_type": game_type, "question": question, "wait_seconds": wait,
                         "reward": str(session.reward), "started_at": session.started_at.isoformat()})

@require_POST
def game_claim(request):
    if not request.user.is_authenticated:
        return JsonResponse({"message": "Inicia sesión."}, status=401)
    data = json_body(request) or {}
    with db_transaction.atomic():
        try:
            game = GameSession.objects.select_for_update().get(id=int(data.get('game_id')), user=request.user)
        except (GameSession.DoesNotExist, TypeError, ValueError):
            return JsonResponse({"message": "Minijuego no encontrado."}, status=404)
        if game.claimed_at:
            return JsonResponse({"message": "Este minijuego ya fue reclamado."}, status=409)
        if timezone.now() < game.started_at + timedelta(seconds=game.wait_seconds):
            return JsonResponse({"message": "Todavía no ha terminado el tiempo de espera."}, status=429)
        if str(data.get('answer', '')).strip().upper() != game.answer.upper():
            return JsonResponse({"message": "Respuesta incorrecta."}, status=400)
        today = timezone.localdate()
        already = Transaction.objects.filter(user=request.user, kind=Transaction.Kind.GAME_REWARD, status=Transaction.Status.APPROVED, created_at__date=today).count()
        if already >= 10:
            return JsonResponse({"message": "Has alcanzado el máximo de 10 recompensas de minijuegos por hoy."}, status=429)
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user=request.user)
        wallet.balance += game.reward
        wallet.save(update_fields=['balance'])
        game.claimed_at = timezone.now()
        game.save(update_fields=['claimed_at'])
        tx = Transaction.objects.create(user=request.user, kind=Transaction.Kind.GAME_REWARD, status=Transaction.Status.APPROVED,
            amount=game.reward, description=f'Recompensa de minijuego: {game.game_type}')
    return JsonResponse({"message": "Recompensa acreditada.", "reward": str(game.reward), "balance": str(wallet.balance), "transaction": transaction_payload(tx)})
