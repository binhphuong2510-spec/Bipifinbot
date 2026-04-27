import os
import asyncio
from datetime import datetime
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

# ── CẤU HÌNH (đọc từ Environment Variables) ──────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]    # Token bot Telegram
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]  # Chat ID của bạn
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"] # API key Anthropic
SEND_HOUR        = int(os.environ.get("SEND_HOUR", "8"))  # Giờ gửi (mặc định 8h)
# ─────────────────────────────────────────────────────────

PROMPT = """Hôm nay là {date}. Viết BÁO CÁO THỊ TRƯỜNG BUỔI SÁNG ngắn gọn gồm 3 phần:

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


async def get_analysis() -> str:
    """Gọi Claude API để lấy phân tích thị trường"""
    today = datetime.now().strftime("%A, %d/%m/%Y")
    
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": "Bạn là chuyên gia phân tích tài chính chứng khoán Việt Nam và thị trường cà phê quốc tế.",
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                "messages": [{"role": "user", "content": PROMPT.format(date=today)}],
            },
        )
        data = resp.json()
        return "\n".join(b["text"] for b in data["content"] if b["type"] == "text")


async def send_report():
    """Tạo và gửi báo cáo qua Telegram"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang tạo báo cáo...")
    try:
        report = await get_analysis()
        bot = Bot(token=TELEGRAM_TOKEN)
        # Telegram giới hạn 4096 ký tự mỗi tin
        for i in range(0, len(report), 4000):
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=report[i:i+4000],
                parse_mode="Markdown",
            )
        print("✅ Đã gửi báo cáo thành công!")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⚠️ FinanceAI bị lỗi: {e}",
        )


async def main():
    print("🤖 FinanceAI Bot đang chạy...")
    
    # Gửi tin nhắn xác nhận bot đang hoạt động
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"✅ FinanceAI Bot đã khởi động!\nSẽ gửi báo cáo lúc {SEND_HOUR}:00 mỗi ngày.",
    )

    # Cài lịch chạy mỗi ngày
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(send_report, "cron", hour=SEND_HOUR, minute=0)
    scheduler.start()

    # Giữ chương trình chạy
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
