import os
import asyncio
from datetime import datetime
import httpx
import xml.etree.ElementTree as ET
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
    print("❌ Thiếu biến môi trường!")
    exit(1)
# ──────────────────────────────────────────────────────────

# ── LẤY GIÁ CHỨNG KHOÁN THẬT TỪ TCBS ─────────────────────
async def get_stock_price(symbol: str) -> dict:
    url = f"https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker={symbol}&type=stock&resolution=D&from=0&to=9999999999"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            data = resp.json()
            bars = data.get("data", [])
            if bars:
                latest = bars[-1]
                prev = bars[-2] if len(bars) > 1 else latest
                close = latest.get("close", 0)
                prev_close = prev.get("close", 0)
                change = close - prev_close
                pct = (change / prev_close * 100) if prev_close else 0
                return {
                    "symbol": symbol,
                    "price": close,
                    "change": round(change, 2),
                    "pct": round(pct, 2),
                    "volume": latest.get("volume", 0)
                }
    except Exception as e:
        print(f"Lỗi lấy giá {symbol}: {e}")
    return {"symbol": symbol, "price": "N/A", "change": 0, "pct": 0, "volume": 0}


# ── LẤY TIN TỨC TỪ RSS ───────────────────────────────────
RSS_FEEDS = {
    "CafeF":     "https://cafef.vn/thi-truong-chung-khoan.rss",
    "VnExpress": "https://vnexpress.net/kinh-doanh/chung-khoan.rss",
    "Vietstock": "https://vietstock.vn/830/chung-khoan.rss",
    "NDH":       "https://ndh.vn/chung-khoan.rss",
}

async def get_news(limit=5) -> str:
    news_list = []
    async with httpx.AsyncClient(timeout=10) as client:
        for source, url in RSS_FEEDS.items():
            try:
                resp = await client.get(url)
                root = ET.fromstring(resp.text)
                items = root.findall(".//item")[:2]
                for item in items:
                    title = item.findtext("title", "").strip()
                    if title:
                        news_list.append(f"[{source}] {title}")
            except Exception as e:
                print(f"Lỗi RSS {source}: {e}")

    return "\n".join(news_list[:limit]) if news_list else "Không lấy được tin tức"


# ── GỌI CLAUDE API ────────────────────────────────────────
async def get_analysis(stock_data: str, news_data: str, topic=None) -> str:
    today = datetime.now().strftime("%A, %d/%m/%Y %H:%M")

    if topic:
        prompt = f"Hôm nay là {today}.\nDữ liệu thị trường thực tế:\n{stock_data}\n\nTin tức mới nhất:\n{news_data}\n\nPhân tích chi tiết về: {topic}\nViết tiếng Việt, dùng emoji, ngắn gọn súc tích."
    else:
        prompt = f"""Hôm nay là {today}.

DỮ LIỆU THỊ TRƯỜNG THỰC TẾ (vừa lấy):
{stock_data}

TIN TỨC MỚI NHẤT:
{news_data}

Dựa vào số liệu THỰC TẾ trên, viết BÁO CÁO THỊ TRƯỜNG gồm:

📊 CHỨNG KHOÁN VIỆT NAM
- Nhận định VN-Index dựa trên giá thực tế
- Phân tích từng cổ phiếu có số liệu trên
- Khuyến nghị: MUA / GIỮ / TRÁNH (kèm lý do)

📰 TÓM TẮT TIN TỨC
- Điểm tin quan trọng ảnh hưởng thị trường

☕ GIÁ CÀ PHÊ NEW YORK
- Dự báo xu hướng Robusta/Arabica hôm nay

🌐 NHẬN ĐỊNH TỔNG THỂ
- 1 câu kết luận ngắn gọn

Viết tiếng Việt, dùng emoji, ngắn gọn."""

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
                "system": "Bạn là chuyên gia phân tích tài chính chứng khoán Việt Nam. Luôn dùng số liệu thực tế được cung cấp, không bịa số liệu.",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        data = resp.json()
        if "error" in data:
            raise Exception(data["error"]["message"])
        return "\n".join(b["text"] for b in data["content"] if b["type"] == "text")


# ── THU THẬP DỮ LIỆU THỰC TẾ ─────────────────────────────
async def collect_realtime_data():
    symbols = ["VCB", "VIC", "HPG", "FPT", "TCB", "MWG", "VHM", "MSN"]
    
    # Lấy giá song song
    tasks = [get_stock_price(s) for s in symbols]
    prices = await asyncio.gather(*tasks)
    
    # Format dữ liệu giá
    stock_lines = []
    for p in prices:
        if p["price"] != "N/A":
            arrow = "▲" if p["change"] >= 0 else "▼"
            stock_lines.append(
                f"{p['symbol']}: {p['price']:,} đ {arrow} {p['change']:+} ({p['pct']:+.2f}%)"
            )
    
    stock_data = "\n".join(stock_lines) if stock_lines else "Không lấy được giá"
    news_data = await get_news(limit=6)
    
    return stock_data, news_data


# ── GỬI BÁO CÁO ──────────────────────────────────────────
async def send_report(bot=None, chat_id=None, topic=None):
    if bot is None:
        bot = Bot(token=TELEGRAM_TOKEN)
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Đang thu thập dữ liệu thực tế...")

    try:
        await bot.send_message(chat_id=chat_id, text="⏳ Đang lấy dữ liệu thị trường thực tế...")
        
        stock_data, news_data = await collect_realtime_data()
        report = await get_analysis(stock_data, news_data, topic)

        for i in range(0, len(report), 4000):
            await bot.send_message(chat_id=chat_id, text=report[i:i+4000])

        print("✅ Đã gửi báo cáo thành công!")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Lỗi: {e}")


# ── CÁC LỆNH TELEGRAM ────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Xin chào! Tôi là FinanceAI Bot!\n\n"
        "📌 Các lệnh:\n"
        "/baocao - Báo cáo thị trường realtime\n"
        "/gia [mã] - Xem giá cổ phiếu ngay\n"
        "/phantich [chủ đề] - Phân tích chủ đề\n"
        "/dudoan - Dự báo theo thời gian\n"
        "/tintuc - Tin tức thị trường mới nhất\n"
        "/help - Hướng dẫn\n\n"
        f"⏰ Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày!"
    )

async def cmd_baocao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_report(bot=context.bot, chat_id=update.effective_chat.id)

async def cmd_gia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = " ".join(context.args).upper() if context.args else None
    if not symbol:
        await update.message.reply_text("⚠️ Nhập mã cổ phiếu!\nVí dụ: /gia VCB")
        return
    await update.message.reply_text(f"⏳ Đang lấy giá {symbol}...")
    data = await get_stock_price(symbol)
    if data["price"] == "N/A":
        await update.message.reply_text(f"❌ Không tìm thấy mã {symbol}")
        return
    arrow = "▲" if data["change"] >= 0 else "▼"
    color = "🟢" if data["change"] >= 0 else "🔴"
    await update.message.reply_text(
        f"{color} {data['symbol']}\n"
        f"💰 Giá: {data['price']:,} đ\n"
        f"{arrow} Thay đổi: {data['change']:+} ({data['pct']:+.2f}%)\n"
        f"📊 KL: {data['volume']:,}"
    )

async def cmd_tintuc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Đang lấy tin tức...")
    news = await get_news(limit=10)
    await update.message.reply_text(f"📰 TIN TỨC MỚI NHẤT:\n\n{news}")

async def cmd_phantich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) if context.args else None
    if not topic:
        await update.message.reply_text(
            "⚠️ Vui lòng nhập chủ đề!\n"
            "Ví dụ: /phantich VCB\n"
            "Ví dụ: /phantich giá cà phê Robusta"
        )
        return
    await send_report(bot=context.bot, chat_id=update.effective_chat.id, topic=topic)

async def cmd_dudoan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📅 CHỌN KHUNG THỜI GIAN:\n\n"
            "/dudoan 3ngay\n"
            "/dudoan 7ngay\n"
            "/dudoan thang\n"
            "/dudoan quy\n"
            "/dudoan nam"
        )
        return
    chon = context.args[0].lower()
    khung = {
        "3ngay": "3 ngày tới",
        "7ngay": "7 ngày tới",
        "thang": "1 tháng tới",
        "quy":   "1 quý tới",
        "nam":   "cả năm 2026",
    }
    if chon not in khung:
        await update.message.reply_text("⚠️ Dùng: 3ngay / 7ngay / thang / quy / nam")
        return
    ten_khung = khung[chon]
    topic = f"Dự báo thị trường {ten_khung}: VN-Index, top cổ phiếu tiềm năng, giá cà phê, rủi ro, chiến lược đầu tư"
    await send_report(bot=context.bot, chat_id=update.effective_chat.id, topic=topic)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 HƯỚNG DẪN:\n\n"
        "/baocao - Báo cáo đầy đủ + giá thực tế\n"
        "/gia VCB - Xem giá 1 cổ phiếu ngay\n"
        "/tintuc - Tin tức thị trường mới nhất\n"
        "/phantich VCB - Phân tích chuyên sâu\n"
        "/dudoan 3ngay - Dự báo 3 ngày\n"
        "/dudoan 7ngay - Dự báo 1 tuần\n"
        "/dudoan thang - Dự báo tháng\n"
        "/dudoan quy - Dự báo quý\n"
        "/dudoan nam - Dự báo năm\n\n"
        f"⏰ Tự động {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày"
    )


# ── HÀM CHÍNH ────────────────────────────────────────────
async def main():
    print("🤖 FinanceAI Bot đang khởi động...")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("baocao",   cmd_baocao))
    app.add_handler(CommandHandler("gia",      cmd_gia))
    app.add_handler(CommandHandler("tintuc",   cmd_tintuc))
    app.add_handler(CommandHandler("phantich", cmd_phantich))
    app.add_handler(CommandHandler("dudoan",   cmd_dudoan))
    app.add_handler(CommandHandler("help",     cmd_help))

    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    scheduler.add_job(send_report, "cron", hour=SEND_HOUR, minute=SEND_MINUTE)
    scheduler.start()

    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"✅ FinanceAI Bot đã khởi động!\n"
             f"⏰ Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d} mỗi ngày\n\n"
             f"📌 Lệnh:\n"
             f"/baocao - Báo cáo realtime\n"
             f"/gia [mã] - Xem giá cổ phiếu\n"
             f"/tintuc - Tin tức mới nhất\n"
             f"/phantich - Phân tích chuyên sâu\n"
             f"/dudoan - Dự báo thị trường\n"
             f"/help - Hướng dẫn"
    )

    print(f"✅ Bot chạy! Tự động gửi lúc {SEND_HOUR:02d}:{SEND_MINUTE:02d}")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
