# Initial database schema for the bear.litle account and wallet system.
import decimal
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='GameSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('game_type', models.CharField(max_length=30)),
                ('question', models.CharField(max_length=200)),
                ('answer', models.CharField(max_length=100)),
                ('reward', models.DecimalField(decimal_places=2, default=decimal.Decimal('0.05'), max_digits=6)),
                ('wait_seconds', models.PositiveSmallIntegerField(default=10)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('claimed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='game_sessions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Wallet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('balance', models.DecimalField(decimal_places=2, default=decimal.Decimal('0.00'), max_digits=14)),
                ('total_invested', models.DecimalField(decimal_places=2, default=decimal.Decimal('0.00'), max_digits=14)),
                ('vip_active', models.BooleanField(default=False)),
                ('last_withdrawal_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='wallet', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('deposit', 'Depósito'), ('withdrawal', 'Retiro'), ('game_reward', 'Recompensa de minijuego')], max_length=20)),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('approved', 'Aprobado'), ('rejected', 'Rechazado')], default='pending', max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('txid', models.CharField(blank=True, max_length=150)),
                ('destination', models.CharField(blank=True, max_length=150)),
                ('description', models.CharField(blank=True, max_length=240)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
