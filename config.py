import os

# اگر Environment Variable در Railway تعریف شده باشد، از آن استفاده می‌شود
# در غیر این صورت از مقدار پیش‌فرض زیر استفاده می‌شود
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8955432875:AAEokc4LmDF4R_65wc0iGkgWYJyadEzZEz4")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1953490397"))

# محدودیت rate limiting
MAX_MESSAGES_PER_MINUTE = 5
