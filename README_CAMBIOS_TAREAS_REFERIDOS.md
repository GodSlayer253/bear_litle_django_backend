# Bear Litle: tareas diarias y referidos

## Cambios incluidos
- Plan normal: 2 tareas al día, recompensa configurada de 1.00 USDT por tarea.
- Plan VIP: 4 tareas al día, recompensa configurada de 5.00 USDT por tarea.
- El conjunto de tareas cambia por fecha y usuario; los reclamos se guardan en la base de datos y tienen restricción única por usuario/fecha/posición.
- Cada billetera tiene un código de referido y la página muestra un enlace compartible por WhatsApp y Telegram.
- Una visita al enlace solo guarda el código en la sesión. La recompensa de 1.00 USDT se acredita cuando se crea correctamente una cuenta nueva con ese código; no se paga por visitas. Una cuenta invitada solo puede tener un invitador registrado.
- El panel /gestion/ muestra registros de referidos y tareas completadas.

## Despliegue
1. Revisa y sube todos los archivos incluidos al repositorio del proyecto.
2. Asegúrate de que `requirements.txt` incluya Django y WhiteNoise como en tu configuración actual.
3. En Render, Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
4. Start Command: `gunicorn config.wsgi:application`
5. Comprueba los registros de compilación y prueba crear una cuenta nueva desde un enlace `/?ref=CODIGO`.

## Importante sobre las recompensas
Las tareas de esta implementación son actividades informativas/autodeclaradas: el botón registra la finalización, pero no comprueba una acción externa de forma independiente. No las describas como ingresos garantizados. Antes de usar dinero real, agrega verificación independiente de cumplimiento y una política clara de elegibilidad. La recompensa de referido actual se otorga tras el registro correcto de una cuenta nueva, no tras una mera visita.

## Base de datos existente
Se añadió la migración `accounts.0002_daily_tasks_referrals`. Render debe ejecutar `python manage.py migrate` para crear las tablas y códigos para billeteras existentes. Mantén una base de datos persistente; SQLite en disco efímero puede perder saldos y registros durante un redeploy.
