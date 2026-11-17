# KN IB HUB – Tool tự động đăng tin Trading / Vàng / XAUUSD / Bitcoin

Mỗi ngày đăng **2 bài** (08:00 và 20:00 giờ VN) lên Facebook Page **KN IB Hub**:
1. Lấy tin mới từ nguồn Mỹ: FXStreet, CNBC, MarketWatch, Investing.com, CoinDesk, Cointelegraph
2. Lọc theo chủ đề: Vàng/XAUUSD → Bitcoin → Vĩ mô (Fed, CPI, NFP) → Forex → Chứng khoán Mỹ
3. Viết lại tiêu đề + tóm tắt bằng tiếng Việt
4. Tạo ảnh 1080x1350 thương hiệu **KN IB HUB**
5. Đăng ảnh + caption lên Page, ghi nhớ tin đã đăng để không trùng

## Secrets cần có (Settings → Secrets and variables → Actions)
- `FB_PAGE_ID` – ID Page KN IB Hub
- `FB_PAGE_TOKEN` – mã truy cập Page (không hết hạn)
- `ANTHROPIC_API_KEY` – không bắt buộc; có thì tiếng Việt tự nhiên hơn, không có thì dùng Google Dịch

## Đăng thủ công
Tab **Actions** → *KN IB HUB Auto Post* → **Run workflow**.

## Tùy chỉnh
- Giờ đăng: sửa `cron` trong `.github/workflows/autopost.yml` (giờ UTC = giờ VN − 7)
- Nguồn tin / từ khóa: sửa `FEEDS` và `TOPICS` trong `main.py`
- Biến môi trường: `POSTS_PER_RUN`, `MAX_AGE_HOURS`, `BRAND`, `HASHTAGS`

## Lưu ý
- Tool viết lại ngắn gọn và ghi rõ nguồn, không chép nguyên bài báo.
- Lỗi `(#200) permissions` → mã thiếu quyền `pages_manage_posts`.
- Lỗi `(#190)` → mã hết hạn, cần lấy lại mã Page.
