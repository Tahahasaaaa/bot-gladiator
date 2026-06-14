import os

# اگر Environment Variable در Railway تعریف شده باشد، از آن استفاده می‌شود
# در غیر این صورت از مقدار پیش‌فرض زیر استفاده می‌شود
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8492001698:AAF6nLaF5WGvtv3tdiljtZCq_6CiCPSX_XA")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1953490397"))

# محدودیت rate limiting
MAX_MESSAGES_PER_MINUTE = 5
