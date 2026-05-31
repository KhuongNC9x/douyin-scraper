# Douyin ACG Scraper

Tự động thu thập video ACG (二次元/anime) từ trang tìm kiếm Douyin, sắp xếp theo mới nhất, xuất file JSON/CSV/HTML và gửi báo cáo lên Slack.

---

## Tính năng

- Đăng nhập Douyin một lần, lưu cookie để tái sử dụng (không cần đăng nhập lại)
- Tự động hover vào bộ lọc **筛选** và chọn **最新发布** (mới nhất)
- Cuộn trang để tải thêm video
- Trích xuất: tiêu đề, tác giả, lượt thích, thời gian đăng, URL, thumbnail
- Dịch tiêu đề/thời gian từ tiếng Trung sang tiếng Việt (qua Google Translate)
- Xuất kết quả ra **JSON**, **CSV**, **HTML** (page source)
- Gửi báo cáo tóm tắt (top 5 video) lên **Slack** qua Incoming Webhook
- Hỗ trợ chạy **headless** trên CI/CD (GitHub Actions, v.v.)

---

## Cài đặt

```bash
pip install -r requirements.txt
```

**requirements.txt:**
```
selenium
webdriver-manager
requests
googletrans==4.0.0rc1
```

> Yêu cầu: **Python 3.10+** và **Google Chrome** đã cài trên máy.

---

## Cấu hình

Chỉnh các hằng số ở đầu file `douyin_scraper.py`:

| Biến | Mặc định | Mô tả |
|---|---|---|
| `TARGET_URL` | URL tìm kiếm 二次元 | URL Douyin cần scrape |
| `OUTPUT_DIR` | `./douyin_output` | Thư mục lưu kết quả |
| `SCROLL_COUNT` | `1` | Số lần cuộn trang |
| `SCROLL_PAUSE` | `2.0` | Giây chờ giữa mỗi lần cuộn |
| `COOKIE_FILE` | `./douyin_cookies.json` | File lưu cookie |

**Biến môi trường:**

| Biến | Mô tả |
|---|---|
| `SLACK_WEBHOOK` | URL Slack Incoming Webhook để nhận báo cáo |
| `HEADLESS` | `true` để chạy Chrome không hiện giao diện |
| `CI` | `true` khi chạy trên CI (tự bật headless, không dùng `input()`) |

---

## Cách dùng

### Lần đầu (cần đăng nhập thủ công)

```bash
python douyin_scraper.py
```

Script sẽ mở Chrome, bạn đăng nhập Douyin trên trình duyệt, sau đó nhấn **Enter**. Cookie sẽ được lưu vào `douyin_cookies.json` cho các lần chạy sau.

### Các lần sau

```bash
python douyin_scraper.py
```

Script tự động nạp cookie từ file, không cần đăng nhập lại.

### Chạy headless (không hiện giao diện)

```bash
HEADLESS=true python douyin_scraper.py
```

### Chạy trên CI/CD

Thiết lập các GitHub Secrets:
- `SLACK_WEBHOOK` — URL webhook Slack
- `DOUYIN_COOKIES` — Nội dung file `douyin_cookies.json` (xuất từ lần chạy thủ công)

Khi `CI=true` mà không có cookie, script sẽ dừng và gửi thông báo lỗi lên Slack.

---

## Kết quả đầu ra

Mỗi lần chạy tạo 3 file trong `./douyin_output/` với timestamp:

| File | Nội dung |
|---|---|
| `videos_YYYYMMDD_HHMMSS.json` | Danh sách video dạng JSON đầy đủ |
| `videos_YYYYMMDD_HHMMSS.csv` | Bảng CSV: title, author, likes, time, url |
| `page_YYYYMMDD_HHMMSS.html` | HTML thô của trang (dùng để debug selector) |

**Cấu trúc JSON mỗi video:**
```json
{
  "video_id": "7645481407343393529",
  "url": "https://www.douyin.com/video/7645481407343393529",
  "title": "标题...",
  "author": "tên tác giả",
  "likes": "1.2万",
  "time": "3天前",
  "thumbnail": "https://..."
}
```

---

## Luồng hoạt động

```
Mở douyin.com
    → Nạp cookie (hoặc đăng nhập thủ công)
    → Mở TARGET_URL
    → Hover 筛选 → chọn 最新发布
    → Cuộn trang SCROLL_COUNT lần
    → Trích xuất video từ DOM
    → Sắp xếp theo thời gian mới nhất
    → Lưu JSON + CSV + HTML
    → Gửi báo cáo Slack
```

---

## Ghi chú & xử lý sự cố

**Trích xuất được 0 video:** Douyin thường xuyên thay đổi class name CSS. Lưu file `page_*.html` và cập nhật lại các CSS selector trong hàm `extract_video_items()`.

**Cookie hết hạn:** Xóa `douyin_cookies.json` và chạy lại để đăng nhập thủ công.

**googletrans lỗi:** Thư viện này dùng API không chính thức của Google, đôi khi bị rate-limit. Nếu lỗi, script vẫn chạy bình thường — chỉ bỏ qua phần dịch.
