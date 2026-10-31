<div align="center">
  <img src="assets/atron-logo.png" alt="ATRON logo" width="220">
  <h1>ATRON · آترون</h1>
  <p><strong>PasarGuard Panel Manager — Telegram Bot</strong></p>
</div>

[فارسی](#فارسی) · [English](#english)

---

## فارسی

ربات تلگرامی برای مدیریت یک یا چند پنل **PasarGuard** با دکمه‌های شیشه‌ای (inline): مدیریت کاربران، جستجو، آمار و نمودار مصرف، سطل زباله (بازیابی تا ۷ روز)، بکاپ، هشدارها، انتقال بین پنل‌ها، **گروه گزارش** (جدید) و رابط دو‌زبانه (فارسی/انگلیسی).

> 🚧 **نسخه ۱.۱** — این پروژه تازه شروع شده و آپدیت‌های زیادی در راه است. باگ‌ها را در Issues گزارش دهید و ریپو را Star/Watch کنید تا از نسخه‌های بعدی باخبر شوید.
>
> توسعه‌دهنده: **SYE** ([github.com/devsye](https://github.com/devsye))

> هیچ توکن یا اطلاعات شخصی داخل این ریپو نیست. توکن و آیدی فقط از طریق فایل `.env` (که commit نمی‌شود) خوانده می‌شوند.

### پیش‌نیاز

1. یک ربات در تلگرام بسازید ([@BotFather](https://t.me/BotFather)) و **توکن** را بردارید.
2. آیدی عددی خودتان را از [@userinfobot](https://t.me/userinfobot) بگیرید (فقط همین آیدی به ربات دسترسی دارد).
3. یک سرور لینوکس (Debian/Ubuntu پیشنهاد می‌شود) که به تلگرام و پنل‌هایتان دسترسی داشته باشد.

### روش ۱: نصب دائمی با systemd (پیشنهادی)

```bash
git clone https://github.com/devsye/atron.git
cd atron
sudo bash install.sh
```

اسکریپت توکن و آیدی را می‌پرسد، ربات را در `/opt/atron` نصب می‌کند و به‌عنوان سرویس فعال می‌کند. ربات بعد از ریبوت یا کرش خودکار بالا می‌آید.

```bash
systemctl status atron        # وضعیت
journalctl -u atron -f        # لاگ
systemctl restart atron       # ری‌استارت
sudo bash scripts/update.sh    # آپدیت بعد از git pull
```

### روش ۲: Docker

```bash
git clone https://github.com/devsye/atron.git
cd atron
cp .env.example .env && nano .env     # BOT_TOKEN و ADMIN_ID را پر کنید
docker compose up -d --build
docker compose logs -f
```

داده‌ها در پوشه `./data` ذخیره می‌شوند (بکاپ بگیرید).

### روش ۳: Termux (فقط برای تست)

```bash
bash scripts/termux-install.sh
```

برای استفاده دائمی از سرور استفاده کنید؛ گوشی ممکن است پروسه را ببندد.

### متغیرهای محیطی

| متغیر | توضیح |
|---|---|
| `BOT_TOKEN` | توکن ربات از BotFather (الزامی) |
| `ADMIN_ID` | آیدی عددی مالک ربات (الزامی) |
| `CHART_LANG` | زبان برچسب نمودارها: `en` یا `fa` |
| `DATA_DIR` | مسیر ذخیره داده‌ها (پیش‌فرض `./data`) |

### 🛰 گروه گزارش (جدید در ۱.۱)

گزارش، نمودار، بکاپ و هشدار **همه‌ی پنل‌ها** در ۱۰ تاپیک یک گروه تلگرام جمع می‌شود:

1. یک گروه بسازید و در تنظیماتش **Topics** را روشن کنید.
2. ربات را به گروه اضافه و **ادمین** کنید (با دسترسی **Manage Topics**؛ حالت «ادمین ناشناس» خاموش باشد).
3. ربات آیدی گروه را خودکار می‌گیرد و تاپیک‌ها را می‌سازد. اگر نشد، داخل گروه `/setup` بفرستید یا از منوی «🛰 گروه گزارش» آیدی را دستی ثبت کنید.

تاپیک‌ها: گزارش کلی، نمودارها، بکاپ، خروجی کاربران، پرمصرف‌ها، وضعیت پنل‌ها، هشدارها، سطل زباله، مهاجرت و لاگ عملیات. زمان‌بندی هر مورد جدا تنظیم می‌شود (خاموش / ۶ساعت / ۱۲ساعت / روزانه / ۳روز / هفتگی) و دکمه‌ی «ارسال همین الان» هم دارد.

> ⚠️ فایل‌های بکاپ حاوی اطلاعات حساس‌اند؛ گروه را **خصوصی** نگه دارید و فقط خودتان و ربات عضو باشید.

### نکات امنیتی

- فایل `.env` را هرگز commit نکنید (در `.gitignore` هست). اگر توکن لو رفت، در BotFather با `/revoke` عوض کنید.
- اطلاعات ورود پنل‌ها (یوزرنیم/پسورد) به‌صورت متن ساده در `data/panels.json` ذخیره می‌شود. دسترسی این پوشه را محدود نگه دارید (`install.sh` خودش `chmod 700` می‌کند) و از آن بکاپ عمومی نگذارید.
- برای پنل از یک ادمین با دسترسی محدود استفاده کنید، نه sudo-admin اصلی.
- ارتباط با پنل بدون اعتبارسنجی گواهی TLS انجام می‌شود تا پنل‌های self-signed کار کنند؛ در شبکه‌های ناامن دقت کنید.

### توسعه‌دهنده

ساخته‌شده توسط **SYE** ([@devsye](https://github.com/devsye))

### لایسنس

MIT © SYE — فایل [LICENSE](LICENSE)

### مشارکت

Issue و Pull Request خوشحال‌مان می‌کند. لطفاً هیچ‌وقت توکن، لینک ساب یا اطلاعات کاربران را در issue قرار ندهید.

---

## English

A Telegram bot to manage one or more **PasarGuard** panels through inline buttons: user management, search, usage stats and charts, trash with 7‑day restore, backups, alerts, migration between panels, a **report group hub** (new), and a bilingual (Persian/English) UI.

> 🚧 **v1.1.** This project is just getting started and many updates are coming. Report bugs in Issues, and Star/Watch the repo to follow new versions.
>
> Developed by **SYE** ([github.com/devsye](https://github.com/devsye))

> No tokens or personal data are included in this repo. Credentials are read only from a `.env` file that is git‑ignored.

### Requirements

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the **token**.
2. Get your numeric Telegram ID from [@userinfobot](https://t.me/userinfobot) (only this ID can use the bot).
3. A Linux server (Debian/Ubuntu recommended) that can reach Telegram and your panels.

### Option 1: Permanent install with systemd (recommended)

```bash
git clone https://github.com/devsye/atron.git
cd atron
sudo bash install.sh
```

The script asks for the token and ID, installs to `/opt/atron`, and enables a service that restarts on crash and on reboot.

```bash
systemctl status atron
journalctl -u atron -f
systemctl restart atron
sudo bash scripts/update.sh   # after git pull
```

### Option 2: Docker

```bash
cp .env.example .env && nano .env
docker compose up -d --build
```

Runtime data lives in `./data` — back it up.

### Option 3: Termux (testing only)

```bash
bash scripts/termux-install.sh
```

### Environment variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Bot token from BotFather (required) |
| `ADMIN_ID` | Numeric Telegram ID of the owner (required) |
| `CHART_LANG` | Chart label language: `en` or `fa` |
| `DATA_DIR` | Data directory (default `./data`) |

### 🛰 Report group hub (new in 1.1)

Reports, charts, backups and alerts of **all panels** are collected in 10 topics of one Telegram group:

1. Create a group and enable **Topics** in its settings.
2. Add the bot and make it **admin** (with **Manage Topics**; turn off "anonymous admin").
3. The bot picks up the group ID automatically and creates the topics. If it doesn't, send `/setup` in the group or set the ID manually from the "🛰 Report group" menu.

Topics: overview, charts, backups, users export, top users, panel status, alerts, trash, migration, operations log. Each job has its own schedule (off / 6h / 12h / daily / 3 days / weekly) plus a "Send now" button.

> ⚠️ Backup files contain sensitive data. Keep the group **private**, with only you and the bot as members.

### Security notes

- Never commit `.env`. If a token leaks, revoke it in BotFather (`/revoke`).
- Panel credentials are stored in plain text in `data/panels.json`; keep that directory private and use a limited panel admin account.
- Panel requests skip TLS certificate verification to support self‑signed panels.
- Never paste tokens, subscription links, or user data into issues.

### Author

Created by **SYE** ([@devsye](https://github.com/devsye)).

### License

MIT © SYE — see [LICENSE](LICENSE).
