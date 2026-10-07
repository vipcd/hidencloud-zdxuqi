import os
import time
import sys
import random
import json
import urllib.request
from playwright.sync_api import sync_playwright

# --- 全局配置 ---
HIDENCLOUD_COOKIE = os.environ.get('HIDENCLOUD_COOKIE')
HIDENCLOUD_EMAIL = os.environ.get('HIDENCLOUD_EMAIL')
HIDENCLOUD_PASSWORD = os.environ.get('HIDENCLOUD_PASSWORD')

# --- 通知配置 ---
TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"
SERVICE_URL = f"{BASE_URL}/service/206500/manage"  # 请确认这是你的服务ID
DEFAULT_COOKIE_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def send_notification(title, message):
    """发送机器人通知的主函数"""
    full_message = f"🤖 {title}\n\n{message}\n\n⏰ 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    log(f"📣 准备发送通知: {title}")

    if TG_BOT_TOKEN and TG_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            data = json.dumps({"chat_id": TG_CHAT_ID, "text": full_message}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
            log("✅ 机器人通知发送成功！")
        except Exception as e:
            log(f"❌ 机器人通知发送失败: {e}")
    else:
        log("⚠️ 未配置通知环境变量 (TG_BOT_TOKEN / TG_CHAT_ID)，跳过发送通知。")

STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
"""

def handle_cloudflare(page):
    """通用 Cloudflare 验证处理逻辑"""
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    if page.locator(iframe_selector).count() == 0:
        return True

    log("⚠️ 检测到 Cloudflare 验证...")
    start_time = time.time()
    
    while time.time() - start_time < 60:
        if page.locator(iframe_selector).count() == 0:
            log("✅ 验证通过！")
            return True

        try:
            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            if checkbox.is_visible():
                log("点击验证复选框...")
                time.sleep(random.uniform(0.5, 1.5))
                checkbox.click()
                log("已点击，等待验证结果...")
                time.sleep(5)
            else:
                time.sleep(1)
        except Exception:
            pass
            
    log("❌ 验证超时。")
    return False

def inject_cookies(context, raw_cookie):
    """智能解析并批量注入 Cookie（支持 JSON 数组和普通字符串）"""
    if not raw_cookie:
        return False
    
    raw_cookie = raw_cookie.strip()
    
    # 尝试作为 JSON 数组解析
    if raw_cookie.startswith('[') or raw_cookie.startswith('{'):
        try:
            cookies_list = json.loads(raw_cookie)
            if isinstance(cookies_list, dict):
                cookies_list = [cookies_list]
            
            playwright_cookies = []
            for c in cookies_list:
                cookie_dict = {
                    'name': c.get('name'),
                    'value': str(c.get('value', '')),
                    'domain': c.get('domain', '.hidencloud.com'),
                    'path': c.get('path', '/'),
                }
                
                if 'expirationDate' in c and c['expirationDate']:
                    cookie_dict['expires'] = float(c['expirationDate'])
                if 'httpOnly' in c:
                    cookie_dict['httpOnly'] = bool(c['httpOnly'])
                if 'secure' in c:
                    cookie_dict['secure'] = bool(c['secure'])
                
                # 转化 sameSite 映射
                same_site = str(c.get('sameSite', '')).lower()
                if same_site in ['strict', 'lax', 'none']:
                    cookie_dict['sameSite'] = same_site.capitalize()
                elif same_site == 'no_restriction':
                    cookie_dict['sameSite'] = 'None'

                playwright_cookies.append(cookie_dict)
            
            context.add_cookies(playwright_cookies)
            log(f"✅ 成功提取并注入 JSON 中的 {len(playwright_cookies)} 个 Cookie。")
            return True
        except Exception as e:
            log(f"⚠️ 解析 JSON Cookie 失败 ({e})，将尝试以纯文本注入...")

    # 如果非 JSON，作为单个 value 字符串处理
    log("尝试作为单个 Cookie 字符串注入...")
    context.add_cookies([{
        'name': DEFAULT_COOKIE_NAME,
        'value': raw_cookie,
        'domain': '.hidencloud.com',
        'path': '/',
        'expires': int(time.time()) + 3600 * 24 * 365,
        'httpOnly': True,
        'secure': True,
        'sameSite': 'Lax'
    }])
    return True

def login(page):
    log("开始登录流程...")
    
    # 1. Cookie 登录尝试
    if HIDENCLOUD_COOKIE:
        log("尝试 Cookie 登录...")
        try:
            inject_cookies(page.context, HIDENCLOUD_COOKIE)
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            
            if "auth/login" not in page.url:
                log(f"✅ Cookie 登录成功！当前所在页面: {page.url}")
                return True
            log(f"Cookie 未生效或已失效，当前被引导至: {page.url}")
        except Exception as e:
            log(f"Cookie 登录过程发生错误: {e}")

    # 2. 账号密码登录
    if not HIDENCLOUD_EMAIL or not HIDENCLOUD_PASSWORD:
        log("❌ Cookie 登录失败，且未提供账号密码变量 (HIDENCLOUD_EMAIL / HIDENCLOUD_PASSWORD)。")
        send_notification("登录失败", "Cookie 失效且未在 GitHub Secrets 配置账号密码。")
        return False

    log("尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        
        page.fill('input[name="email"]', HIDENCLOUD_EMAIL)
        page.fill('input[name="password"]', HIDENCLOUD_PASSWORD)
        time.sleep(0.5)
        handle_cloudflare(page)
        
        page.click('button[type="submit"]')
        time.sleep(3)
        handle_cloudflare(page)
        
        page.wait_for_url(f"{BASE_URL}/*", timeout=30000)
        
        if "auth/login" in page.url:
             log("❌ 登录失败。")
             send_notification("登录失败", "账号或密码错误，或被系统拦截。")
             return False

        log("✅ 账号密码登录成功！")
        return True
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        page.screenshot(path="login_fail.png")
        send_notification("登录异常", f"执行登录时发生错误:\n{str(e)}")
        return False

def renew_service(page):
    try:
        log("进入续费流程...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        handle_cloudflare(page)

        log("准备点击 'Renew' 按钮...")
        renew_btn = page.locator('button:has-text("Renew")')
        create_btn = page.locator('button:has-text("Create Invoice")')
        
        modal_opened = False
        for i in range(3):
            try:
                renew_btn.wait_for(state="visible", timeout=10000)
                renew_btn.scroll_into_view_if_needed()
                
                log(f"第 {i+1} 次尝试点击 'Renew'...")
                renew_btn.click()
                
                log("等待弹窗出现...")
                try:
                    create_btn.wait_for(state="visible", timeout=5000)
                    modal_opened = True
                    log("✅ 弹窗已成功弹出！")
                    break 
                except:
                    log("⚠️ 弹窗未出现，可能是点击未响应，准备重试...")
                    time.sleep(2)
            except Exception as e:
                log(f"点击尝试出错: {e}")
        
        if not modal_opened:
            log("❌ 错误：尝试多次后，续费弹窗仍未出现。")
            page.screenshot(path="renew_modal_failed.png")
            send_notification("续费失败", "尝试多次点击 Renew 按钮后，创建账单弹窗仍未出现。")
            return False

        handle_cloudflare(page)
        
        log("点击 'Create Invoice'...")
        create_btn.click()
        
        log("等待发票生成...")
        new_invoice_url = None
        start_wait = time.time()
        
        while time.time() - start_wait < 90:
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面已跳转: {new_invoice_url}")
                break
            
            if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
                log("⚠️ 遇到拦截，尝试处理...")
                handle_cloudflare(page)
            
            time.sleep(1)
        
        if not new_invoice_url:
            log("❌ 未能进入发票页面，超时。")
            page.screenshot(path="renew_stuck_invoice.png")
            send_notification("续费超时", "已点击 Create Invoice，但长时间未跳转到账单支付页面。")
            return False

        if page.url != new_invoice_url:
            page.goto(new_invoice_url)
            
        handle_cloudflare(page)

        log("查找 'Pay' 按钮...")
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click()
        
        log("✅ 'Pay' 按钮已点击。")
        time.sleep(5)
        
        send_notification("🎉 续费成功", f"服务 [{SERVICE_URL}] 的续期发票已成功点击支付！")
        return True

    except Exception as e:
        log(f"❌ 续费异常: {e}")
        page.screenshot(path="renew_error.png")
        send_notification("续费异常", f"执行续费操作时发生错误:\n{str(e)}")
        return False

def main():
    if not HIDENCLOUD_COOKIE and not (HIDENCLOUD_EMAIL and HIDENCLOUD_PASSWORD):
        send_notification("配置错误", "未提供登录凭证（Cookie或账号密码），脚本退出。")
        sys.exit(1)

    with sync_playwright() as p:
        try:
            log("启动官方 Chrome (Linux版)...")
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars']
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.add_init_script(STEALTH_JS)

            if not login(page):
                sys.exit(1)

            if not renew_service(page):
                sys.exit(1)

            log("🎉 任务全部完成！")
        except Exception as e:
            log(f"💥 严重错误: {e}")
            send_notification("脚本严重崩溃", f"脚本运行中发生未知错误:\n{str(e)}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
