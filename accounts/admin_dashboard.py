from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, authenticate, login, logout
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Wallet, Transaction, GameSession, Referral, DailyTaskClaim

User = get_user_model()


def admin_login(request):
    """Formulario de acceso para el panel de gestión; solo acepta cuentas staff."""
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        return redirect('admin_dashboard')

    error = ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)
        if user is None:
            error = 'Usuario o contraseña incorrectos.'
        elif not user.is_active:
            error = 'Esta cuenta está desactivada.'
        elif not (user.is_staff or user.is_superuser):
            error = 'Esta cuenta no tiene permisos de administrador.'
        else:
            login(request, user)
            destination = request.GET.get('next', '')
            if not destination.startswith('/') or destination.startswith('//'):
                destination = '/gestion/'
            return redirect(destination)

    return render(request, 'accounts/admin_login.html', {'error': error})


@require_http_methods(['POST'])
def admin_logout(request):
    logout(request)
    return redirect('admin_login')


def staff_required(view_func):
    """Redirige al formulario propio de gestión si la sesión no es staff."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('admin_login')
        if not (request.user.is_staff or request.user.is_superuser):
            # No mostrar un 403 a usuarios con sesión normal: llevarlos al
            # formulario para que puedan autenticarse con la cuenta admin.
            return redirect('admin_login')
        return view_func(request, *args, **kwargs)
    return wrapped


@staff_required
def dashboard(request):
    query = request.GET.get('q', '').strip()
    users = User.objects.all().order_by('-date_joined')
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    paginator = Paginator(users, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    wallets = Wallet.objects.select_related('user')
    context = {
        'users_page': page_obj,
        'query': query,
        'user_count': User.objects.count(),
        'wallet_count': Wallet.objects.count(),
        'total_balance': wallets.aggregate(total=Sum('balance'))['total'] or Decimal('0.00'),
        'pending_transactions': Transaction.objects.filter(status=Transaction.Status.PENDING).count(),
        'recent_transactions': Transaction.objects.select_related('user').order_by('-created_at')[:10],
        'recent_games': GameSession.objects.select_related('user').order_by('-started_at')[:10],
        'recent_referrals': Referral.objects.select_related('inviter', 'invited').order_by('-created_at')[:100],
        'daily_task_claims': DailyTaskClaim.objects.select_related('user').order_by('-completed_at')[:50],
        'trace_note': 'No existe un modelo de trazas técnicas en los modelos actuales de Bear Litle. Esta sección muestra movimientos y sesiones de tareas/minijuegos almacenados.',
    }
    return render(request, 'accounts/admin_dashboard.html', context)


@staff_required
@require_http_methods(['GET', 'POST'])
def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    wallet, _ = Wallet.objects.get_or_create(user=user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'balance_adjustment':
            raw_amount = (request.POST.get('amount') or '').strip().replace(',', '.')
            reason = (request.POST.get('reason') or '').strip()
            try:
                amount = Decimal(raw_amount).quantize(Decimal('0.01'))
            except (InvalidOperation, ValueError):
                amount = Decimal('0')
                messages.error(request, 'Introduce una cantidad válida.')
            else:
                if amount == 0:
                    messages.error(request, 'La cantidad no puede ser cero.')
                elif not reason:
                    messages.error(request, 'Es obligatorio indicar el motivo del ajuste.')
                else:
                    with db_transaction.atomic():
                        locked_wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
                        if locked_wallet.balance + amount < 0:
                            messages.error(request, 'El ajuste no puede dejar el saldo por debajo de cero.')
                        else:
                            locked_wallet.balance += amount
                            locked_wallet.save(update_fields=['balance'])
                            sign = '+' if amount > 0 else ''
                            Transaction.objects.create(
                                user=user,
                                kind='admin_adjustment',
                                status=Transaction.Status.APPROVED,
                                amount=amount,
                                description=f'Ajuste administrativo ({sign}{amount} USDT). Motivo: {reason[:170]}',
                                reviewed_at=timezone.now(),
                            )
                            messages.success(request, f'Saldo actualizado. Nuevo saldo: {locked_wallet.balance} USDT.')
                            return redirect('admin_user_detail', user_id=user.pk)
        elif action == 'toggle_active':
            if user.pk == request.user.pk:
                messages.error(request, 'No puedes desactivar tu propia cuenta desde esta pantalla.')
            else:
                user.is_active = not user.is_active
                user.save(update_fields=['is_active'])
                messages.success(request, 'Estado del usuario actualizado.')
                return redirect('admin_user_detail', user_id=user.pk)
        elif action == 'toggle_vip':
            wallet.vip_active = not wallet.vip_active
            wallet.save(update_fields=['vip_active'])
            messages.success(request, 'Estado VIP actualizado.')
            return redirect('admin_user_detail', user_id=user.pk)

    context = {
        'target_user': user,
        'wallet': wallet,
        'transactions': Transaction.objects.filter(user=user).order_by('-created_at')[:100],
        'games': GameSession.objects.filter(user=user).order_by('-started_at')[:100],
    }
    return render(request, 'accounts/admin_user_detail.html', context)
