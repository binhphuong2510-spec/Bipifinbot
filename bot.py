import os
import asyncio
from datetime import datetime
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── CẤU HÌNH ──────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
SEND_HOUR        = int(os.environ.get("SEND_HOUR", "8"))
SEND_MINUTE      = int(os.environ.get("SEND_MINUTE", "0"))

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not ANTHROPIC_KEY:
    print("❌ Thiếu biến môi trường! Kiểm tra TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY")
    exit(1)
# ──────────────────────────────────────────────────────────

PROMPT = """Hôm nay là {date}. Viết BÁO CÁO THỊ TRƯỜNG gồm 3 phần:

📊 CHỨNG KHOÁN VIỆT NAM
- Dự báo xu hướng VN-Index hôm nay
- 3 cổ phiếu đáng chú ý (VCB, HPG, FPT, TCB, VIC...)
- Khuyến nghị: MUA / GIỮ / TRÁNH

☕ GIÁ CÀ PHÊ NEW YORK (ICE Futures)
- Giá Robusta và Arabica hôm nay
- Xu hướng: TĂNG / GIẢM / ĐI NGANG
- Tác động đến xuất khẩu Việt Nam

🌐 VĨ MÔ TOÀN CẦU
- FED/lãi suất, DXY, rủi ro địa chính trị

Kết thúc bằng 1 câu NHẬN ĐỊNH TỔNG THỂ.
Viết tiếng Việt, ngắn gọn, dùng emoji."""


# ── GỌI CLAUDE API ────────────────────────────────────────
async def get_analysis(topic=None):
    today = datetime.now().strftime("%A, %d/%m/%Y")
    prompt = PROMPT.format(date=today)
    
    # Nếu hỏi chủ đề cụ thể
    if topic:
        prompt = f"Hôm nay là {today}. Phân tích chi tiết về: {topic}. Viết tiếng Việt, dùng emoji, ngắn gọn súc tích."

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 1000,
                "system": "Bạn là chuyên gia phân tích tài chính chứng khoán Việt Nam và thị trường cà phê quốc tế.",
                
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        data = resp.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        return "\n".join(b["text"] for b in data["content"] if b["type"] == "text")


# ── GỬI BÁO CÁO ──────────────────────────────────────────
async def send_report(bot=None, chat_id=None, topic=None):
    if bot is None:
        bot = Bot(token=TELEGRAM_TOKEN)
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    label = f"về '{topic}'" if topic else "thị trường"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang tạo báo cáo {label}...")

    try:
        await bot.send_message(chat_id=chat_id, text=f"⏳ Đang phân tích {label}, vui lòng chờ...")
        report = await get_analysis(topic)

        for i in range(0, len(report), 4000):
            await bot.send_message(
                chat_id=chat_id,
                text=report[i:i+4000],
            )
        print("✅ Đã gửi báo cáo thành công!")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Lỗi: {e}")


# ── LỆNH TELEGRAM ─────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start"""
    await update.message.reply_text(
        "👋 Xin chào! Tôi là FinanceAI Bot!\n\n"
        "📌 Các lệnh:\n"
        "/baocao - Báo cáo thị trường đầy đủ\n"
        "/phantich [chủ đề] - Phân tích chủ đề cụ thể\n"
        "/help - Hướng dẫn sử dụng\n\n"
        f"⏰ Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày!"
    )

async def cmd_baocao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /baocao - gửi báo cáo ngay"""
    bot = context.bot
    chat_id = update.effective_chat.id
    await send_report(bot=bot, chat_id=chat_id)

async def cmd_phantich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /phantich [chủ đề] - phân tích chủ đề cụ thể"""
    topic = " ".join(context.args) if context.args else None
    if not topic:
        await update.message.reply_text(
            "⚠️ Vui lòng nhập chủ đề!\n"
            "Ví dụ: /phantich VCB\n"
            "Ví dụ: /phantich giá cà phê Robusta\n"
            "Ví dụ: /phantich VN-Index tuần này"
        )
        return
    bot = context.bot
    chat_id = update.effective_chat.id
    await send_report(bot=bot, chat_id=chat_id, topic=topic)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /help"""
    await update.message.reply_text(
        "📖 HƯỚNG DẪN SỬ DỤNG:\n\n"
        "/baocao - Xem báo cáo thị trường đầy đủ ngay\n\n"
        "/phantich [chủ đề] - Phân tích 1 chủ đề cụ thể\n"
        "  • /phantich VCB\n"
        "  • /phantich giá Robusta\n"
        "  • /phantich lãi suất FED\n\n"
        f"⏰ Tự động gửi báo cáo lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày!"
    )


# ── HÀM CHÍNH ────────────────────────────────────────────
async def main():
    print("🤖 FinanceAI Bot đang khởi động...")

    # Khởi tạo Telegram app
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Đăng ký các lệnh
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("baocao", cmd_baocao))
    app.add_handler(CommandHandler("phantich", cmd_phantich))
    app.add_handler(CommandHandler("help", cmd_help))

    # Cài lịch tự động
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(
        send_report, "cron",
        hour=SEND_HOUR, minute=SEND_MINUTE
    )
    scheduler.start()

    # Thông báo khởi động
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"✅ FinanceAI Bot đã khởi động!\n"
             f"⏰ Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày\n\n"
             f"📌 Lệnh thủ công:\n"
             f"/baocao - Xem báo cáo ngay\n"
             f"/phantich [chủ đề] - Phân tích cụ thể\n"
             f"/help - Hướng dẫn"
    )

    print(f"✅ Bot chạy! Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d}")

    # Chạy bot nhận lệnh
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # Giữ chương trình chạy
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
