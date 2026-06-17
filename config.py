import os

# اگر Environment Variable در Railway تعریف شده باشد، از آن استفاده می‌شود
# در غیر این صورت از مقدار پیش‌فرض زیر استفاده می‌شود
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8492001698:AAF6nLaF5WGvtv3tdiljtZCq_6CiCPSX_XA")

# ---- پشتیبانی از چند ادمین ----
# در Railway، متغیر ADMIN_IDS را با کاما جدا کن، مثلا: 1953490397,987654321
# اگر فقط یک ادمین داری، کافیست همان یک عدد را بگذاری.
_admin_ids_raw = os.environ.get("ADMIN_IDS", os.environ.get("ADMIN_ID", "1953490397,98064300"))
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()]

# برای سازگاری با کدهای قدیمی‌تر که فقط یک ادمین اصلی می‌خواهند
ADMIN_ID = ADMIN_IDS[0]

# محدودیت rate limiting
MAX_MESSAGES_PER_MINUTE = 5
