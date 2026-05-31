"""
Douyin ACG Scraper - Tự động lấy nội dung từ Douyin
Yêu cầu: pip install selenium webdriver-manager requests googletrans==4.0.0rc1
"""

import re
import time
import json
import os
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
try:
    from googletrans import Translator
    _translator = Translator()
    TRANSLATE_ENABLED = True
except ImportError:
    TRANSLATE_ENABLED = False
    print("[!] googletrans chưa cài — bỏ qua dịch. Chạy: pip install googletrans==4.0.0rc1")

# ─── CẤU HÌNH ────────────────────────────────────────────────────────────────
TARGET_URL  = "https://www.douyin.com/jingxuan/acg/search/二次元?aid=60b5e0b8-0186-478b-9103-2ea6b51e4836&type=general"
OUTPUT_DIR  = "./douyin_output"
SCROLL_COUNT = 1
SCROLL_PAUSE = 2.0
COOKIE_FILE = "./douyin_cookies.json"

# CI mode: tự động bật headless, không dùng input()
IS_CI       = os.environ.get("CI", "false").lower() == "true"
HEADLESS    = IS_CI or os.environ.get("HEADLESS", "false").lower() == "true"

# Slack webhook: đọc từ env var (set trong GitHub Secrets hoặc file .env.local)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK", "")
# ─────────────────────────────────────────────────────────────────────────────


def translate_zh_vi(text: str) -> str:
    """Dịch tiếng Trung → tiếng Việt qua Google Translate free."""
    if not TRANSLATE_ENABLED or not text or not text.strip():
        return text
    try:
        result = _translator.translate(text, src="zh-cn", dest="vi")
        return result.text
    except Exception:
        return text  # Trả về bản gốc nếu lỗi


def setup_driver(headless: bool = False) -> webdriver.Chrome:
    """Khởi tạo Chrome driver."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--window-size=1400,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def save_cookies(driver: webdriver.Chrome, path: str) -> None:
    """Lưu cookie hiện tại ra file."""
    cookies = driver.get_cookies()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"[✓] Đã lưu {len(cookies)} cookies → {path}")


def load_cookies(driver: webdriver.Chrome, path: str) -> bool:
    """Nạp cookie từ file (phải mở douyin.com trước)."""
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    for cookie in cookies:
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    print(f"[✓] Đã nạp {len(cookies)} cookies từ {path}")
    return True


def scroll_and_collect(driver: webdriver.Chrome, scroll_count: int, pause: float) -> None:
    """Cuộn trang để load thêm nội dung."""
    last_height = driver.execute_script("return document.body.scrollHeight")
    for i in range(scroll_count):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)
        new_height = driver.execute_script("return document.body.scrollHeight")
        print(f"  Cuộn {i+1}/{scroll_count} | chiều cao trang: {new_height}px")
        if new_height == last_height:
            print("  → Đã đến cuối trang, dừng cuộn.")
            break
        last_height = new_height


def extract_video_items(driver: webdriver.Chrome) -> list[dict]:
    """Trích xuất thông tin video từ DOM."""
    items = []
    try:
        # Mỗi card video nằm trong div.AMqhOzPC với id="waterfall_item_XXXX"
        cards = driver.find_elements(By.CSS_SELECTOR, "div[id^='waterfall_item_']")
        if not cards:
            # Fallback
            cards = driver.find_elements(By.CSS_SELECTOR, "div.search-result-card")

        print(f"  Tìm thấy {len(cards)} card")

        for card in cards:
            item = {}

            # Video ID từ id attribute → tạo URL
            try:
                card_id = card.get_attribute("id")  # waterfall_item_7645481407343393529
                if card_id and "waterfall_item_" in card_id:
                    video_id = card_id.replace("waterfall_item_", "")
                    item["url"] = f"https://www.douyin.com/video/{video_id}"
                    item["video_id"] = video_id
            except Exception:
                item["url"] = ""

            # Title: div đầu tiên trong block bottom (không dùng class hash)
            try:
                item["title"] = card.find_element(
                    By.XPATH, ".//div[contains(@class,'search-result-card')]//div[last()]//div[1]//div[1]"
                ).text
            except Exception:
                item["title"] = ""

            # Author: span thứ 2 trong span chứa "@"
            try:
                item["author"] = card.find_element(
                    By.XPATH, ".//span[./span[text()='@']]/span[last()]"
                ).text
            except Exception:
                item["author"] = ""

            # Thời gian: span có text chứa "前" hoặc "周" hoặc "天" hoặc "小时" hoặc "分钟"
            try:
                item["time"] = card.find_element(
                    By.XPATH, ".//span[contains(text(),'前') or contains(text(),'周') or contains(text(),'天')]"
                ).text.replace(" · ", "").strip()
            except Exception:
                item["time"] = ""

            # Likes: span chứa số sau SVG heart (span cuối trong block overlay)
            try:
                item["likes"] = card.find_element(
                    By.XPATH, ".//span[contains(text(),'万') or (string-length(text()) > 0 and number(text()) = number(text()))]"
                ).text
            except Exception:
                item["likes"] = ""

            # Thumbnail
            try:
                img = card.find_element(By.CSS_SELECTOR, "img.fnWBjiik")
                item["thumbnail"] = img.get_attribute("src")
            except Exception:
                try:
                    img = card.find_element(By.TAG_NAME, "img")
                    item["thumbnail"] = img.get_attribute("src")
                except Exception:
                    item["thumbnail"] = ""

            if item.get("title") or item.get("url"):
                items.append(item)

    except Exception as e:
        print(f"[!] Lỗi khi extract: {e}")
    return items


def save_results(items: list[dict], html: str, output_dir: str) -> None:
    """Lưu kết quả ra file."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Lưu JSON
    json_path = os.path.join(output_dir, f"videos_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"[✓] JSON  → {json_path}  ({len(items)} video)")

    # Lưu HTML thô
    html_path = os.path.join(output_dir, f"page_{ts}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[✓] HTML  → {html_path}")

    # Lưu CSV đơn giản
    csv_path = os.path.join(output_dir, f"videos_{ts}.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("title,author,likes,time,url\n")
        for v in items:
            title   = v.get("title","").replace(",","，")
            author  = v.get("author","").replace(",","，")
            likes   = v.get("likes","")
            t       = v.get("time","")
            url     = v.get("url","")
            f.write(f"{title},{author},{likes},{t},{url}\n")
    print(f"[✓] CSV   → {csv_path}")


def click_element(driver: webdriver.Chrome, selectors: list[str], label: str, timeout: int = 8) -> bool:
    """Thử click lần lượt các selector, trả về True nếu thành công."""
    for sel in selectors:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH if sel.startswith("//") else By.CSS_SELECTOR, sel))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            el.click()
            print(f"  [✓] {label}")
            return True
        except Exception:
            continue
    print(f"  [!] Không tìm thấy: {label} — bỏ qua")
    return False


def apply_filters(driver: webdriver.Chrome) -> None:
    """Hover vào 筛选 → chọn 最新发布."""

    # 1. Hover vào nút 筛选 để mở panel
    for sel in [
        "//div[contains(@class,'jjU9T0dQ')]",
        "//span[contains(@class,'QfeM8ow3')]",
        "//span[contains(text(),'筛选')]",
    ]:
        try:
            el = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, sel))
            )
            ActionChains(driver).move_to_element(el).perform()
            print("  [✓] Hover vào 筛选")
            break
        except Exception:
            continue
    time.sleep(1.5)

    # 2. Click 最新发布 bằng JS để tránh bị panel đóng trước
    try:
        el = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, "//span[@data-index1='0' and @data-index2='1']"))
        )
        driver.execute_script("arguments[0].click();", el)
        print("  [✓] Sort 最新发布")
    except Exception as e:
        print(f"  [!] Không click được 最新发布: {e}")
    time.sleep(3)
    print("  [✓] Đã áp dụng filter xong")


def time_to_minutes(t: str) -> int:
    """Chuyển '2小时前', '1周前'... thành số phút để so sánh."""
    t = t.replace(" · ", "").strip()
    m = re.search(r"(\d+)", t)
    n = int(m.group(1)) if m else 0
    if "分钟" in t: return n
    if "小时" in t: return n * 60
    if "天"  in t: return n * 60 * 24
    if "周"  in t: return n * 60 * 24 * 7
    if "月"  in t: return n * 60 * 24 * 30
    return 99999


def send_slack_report(items: list[dict], output_dir: str, error: str = None) -> None:
    """Gửi report tóm tắt lên Slack qua webhook."""
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    if error:
        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "❌ Douyin Scraper — Thất bại", "emoji": True}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Thời gian:*\n{ts}"},
                        {"type": "mrkdwn", "text": f"*Lỗi:*\n`{error}`"},
                    ]
                }
            ]
        }
    else:
        # Lấy top 5 video có title để preview
        preview_lines = []
        count = 0
        for v in items:
            if count >= 5:
                break
            url    = v.get("url", "").strip()
            likes  = f"  ♥ {v['likes']}" if v.get("likes") else ""
            author = f"@{v['author']}" if v.get("author") else ""
            title  = translate_zh_vi(v.get("title", "").strip())
            t      = translate_zh_vi(v.get("time", "").strip())
            t      = f"  ⏰{t}" if t else ""
            if not url:
                continue
            line = f"• {title}\n  {author}{likes}{t}\n  🔗 {url}"
            preview_lines.append(line)
            count += 1

        preview_text = "\n".join(preview_lines) if preview_lines else "_Không trích xuất được nội dung_"
        files_path = os.path.abspath(output_dir)

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "✅ Douyin Scraper — Hoàn tất", "emoji": True}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Thời gian:*\n{ts}"},
                        {"type": "mrkdwn", "text": f"*Tổng video tìm thấy:*\n{len(items)} video"},
                        {"type": "mrkdwn", "text": f"*Keyword:*\n二次元 (ACG → 动漫)"},
                        {"type": "mrkdwn", "text": f"*Kết quả lưu tại:*\n`{files_path}`"},
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*🎬 Top {count} video:*\n{preview_text}"}
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"📁 File đầu ra: JSON · CSV · HTML  |  Scroll: {SCROLL_COUNT} lần  |  Sort: 最新发布"}
                    ]
                }
            ]
        }

    try:
        resp = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        if resp.status_code == 200:
            print("[✓] Đã gửi report lên Slack")
        else:
            print(f"[!] Slack trả về lỗi: {resp.status_code} — {resp.text}")
    except Exception as e:
        print(f"[!] Không gửi được Slack: {e}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    driver = setup_driver(headless=HEADLESS)

    try:
        # ── Bước 1: Mở Douyin để set domain cookie ──
        print("[1] Mở trang Douyin...")
        driver.get("https://www.douyin.com")
        time.sleep(3)

        # ── Bước 2: Thử nạp cookie cũ hoặc yêu cầu đăng nhập ──
        if load_cookies(driver, COOKIE_FILE):
            driver.refresh()
            time.sleep(3)
            print("[2] Đã dùng cookie cũ, bỏ qua đăng nhập.")
        else:
            if IS_CI:
                print("[2] Chạy trên CI nhưng không có cookie — dừng lại.")
                send_slack_report([], OUTPUT_DIR, error="Không tìm thấy cookie. Cần cập nhật DOUYIN_COOKIES secret.")
                return
            print("[2] Chưa có cookie — vui lòng ĐĂNG NHẬP trên trình duyệt.")
            print("    Sau khi đăng nhập xong, quay lại đây và nhấn Enter...")
            input("    >>> Nhấn Enter khi đã đăng nhập: ")
            save_cookies(driver, COOKIE_FILE)

        # ── Bước 3: Mở URL mục tiêu ──
        print(f"[3] Mở URL mục tiêu...")
        driver.get(TARGET_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)

        # ── Bước 4: Chọn filter 动漫 → 最新发布 ──
        print("[4] Áp dụng filter...")
        apply_filters(driver)

        # ── Bước 5: Cuộn trang để load nội dung ──
        print(f"[5] Cuộn trang {SCROLL_COUNT} lần để load thêm video...")
        scroll_and_collect(driver, SCROLL_COUNT, SCROLL_PAUSE)

        # ── Bước 6: Trích xuất dữ liệu ──
        print("[6] Trích xuất thông tin video...")
        items = extract_video_items(driver)
        html  = driver.page_source
        print(f"    → Tìm thấy {len(items)} video")

        if len(items) == 0:
            print("\n⚠️  CẢNH BÁO: Không trích xuất được video nào!")
            print("    Có thể Douyin đã thay đổi class name.")
            print("    → Hãy lưu lại HTML trang và gửi để cập nhật selector.")
            save_results(items, html, OUTPUT_DIR)
            send_slack_report(items, OUTPUT_DIR, error="Trích xuất được 0 video — Douyin có thể đã thay đổi cấu trúc DOM. Cần cập nhật selector.")
            return

        # ── Sắp xếp theo thời gian mới nhất ──
        items.sort(key=lambda v: time_to_minutes(v.get("time", "")))

        # ── Bước 7: Lưu kết quả ──
        print("[7] Lưu kết quả...")
        save_results(items, html, OUTPUT_DIR)

        # ── Bước 8: Gửi report lên Slack ──
        print("[8] Gửi report lên Slack...")
        send_slack_report(items, OUTPUT_DIR)

        print("\n✅ Hoàn tất!")

    except Exception as e:
        print(f"\n[✗] Lỗi: {e}")
        import traceback; traceback.print_exc()
        send_slack_report([], OUTPUT_DIR, error=str(e))
    finally:
        if not IS_CI:
            input("\nNhấn Enter để đóng trình duyệt...")
        driver.quit()


if __name__ == "__main__":
    main()
