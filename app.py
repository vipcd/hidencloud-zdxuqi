#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os,re,sys,time,random,requests,urllib.parse
try:
    from patchright.sync_api import sync_playwright
    USING_PATCHRIGHT = True
except ImportError:
    from playwright.sync_api import sync_playwright
    USING_PATCHRIGHT = False

# --- 环境变量 (可在Settings里设置secrets或者私库直接填写在双引号里)---
EMAIL         = os.environ.get('EMAIL') or ""            # 登录邮箱（仅 TG 通知用）
REGION        = os.environ.get('REGION') or "🎉"         # 地区,（仅 TG 通知用）, 可填写emoji示例：🇸🇬  🇦🇪  🇦🇺  🇲🇽  🇫🇷  🇮🇳  🇺🇸 
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN') or ""    # Discord Token，必填！用于Discord OAuth登录（站点要求免费服务续期必须Discord登录）
TG_CHAT_ID    = os.environ.get('TG_CHAT_ID') or ""       # Telegram Chat ID,可选
TG_BOT_TOKEN  = os.environ.get('TG_BOT_TOKEN') or ""     # Telegram Bot Token,可选

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"
DISCORD_OAUTH_LOGIN_URL = f"{BASE_URL}/oauth/discord/login"

# --- 代理配置（由工作流 shell 脚本写入 $GITHUB_ENV）---
IS_PROXY      = os.environ.get('IS_PROXY', 'false').lower() == 'true'
PROXY_SERVER  = os.environ.get('PROXY_SERVER') or "http://127.0.0.1:1081"
REQUESTS_PROXIES = {"http": PROXY_SERVER, "https": PROXY_SERVER} if IS_PROXY else None

# Cloudflare 整页挑战 / Turnstile 组件共用的 iframe 选择器
CF_IFRAME_SELECTOR = 'iframe[src*="challenges.cloudflare.com"]'

# 按运行平台选择 UA
if sys.platform == 'win32':
    DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
else:
    DEFAULT_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

# 日志
def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

STEALTH_JS = """
try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
} catch (e) {}
"""

def get_current_ip(proxy_server=None):
    """获取当前出口IP"""
    proxies = {"http": proxy_server, "https": proxy_server} if (proxy_server and IS_PROXY) else None
    try:
        resp = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
        if resp.status_code == 200:
            return resp.text.strip()
        return "获取失败"
    except Exception as e:
        log(f"❌ 获取出口IP失败: {e}")
        return "获取失败"

def send_telegram_notification(status, old_due="未知", new_due="未知", current_ip="未知"):
    """发送 Telegram 通知"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram 未配置，跳过通知")
        return False
    
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)
    if '@' in EMAIL:
        name, domain = EMAIL.split('@', 1)
        if len(name) > 4:
            masked_email = f"{name[:2]}****{name[-2:]}@{domain}"
        else:
            masked_email = f"{name}@{domain}"
    else:
        masked_email = (EMAIL[:2] + '****') if EMAIL else "Discord用户"

    text = (
        f"{REGION} HidenCloud 续期通知\n\n"
        f"{status}\n"
        f"👤 账号: {masked_email}\n"
        f"📅 续期前到期：{old_due}\n"
        f"📅 续期后到期：{new_due}\n"
        f"🌐 续期使用IP: {current_ip}\n"
        f"🕒 续期时间：{now}"
    )
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10, proxies=REQUESTS_PROXIES)
        if resp.status_code == 200:
            log("✅ Telegram 通知发送成功")
            return True
        else:
            log(f"❌ Telegram 通知失败: {resp.text}")
            return False
    except Exception as e:
        log(f"❌ Telegram 通知异常: {e}")
        return False

def _get_turnstile_token(page):
    try:
        return page.evaluate(
            """
            () => {
                try {
                    if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
                        let t = null;
                        try { t = window.turnstile.getResponse(); } catch (e) {}
                        if (t && t.length > 30) return t;
                        for (let i = 0; i < 5; i++) {
                            try { t = window.turnstile.getResponse(String(i)); } catch (e) { t = null; }
                            if (t && t.length > 30) return t;
                        }
                    }
                } catch (e) {}
                const inputs = document.querySelectorAll(
                    'input[name="cf-turnstile-response"], input[id$="_response"]'
                );
                for (const el of inputs) {
                    if (el.value && el.value.length > 30) return el.value;
                }
                return null;
            }
            """
        )
    except Exception:
        return None

def _find_visible_cf_frames(page):
    result = []
    try:
        for handle in page.query_selector_all(CF_IFRAME_SELECTOR):
            try:
                box = handle.bounding_box()
                if box and box['width'] > 10 and box['height'] > 10:
                    result.append(handle)
            except Exception:
                continue
    except Exception:
        pass
    return result

def _cf_checkbox_visible(page):
    for frame in page.frames:
        if 'challenges.cloudflare.com' not in (frame.url or ''):
            continue
        try:
            if frame.locator('input[type="checkbox"]:visible').count() > 0:
                return True
        except Exception:
            continue
    return False

def _click_cf_checkbox(page, frame_el=None):
    for frame in page.frames:
        if 'challenges.cloudflare.com' not in (frame.url or ''):
            continue
        try:
            frame.locator('input[type="checkbox"]').first.click(timeout=2500)
            return True
        except Exception:
            continue
    if frame_el is None:
        return False
    try:
        try:
            frame_el.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        box = frame_el.bounding_box()
        if not box:
            return False
        x = box['x'] + random.uniform(18, 34)
        y = box['y'] + box['height'] / 2 + random.uniform(-4, 4)
        page.mouse.move(x - random.uniform(30, 60), y + random.uniform(-8, 8))
        time.sleep(random.uniform(0.15, 0.4))
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.05, 0.2))
        page.mouse.down()
        time.sleep(random.uniform(0.04, 0.1))
        page.mouse.up()
        return True
    except Exception:
        return False

SECURITY_TITLE_HINTS = ('security verification', 'just a moment', 'attention required', 'checking your browser', '请稍候', 'please wait', 'one more step', 'protection enabled')

def _is_security_check_page(page):
    try:
        title = (page.title() or '').lower()
        if any(h in title for h in SECURITY_TITLE_HINTS):
            return True
    except Exception:
        return True
    try:
        return page.evaluate(
            """
            () => {
                const t = document.body ? document.body.innerText.slice(0, 5000).toLowerCase() : '';
                return t.includes('verify you are human') || t.includes('checking your browser')
                    || t.includes('security verification')
                    || t.includes('verifying the security of your connection');
            }
            """
        )
    except Exception:
        return True

def _has_interstitial_iframe(page):
    try:
        for handle in page.query_selector_all(CF_IFRAME_SELECTOR):
            if '/turnstile/' not in (handle.get_attribute('src') or ''):
                return True
    except Exception:
        pass
    return False

def _click_security_submit(page):
    for text in ('Verify', 'Continue', 'Submit', 'Proceed', '验证'):
        try:
            btn = page.locator(f'button:has-text("{text}"):visible, input[type="submit"]:visible').first
            if btn.count() > 0:
                btn.click(timeout=3000)
                log(f"🖱️ 已点击安全验证页的确认按钮（{text}）...")
                return True
        except Exception:
            continue
    return False

def handle_cloudflare(page, timeout=240):
    def challenge_active():
        return _has_interstitial_iframe(page) or _is_security_check_page(page)

    if not challenge_active():
        for _ in range(3):
            time.sleep(1)
            if challenge_active():
                break
        else:
            return True

    log("🔒 检测到 Cloudflare 安全验证...")
    time.sleep(5)

    effective_timeout = timeout + (180 if timeout > 60 else 0)
    manual_hinted = False
    start_time = time.time()
    last_click = 0
    clear_rounds = 0
    while time.time() - start_time < effective_timeout:
        if not challenge_active():
            clear_rounds += 1
            if clear_rounds >= 2: 
                return True
            time.sleep(1)
            continue
        clear_rounds = 0
        if not manual_hinted and timeout > 60 and time.time() - start_time > timeout - 30:
            log("🤝 自动点击未能通过验证，脚本会继续等待...")
            manual_hinted = True
        if time.time() - last_click > 6:
            frames = _find_visible_cf_frames(page)
            if frames:
                log("🖱️ 点击 Turnstile 验证......")
                if _click_cf_checkbox(page, frames[-1]):
                    last_click = time.time()
                    time.sleep(random.uniform(3, 5))
                    continue
            elif _get_turnstile_token(page) and _is_security_check_page(page):
                if _click_security_submit(page):
                    last_click = time.time()
                    time.sleep(random.uniform(2, 4))
                    continue
        time.sleep(1)
    log("❌ 验证超时。")
    return False

def solve_modal_turnstile(page, timeout=90):
    log("🛡️ 开始处理 Turnstile 验证...")
    start = time.time()
    last_click = 0
    clicks = 0
    no_frame_seconds = 0
    while time.time() - start < timeout:
        if _get_turnstile_token(page):
            log("✅ Turnstile 验证通过！")
            return True
        frames = _find_visible_cf_frames(page)
        if not frames:
            no_frame_seconds += 1
            if no_frame_seconds >= 20 and clicks == 0:
                log("ℹ️ 未检测到 Turnstile 验证框，无需验证。")
                return True
            time.sleep(1)
            continue
        no_frame_seconds = 0
        if clicks > 0 and time.time() - last_click > 4 and not _cf_checkbox_visible(page):
            time.sleep(2)
            if not _cf_checkbox_visible(page):
                log("✅ Turnstile 复选框已消失，视为验证通过！")
                return True
        if time.time() - last_click > 6 and _cf_checkbox_visible(page):
            log(f"🖱️ 点击 Turnstile 复选框（第 {clicks + 1} 次）...")
            if _click_cf_checkbox(page, frames[-1]):
                clicks += 1
                last_click = time.time()
                time.sleep(random.uniform(3, 5))
                continue
        if clicks == 0 and time.time() - start > 20 and time.time() - last_click > 6:
            if _click_cf_checkbox(page, frames[-1]):
                clicks += 1
                last_click = time.time()
                time.sleep(random.uniform(3, 5))
                continue
        time.sleep(1)
    if _get_turnstile_token(page):
        log("✅ Turnstile 验证通过！")
        return True
    log("❌ Turnstile 验证超时。")
    return False

def open_browser(p):
    proxy_arg = {"server": PROXY_SERVER} if IS_PROXY else None
    if USING_PATCHRIGHT:
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            args=['--disable-infobars'],
            proxy=proxy_arg,
        )
        ctx = browser.new_context(viewport=None, proxy=proxy_arg)
        page = ctx.new_page()
        return browser, page
    browser = p.chromium.launch(
        channel="chrome",
        headless=False,
        args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars']
    )
    ctx = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent=DEFAULT_UA,
        proxy=proxy_arg,
    )
    page = ctx.new_page()
    page.add_init_script(STEALTH_JS)
    return browser, page

def _is_logged_in(page, strict=False):
    try:
        url = page.url or ''
        if 'dash.hidencloud.com' not in url:
            return False
        if 'auth/login' in url or _is_security_check_page(page):
            return False
        if strict:
            try:
                body = (page.locator("body").inner_text(timeout=8000) or "").lower()
            except Exception:
                return False
            login_markers = ('sign in to your account', 'email or username', 'forgot password',
                             'sign in with discord', 'sign in with google')
            if any(m in body for m in login_markers):
                return False
            console_markers = ('dashboard', 'invoices', 'balance', 'tickets', 'your services', 'notifications')
            if not any(m in body for m in console_markers):
                return False
        return True
    except Exception:
        return False

DISCORD_AUTHORIZE_JS = """
async (cfg) => {
    const resp = await fetch('https://discord.com/api/v9/oauth2/authorize?' + cfg.query, {
        method: 'POST',
        headers: {
            'content-type': 'application/json',
            'authorization': cfg.token,
            'x-discord-locale': 'en-US'
        },
        body: JSON.stringify({
            permissions: '0',
            authorize: true,
            integration_type: 0,
            location_context: { guild_id: '10000', channel_id: '10000', channel_type: 10000 }
        })
    });
    let data = {};
    try { data = await resp.json(); } catch (e) {}
    return { status: resp.status, location: (data && data.location) || '' };
}
"""

def _extract_authorize_query(url):
    if not url:
        return ""
    if '/oauth2/authorize' in url and '?' in url:
        return url.split('?', 1)[1]
    m = re.search(r'[?&]redirect_to=([^&]+)', url)
    if m:
        try:
            target = urllib.parse.unquote(m.group(1))
        except Exception:
            return ""
        if 'oauth2/authorize?' in target:
            return target.split('oauth2/authorize?', 1)[1]
    return ""

def discord_login(page):
    if not DISCORD_TOKEN:
        log("ℹ️ 未配置 DISCORD_TOKEN，跳过 Discord OAuth 登录")
        return False
    log("🔑 尝试 Discord OAuth 登录...")
    try:
        if _is_logged_in(page, strict=True):
            return True

        page.goto(DISCORD_OAUTH_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        query = ""
        nav_start = time.time()
        while time.time() - nav_start < 90:
            url = page.url or ""
            if 'discord.com' in url:
                query = _extract_authorize_query(url)
                if query:
                    break
            elif 'dash.hidencloud.com' in url:
                if '/oauth/' in url:
                    handle_cloudflare(page, timeout=60)
                elif '/auth/login' in url:
                    if time.time() - nav_start > 10:
                        break
                elif _is_logged_in(page, strict=True):
                    log("✅ 检测到 Discord 已授权会话，直接登录成功")
                    return True
                else:
                    handle_cloudflare(page, timeout=60)
            time.sleep(1)

        if not query:
            log("❌ 未能获取 Discord OAuth 授权参数")
            page.screenshot(path="discord_oauth_fail.png")
            return False

        result = page.evaluate(DISCORD_AUTHORIZE_JS, {"query": query, "token": DISCORD_TOKEN}) or {}
        location = result.get("location", "")
        status = result.get("status", 0)
        if status != 200 or not location:
            log(f"❌ Discord 授权失败 (HTTP {status})，Token 可能已失效")
            page.screenshot(path="discord_auth_fail.png")
            return False

        page.goto(location, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page, timeout=120)
        time.sleep(2)
        handle_cloudflare(page, timeout=60)
        if _is_logged_in(page, strict=True):
            log("✅ Discord OAuth 登录成功！已进入控制台")
            return True
        return False
    except Exception as e:
        log(f"❌ Discord OAuth 登录异常: {e}")
        return False

def login(page):
    if not DISCORD_TOKEN:
        log("❌ 缺少 DISCORD_TOKEN，无法登录")
        return False
    if discord_login(page):
        return True
    status = "❌ 登录失败（Discord OAuth，请检查 DISCORD_TOKEN 是否有效）"
    send_telegram_notification(status)
    page.screenshot(path="login_fail.png")
    return False

def get_server_id(page):
    try:
        if 'dash.hidencloud.com' not in page.url:
            page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            time.sleep(2)
        handle_cloudflare(page)
        time.sleep(3)
        html = page.content()

        matches = re.findall(r'/service/(\d+)/manage', html)
        if matches:
            return matches[0]

        matches = [m for m in re.findall(r'#(\d{4,})', html) if set(m) != {'0'}]
        if matches:
            return matches[0]

        status = "❌ 未获取到server ID, 检查服务是否被删除"
        send_telegram_notification(status)
        return None
    except Exception as e:
        log(f"❌ 获取 Server ID 失败: {e}")
        return None

def get_due_date(page):
    try:
        if SERVICE_URL not in page.url:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        body_text = page.locator("body").inner_text()
        patterns = [
            r"Due date\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date\s*\n\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
            r"Due date.*?(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
    except Exception as e:
        log(f"❌ 获取Due Date失败: {e}")
    return "未知"

def renew_service(page):
    try:
        log("➡ 进入续期流程...")
        for renew_round in range(3):
            if page.url != SERVICE_URL or "/auth/login" in (page.url or ""):
                page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            time.sleep(12)
            log("🖱️ 准备点击 Renew 按钮...")
            renew_btn = page.locator('button:has-text("Renew")')
            create_btn = page.locator('button:has-text("Create Invoice")')
            modal_opened = False
            for i in range(6):
                try:
                    renew_btn.wait_for(state="visible", timeout=10000)
                    renew_btn.scroll_into_view_if_needed()
                    renew_btn.click()
                    time.sleep(3)
                    page_text = page.locator("body").inner_text()
                    if "Renewal Restricted" in page_text or "can only renew" in page_text.lower():
                        log("⚠️ 未到续期时间，无法续期。")
                        page.screenshot(path="renew_not_allowed.png")
                        return "NOT_TIME" 

                    try:
                        create_btn.wait_for(state="visible", timeout=8000)
                        modal_opened = True
                        log("✅ 弹窗已成功弹出！")
                        break
                    except:
                        time.sleep(2)
                except Exception as e:
                    log(f"❌ 点击尝试出错: {e}")

            if not modal_opened:
                log("❌ 错误：尝试多次后，续费弹窗仍未出现。")
                page.screenshot(path="renew_modal_failed.png")
                return False

            handle_cloudflare(page, timeout=60)
            if not solve_modal_turnstile(page, timeout=90):
                log("⚠️ Turnstile 未确认通过，仍将尝试提交...")

            new_invoice_url = None
            kicked_to_login = False
            time.sleep(2)
            for attempt in range(6):
                log(f"🖱️ 点击 Create Invoice（第 {attempt + 1} 次）...")
                try:
                    create_btn.wait_for(state="visible", timeout=30000)
                    
                    # 🛠️ 核心修复：自动移除可能拦截点击的 Cookie/隐私合规弹窗（#ncmp__tool）
                    try:
                        page.evaluate("() => { const banner = document.getElementById('ncmp__tool'); if (banner) banner.remove(); }")
                    except Exception:
                        pass

                    # 使用 force=True 彻底绕过指针事件拦截
                    create_btn.click(force=True, timeout=20000)
                except Exception as e:
                    log(f"⚠️ 点击 Create Invoice 失败: {e}")
                    solve_modal_turnstile(page, timeout=45)
                    time.sleep(2)
                    continue

                start_wait = time.time()
                while time.time() - start_wait < 30:
                    if "/payment/invoice/" in page.url:
                        new_invoice_url = page.url
                        log(f"🎉 页面已跳转: {new_invoice_url}")
                        break
                    if "/auth/login" in (page.url or ""):
                        kicked_to_login = True
                        break
                    if _has_interstitial_iframe(page) or _is_security_check_page(page):
                        handle_cloudflare(page, timeout=60)
                    time.sleep(1)
                if new_invoice_url:
                    break
                if kicked_to_login:
                    break

                solve_modal_turnstile(page, timeout=45)

            if new_invoice_url:
                break

            if kicked_to_login:
                if not discord_login(page):
                    return False
                continue

            return False
        else:
            return False

        if page.url != new_invoice_url:
            page.goto(new_invoice_url)
        handle_cloudflare(page)

        # 🛠️ 补全发票页的 Pay 按钮点击与支付确认
        log("🔎 查找 Pay 按钮...")
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click(force=True)
        log("✅ Pay 按钮已点击")
        
        time.sleep(6)
        page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        return True

    except Exception as e:
        log(f"❌ 续费异常: {e}")
        page.screenshot(path="renew_error.png")
        return False

def main():
    if not DISCORD_TOKEN:
        log("❌ 缺少 DISCORD_TOKEN，无法登录")
        sys.exit(1)

    global SERVICE_URL

    with sync_playwright() as p:
        browser = None
        try:
            if IS_PROXY:
                log(f"⚙️ 代理已启用: {PROXY_SERVER}")
            else:
                log("🌐 直连模式（未使用代理）")
            
            current_ip = get_current_ip(PROXY_SERVER)
            log(f"🎯 当前出口IP: {current_ip}")

            log("🚀 启动反检测内核浏览器...")
            browser, page = open_browser(p)

            if not login(page):
                sys.exit(1)

            server_id = get_server_id(page)
            if not server_id:
                log("❌ 无法获取 Server ID，退出。")
                sys.exit(1)
            SERVICE_URL = f"{BASE_URL}/service/{server_id}/manage"

            old_due = get_due_date(page)
            log(f"📆 续费前到期时间：{old_due}")

            renew_result = renew_service(page)

            new_due = old_due
            if renew_result == "NOT_TIME":
                status = "⏳ 未到续期时间"
            elif renew_result is False:
                status = "❌ 续期失败"
            else:
                new_due = get_due_date(page)
                status = "✅ 续期成功"

            send_telegram_notification(status, old_due, new_due, current_ip)

            if renew_result == "NOT_TIME":
                sys.exit(0)
            elif renew_result is False:
                sys.exit(1)
            else:
                sys.exit(0)
        except Exception as e:
            log(f"❌ 浏览器启动出错: {e}")
            sys.exit(1)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
                
if __name__ == "__main__":
    main()
