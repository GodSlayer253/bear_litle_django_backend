from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
import secrets
import string

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_invested = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    vip_active = models.BooleanField(default=False)
    last_withdrawal_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    referral_code = models.CharField(max_length=16, unique=True, blank=True, null=True, db_index=True)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            alphabet = string.ascii_uppercase + string.digits
            while True:
                code = ''.join(secrets.choice(alphabet) for _ in range(10))
                if not Wallet.objects.filter(referral_code=code).exists():
                    self.referral_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.username} — {self.balance} USDT'

class Transaction(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', 'Depósito'
        WITHDRAWAL = 'withdrawal', 'Retiro'
        GAME_REWARD = 'game_reward', 'Recompensa de minijuego'
        ADMIN_ADJUSTMENT = 'admin_adjustment', 'Ajuste administrativo'
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobado'
        REJECTED = 'rejected', 'Rechazado'
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    txid = models.CharField(max_length=150, blank=True)
    destination = models.CharField(max_length=150, blank=True)
    description = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f'{self.user.username} · {self.get_kind_display()} · {self.amount} USDT · {self.status}'

class GameSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='game_sessions')
    game_type = models.CharField(max_length=30)
    question = models.CharField(max_length=200)
    answer = models.CharField(max_length=100)
    reward = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.05'))
    wait_seconds = models.PositiveSmallIntegerField(default=10)
    started_at = models.DateTimeField(default=timezone.now)
    claimed_at = models.DateTimeField(null=True, blank=True)
    def __str__(self):
        return f'{self.user.username} · {self.game_type} · {self.started_at:%Y-%m-%d %H:%M}'


class Referral(models.Model):
    class Status(models.TextChoices):
        CREDITED = 'credited', 'Acreditado'
        REJECTED = 'rejected', 'Rechazado'
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='referrals_sent')
    invited = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='referral_source')
    reward = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('1.00'))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CREDITED)
    created_at = models.DateTimeField(auto_now_add=True)
    credited_at = models.DateTimeField(null=True, blank=True)
    transaction = models.OneToOneField('Transaction', null=True, blank=True, on_delete=models.SET_NULL, related_name='referral_reward')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.invited} invitado por {self.inviter} ({self.status})'


class DailyTaskClaim(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_task_claims')
    task_date = models.DateField()
    slot = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=180)
    reward = models.DecimalField(max_digits=8, decimal_places=2)
    completed_at = models.DateTimeField(auto_now_add=True)
    transaction = models.OneToOneField('Transaction', null=True, blank=True, on_delete=models.SET_NULL, related_name='daily_task_claim')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'task_date', 'slot'], name='unique_daily_task_claim')]
        ordering = ['task_date', 'slot']

    def __str__(self):
        return f'{self.user} · {self.task_date} · {self.title}'
