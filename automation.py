import os
import time
import shutil
import base64
import hashlib
import json
import random
import socket
import struct
import subprocess
import urllib.request
from urllib.parse import urlparse

from dotenv import dotenv_values
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    NoAlertPresentException,
    NoSuchWindowException,
    NoSuchElementException,
    ElementNotInteractableException,
    InvalidArgumentException,
    WebDriverException,
    UnexpectedAlertPresentException,
)

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        r"Google\Chrome\Application\chrome.exe",
    ),
]
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DATA_DIR = os.environ.get("LOCALAPPDATA") or _APP_DIR
_CHROME_PROFILE_BASE = os.path.join(_APP_DATA_DIR, "elec-car", "chrome-debug")
_DEBUG_DIR = os.path.join(_APP_DIR, "debug")

LOGIN_URL = "https://ev.or.kr/nportal/login.do"
FORM_URL = "https://ev.or.kr/ev_ps/ps/seller/sellerApplyform"
DEFAULT_LOGIN_ID = "D034726"

# 필수 env 항목: (키, 표시명, 예시값)
_REQUIRED_FIELDS = [
    ("APPLICATION_TYPE", "신청유형",         "단체 또는 개인"),
    ("CONTRACT_DAY",     "계약일자",          "2025-09-01"),
    ("CAR_MODEL",        "신청차종",          "더뉴아이오닉5 AWD ..."),
    ("CAR_COUNT",        "신청대수",          "1"),
    ("DELIVERY_DATE",    "출고예정일",        "2025-09-12"),
    ("PHONE",            "전화번호",          "043-000-0000"),
    ("MOBILE",           "휴대폰",            "010-0000-0000"),
    ("ORG_NAME",         "기관명",            "주식회사 ..."),
    ("APP_GUBUN",        "신청구분",          "기타"),
    ("NAME",             "성명/대표자",       "홍길동"),
    ("B_NUM",            "법인번호",          "000000-0000000"),
    ("S_NUM",            "사업자번호",        "000-00-00000"),
    ("AGENCY_PHONE",     "대리점연락처",      "043-000-0000"),
    ("CONTACT_NAME",     "연락담당자 성명",   "홍길동"),
    ("CONTACT_MOBILE",   "연락담당자 휴대폰", "010-0000-0000"),
    ("MANUFACTURER_ID",  "제조수입사관리번호","G0000NE000000"),
    ("ADDRESS",          "주소",              "OO동 OO길 00"),
    ("FILE1",            "첨부파일 경로",     r"C:\파일경로\파일명.pdf"),
]


# ──────────────────────────────────────────
# 로그 헬퍼
# ──────────────────────────────────────────

def _err_box(log, step, cause, tips=None):
    log("┌" + "─" * 50)
    log(f"│ ❌  오류: {step}")
    log(f"│  원인: {cause}")
    if tips:
        log("│")
        log("│  ▶ 확인이 필요합니다:")
        for tip in tips:
            log(f"│     • {tip}")
    log("└" + "─" * 50)


def _warn_box(log, step, detail):
    log(f"  ┌ ⚠  경고: {step}")
    log(f"  └   {detail}")


def _short_error(e):
    return str(e).splitlines()[0] if str(e) else repr(e)


def _describe_page(driver):
    try:
        return f"title='{driver.title}', url={driver.current_url}"
    except Exception:
        return "현재 페이지 정보를 읽을 수 없습니다"


def _describe_element(driver, el):
    try:
        return driver.execute_script(
            """
            const el = arguments[0];
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return [
              `tag=${el.tagName.toLowerCase()}`,
              `id=${el.id || ''}`,
              `name=${el.name || ''}`,
              `type=${el.type || ''}`,
              `class=${el.className || ''}`,
              `display=${s.display}`,
              `visibility=${s.visibility}`,
              `disabled=${el.disabled}`,
              `readonly=${el.readOnly}`,
              `rect=${Math.round(r.width)}x${Math.round(r.height)}`
            ].join(', ');
            """,
            el,
        )
    except Exception:
        return "요소 정보를 읽을 수 없습니다"


def _log_debug_context(log, driver, step, el=None):
    log(f"  ↳ 위치: {_describe_page(driver)}")
    if el is not None:
        log(f"  ↳ 요소: {_describe_element(driver, el)}")
    _save_debug_snapshot(log, driver, step)


def _safe_filename(text):
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
    return cleaned.strip("_")[:60] or "debug"


def _save_debug_snapshot(log, driver, step):
    try:
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}_{_safe_filename(step)}"
        png_path = os.path.join(_DEBUG_DIR, f"{name}.png")
        html_path = os.path.join(_DEBUG_DIR, f"{name}.html")

        try:
            driver.save_screenshot(png_path)
            log(f"  ↳ 화면 캡처: {png_path}")
        except Exception as e:
            log(f"  ↳ 화면 캡처 실패: {_short_error(e)}")

        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            log(f"  ↳ HTML 저장: {html_path}")
        except Exception as e:
            log(f"  ↳ HTML 저장 실패: {_short_error(e)}")
    except Exception as e:
        log(f"  ↳ 디버그 스냅샷 저장 실패: {_short_error(e)}")


def _wait_for_page_idle(driver, log=None, label="페이지", timeout=12):
    deadline = time.time() + timeout
    saw_loading = False

    while time.time() < deadline:
        try:
            state = driver.execute_script(
                """
                const ready = document.readyState;
                const jqActive = window.jQuery ? window.jQuery.active : 0;
                const loadingSelectors = [
                  '.loading', '.loading-wrap', '.loader', '.spinner',
                  '.blockUI', '.ui-widget-overlay', '#loading', '#loadingBar',
                  '[aria-busy="true"]'
                ];
                const hasVisibleLoading = loadingSelectors.some((selector) =>
                  Array.from(document.querySelectorAll(selector)).some((el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                      && style.visibility !== 'hidden'
                      && style.opacity !== '0'
                      && rect.width > 0
                      && rect.height > 0;
                  })
                );
                return {ready, jqActive, hasVisibleLoading};
                """
            )
            is_idle = (
                state.get("ready") == "complete"
                and int(state.get("jqActive") or 0) == 0
                and not state.get("hasVisibleLoading")
            )
            if is_idle:
                if saw_loading and log:
                    log(f"  ✓ {label} 로딩 완료")
                return True
            saw_loading = True
        except (NoSuchWindowException, NoAlertPresentException):
            return True
        except Exception:
            return False
        time.sleep(0.2)

    if log:
        _warn_box(log, f"{label} 로딩 대기", f"{timeout}초 대기 후에도 로딩 상태일 수 있어 계속 진행합니다")
    return False


def _js_set_value(driver, el, value):
    _wait_for_page_idle(driver, None, timeout=5)
    driver.execute_script(
        """
        const el = arguments[0];
        const value = arguments[1];
        el.scrollIntoView({block: 'center', inline: 'nearest'});
        el.removeAttribute('readonly');
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        el,
        value,
    )


def _is_form_url(url):
    try:
        current = urlparse(url)
        target = urlparse(FORM_URL)
        return current.netloc == target.netloc and current.path == target.path
    except Exception:
        return False


def _click_element(driver, wait, locator, step, log):
    el = None
    last_err = None
    for attempt in range(2):
        try:
            _drain_alerts(driver, log, f"{step} 전", timeout=0.3)
            _wait_for_page_idle(driver, log, f"{step} 전")
            el = wait.until(EC.presence_of_element_located(locator))
            driver.execute_script(
                """
                const el = arguments[0];
                el.scrollIntoView({block:'center', inline:'nearest'});
                el.click();
                """,
                el,
            )
            return el
        except UnexpectedAlertPresentException as e:
            last_err = e
            if _handle_unexpected_alert(driver, log, step, e):
                continue
            break
        except Exception as e:
            last_err = e
            if el is not None:
                try:
                    driver.execute_script("arguments[0].click();", el)
                    _warn_box(log, step, "일반 클릭 실패 후 JavaScript 클릭으로 진행했습니다")
                    return el
                except UnexpectedAlertPresentException as alert_e:
                    last_err = alert_e
                    if _handle_unexpected_alert(driver, log, step, alert_e):
                        continue
                except Exception:
                    pass
            break

    _err_box(
        log,
        step,
        _short_error(last_err),
        ["아래 위치/요소 정보를 보고 사이트 화면이 예상 단계인지 확인하세요"],
    )
    _log_debug_context(log, driver, step, el)
    raise last_err


def _scroll_to_element(driver, wait, locator, step, log):
    try:
        _drain_alerts(driver, log, f"{step} 위치 이동 전", timeout=0.3)
        _wait_for_page_idle(driver, log, f"{step} 위치 이동 전")
        el = wait.until(EC.presence_of_element_located(locator))
        moved = driver.execute_script(
            """
            const el = arguments[0];
            const scrollParents = [];
            let node = el.parentElement;

            while (node && node !== document.body && node !== document.documentElement) {
              const style = window.getComputedStyle(node);
              const canScrollY = /(auto|scroll|overlay)/.test(style.overflowY)
                && node.scrollHeight > node.clientHeight;
              const canScrollX = /(auto|scroll|overlay)/.test(style.overflowX)
                && node.scrollWidth > node.clientWidth;
              if (canScrollY || canScrollX) scrollParents.push(node);
              node = node.parentElement;
            }

            for (const parent of scrollParents.reverse()) {
              const pr = parent.getBoundingClientRect();
              const er = el.getBoundingClientRect();
              parent.scrollTop += (er.top - pr.top) - (parent.clientHeight / 2) + (er.height / 2);
              parent.scrollLeft += (er.left - pr.left) - (parent.clientWidth / 2) + (er.width / 2);
            }

            el.scrollIntoView({block:'center', inline:'center'});

            const rect = el.getBoundingClientRect();
            const targetY = window.scrollY + rect.top - (window.innerHeight / 2) + (rect.height / 2);
            const targetX = window.scrollX + rect.left - (window.innerWidth / 2) + (rect.width / 2);
            window.scrollTo({
              top: Math.max(0, targetY),
              left: Math.max(0, targetX),
              behavior: 'instant'
            });

            el.style.outline = '4px solid #ef4444';
            el.style.outlineOffset = '3px';
            setTimeout(() => {
              el.style.outline = '';
              el.style.outlineOffset = '';
            }, 1500);

            const finalRect = el.getBoundingClientRect();
            return {
              top: Math.round(finalRect.top),
              left: Math.round(finalRect.left),
              width: Math.round(finalRect.width),
              height: Math.round(finalRect.height),
              parents: scrollParents.length
            };
            """,
            el,
        )
        time.sleep(0.05)
        log(
            f"  ✓ {step} 위치로 화면 이동 "
            f"(top={moved.get('top')}, left={moved.get('left')}, scrollParents={moved.get('parents')})"
        )
        return el
    except Exception as e:
        _err_box(
            log,
            f"{step} 위치 이동 실패",
            _short_error(e),
            ["대상 버튼이 현재 화면/창에 있는지 확인하세요"],
        )
        _log_debug_context(log, driver, f"{step} 위치 이동 실패")
        raise


def _open_attach_popup_from_form(driver, wait, attach_id, log):
    _drain_alerts(driver, log, f"[{attach_id}] 첨부 팝업 열기 전", timeout=0.5)
    locator = (
        By.XPATH,
        f"//button[contains(@onclick, \"popupAttachFile('{attach_id}')\")]",
    )
    button = _scroll_to_element(
        driver,
        wait,
        locator,
        f"[{attach_id}] 첨부파일 등록 버튼",
        log,
    )
    try:
        _wait_for_page_idle(driver, log, f"[{attach_id}] 첨부 팝업 함수 호출 전")
        driver.execute_script(
            """
            const button = arguments[0];
            const attachId = arguments[1];
            button.scrollIntoView({block:'center', inline:'nearest'});
            if (typeof window.popupAttachFile === 'function') {
                window.popupAttachFile(attachId);
            } else {
                button.click();
            }
            """,
            button,
            attach_id,
        )
    except Exception as e:
        _err_box(
            log,
            f"[{attach_id}] 첨부 팝업 열기 실패",
            _short_error(e),
            ["popupAttachFile 함수 호출 또는 버튼 클릭이 실패했습니다"],
        )
        _log_debug_context(log, driver, f"[{attach_id}] 첨부 팝업 열기 실패", button)
        raise


# ──────────────────────────────────────────
# Chrome 관련
# ──────────────────────────────────────────

def find_chrome():
    chrome_on_path = shutil.which("chrome") or shutil.which("chrome.exe")
    if chrome_on_path:
        return chrome_on_path

    for p in _CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _read_json_url(url, timeout=1):
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def _wait_for_debugger(port, timeout=8):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            tabs = _read_json_url(f"http://127.0.0.1:{port}/json", timeout=1)
            if tabs:
                return tabs
        except Exception as e:
            last_err = e
            time.sleep(0.25)
    raise TimeoutError(f"Chrome 디버깅 포트 :{port} 연결 실패: {last_err}")


def _recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("DevTools 응답이 중간에 끊겼습니다.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_ws_frame(sock):
    header = _recv_exact(sock, 2)
    if len(header) < 2:
        raise ConnectionError("DevTools 응답을 읽을 수 없습니다.")

    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]

    if header[1] & 0x80:
        mask = _recv_exact(sock, 4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(_recv_exact(sock, length)))
    else:
        payload = _recv_exact(sock, length)

    if opcode == 8:
        raise ConnectionError("DevTools WebSocket 연결이 닫혔습니다.")
    return payload.decode("utf-8", errors="replace")


def _send_ws_frame(sock, payload):
    payload_bytes = payload.encode("utf-8")
    mask = os.urandom(4)
    length = len(payload_bytes)

    if length < 126:
        header = struct.pack("!BB", 0x81, 0x80 | length)
    elif length < 65536:
        header = struct.pack("!BBH", 0x81, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", 0x81, 0x80 | 127, length)

    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload_bytes))
    sock.sendall(header + mask + masked)


def _cdp_call(websocket_url, method, params=None, timeout=3):
    parsed = urlparse(websocket_url)
    sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {parsed.path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        )
        if b" 101 " not in response or accept not in response:
            raise ConnectionError("DevTools WebSocket handshake 실패")

        message_id = random.randint(1000, 999999)
        _send_ws_frame(
            sock,
            json.dumps(
                {
                    "id": message_id,
                    "method": method,
                    "params": params or {},
                }
            ),
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            data = json.loads(_recv_ws_frame(sock))
            if data.get("id") == message_id:
                return data
        raise TimeoutError("DevTools JavaScript 실행 응답 시간 초과")
    finally:
        sock.close()


def _cdp_evaluate(websocket_url, expression, timeout=3):
    return _cdp_call(
        websocket_url,
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
        timeout=timeout,
    )


def _auto_fill_login_id(port, login_id, timeout=8):
    deadline = time.time() + timeout
    tab = None
    fallback_tab = None

    while time.time() < deadline:
        tabs = _wait_for_debugger(port, timeout=1)
        pages = [
            item
            for item in tabs
            if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
        ]
        fallback_tab = fallback_tab or (pages[0] if pages else None)
        tab = next((item for item in pages if "login.do" in item.get("url", "")), None)
        if tab:
            break
        time.sleep(0.25)

    tab = tab or fallback_tab
    if not tab:
        raise RuntimeError("DevTools에서 제어 가능한 Chrome 탭을 찾을 수 없습니다.")

    if "login.do" not in tab.get("url", ""):
        _cdp_call(
            tab["webSocketDebuggerUrl"],
            "Page.navigate",
            {"url": LOGIN_URL},
            timeout=3,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            tabs = _wait_for_debugger(port, timeout=1)
            pages = [
                item
                for item in tabs
                if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
            ]
            login_tab = next(
                (item for item in pages if "login.do" in item.get("url", "")),
                None,
            )
            if login_tab:
                tab = login_tab
                break
            time.sleep(0.25)

    script = f"""
    (() => {{
      const loginId = {json.dumps(login_id)};
      const candidates = [
        '#userId', '#userid', '#user_id', '#loginId', '#login_id',
        '#mberId', '#memberId', '#id', '[name="userId"]', '[name="userid"]',
        '[name="user_id"]', '[name="loginId"]', '[name="login_id"]',
        '[name="mberId"]', '[name="memberId"]', '[name="id"]'
      ];

      const visible = (el) => {{
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
          && style.visibility !== 'hidden'
          && rect.width > 0
          && rect.height > 0
          && !el.disabled
          && !el.readOnly;
      }};

      let input = candidates.map((selector) => document.querySelector(selector))
        .find((el) => el && visible(el));

      if (!input) {{
        input = Array.from(document.querySelectorAll('input'))
          .find((el) => {{
            const text = [
              el.id, el.name, el.placeholder, el.title,
              el.getAttribute('aria-label') || ''
            ].join(' ').toLowerCase();
            return visible(el)
              && ['text', 'email', 'tel', ''].includes((el.type || '').toLowerCase())
              && !/pass|pwd|비밀번호|password|captcha|보안/.test(text);
          }});
      }}

      if (!input) return {{ filled: false, target: '' }};
      input.focus();
      input.value = loginId;
      input.dispatchEvent(new Event('input', {{ bubbles: true }}));
      input.dispatchEvent(new Event('change', {{ bubbles: true }}));

      const password = Array.from(document.querySelectorAll('input[type="password"]'))
        .find(visible);
      if (password) password.focus();
      return {{ filled: true, target: input.id || input.name || input.outerHTML.slice(0, 80) }};
    }})()
    """
    deadline = time.time() + timeout
    value = {}
    while time.time() < deadline:
        result = _cdp_evaluate(tab["webSocketDebuggerUrl"], script, timeout=3)
        value = result.get("result", {}).get("result", {}).get("value", {})
        if value.get("filled"):
            return value.get("target", "")
        time.sleep(0.25)
    raise RuntimeError("로그인 페이지의 아이디 입력칸을 찾지 못했습니다.")


def open_chrome(port, login_id=DEFAULT_LOGIN_ID):
    chrome = find_chrome()
    if not chrome:
        raise FileNotFoundError("Chrome 실행 파일을 찾을 수 없습니다.")

    profile_dir = os.path.join(_CHROME_PROFILE_BASE, str(port))
    os.makedirs(profile_dir, exist_ok=True)

    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            LOGIN_URL,
        ],
        creationflags=subprocess.DETACHED_PROCESS,
    )
    try:
        target = _auto_fill_login_id(port, login_id)
        return True, f"아이디 자동 입력 완료: {login_id} ({target})"
    except Exception as e:
        return False, f"아이디 자동 입력 건너뜀: {_short_error(e)}"


# ──────────────────────────────────────────
# env 유효성 검사
# ──────────────────────────────────────────

def _validate_cfg(cfg, log):
    missing = []
    for key, label, example in _REQUIRED_FIELDS:
        if not cfg.get(key, "").strip():
            missing.append((key, label, example))

    if missing:
        log("┌" + "─" * 50)
        log("│ ❌  env 파일에 필수 항목이 없습니다")
        log("│")
        log("│  누락된 항목 목록:")
        for key, label, example in missing:
            log(f"│     • {key}  ({label})")
            log(f"│       예시: {key}={example}")
        log("│")
        log("│  ▶ env 파일을 열어서 위 항목을 채워주세요")
        log("└" + "─" * 50)
        raise ValueError(f"env 누락 항목: {[k for k, _, _ in missing]}")

    # 첨부파일 존재 여부
    file1 = cfg.get("FILE1", "")
    if file1 and not os.path.exists(file1):
        _err_box(
            log,
            "첨부파일 경로 오류",
            f"파일이 존재하지 않습니다: {file1}",
            [
                "env 파일의 FILE1 경로가 정확한지 확인하세요",
                "파일명에 한글이 포함된 경우 경로를 큰따옴표로 묶으세요",
                f'예: FILE1="{file1}"',
            ],
        )
        raise FileNotFoundError(f"첨부파일 없음: {file1}")


# ──────────────────────────────────────────
# Alert 처리
# ──────────────────────────────────────────

def _accept_alert(driver, timeout=3, retries=2):
    last_txt = ""
    for _ in range(retries):
        try:
            WebDriverWait(driver, timeout).until(EC.alert_is_present())
            a = driver.switch_to.alert
            txt = a.text
            time.sleep(0.1)
            a.accept()
            time.sleep(0.1)
            return True, txt
        except (TimeoutException, NoAlertPresentException):
            continue
        except NoSuchWindowException:
            return True, ""
        except Exception as e:
            last_txt = str(e)
            break
    return False, last_txt


def _drain_alerts(driver, log, label, timeout=1, max_alerts=5):
    handled_any = False
    texts = []
    for _ in range(max_alerts):
        try:
            WebDriverWait(driver, timeout).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            txt = alert.text
            alert.accept()
            handled_any = True
            texts.append(txt)
            time.sleep(0.2)
        except (TimeoutException, NoAlertPresentException):
            break
        except NoSuchWindowException:
            break
        except Exception:
            break
    if handled_any:
        log(f"  ✓ {label} Alert 처리: {' / '.join(texts)}")
    return handled_any, texts


def _handle_unexpected_alert(driver, log, label, exc=None):
    text = ""
    try:
        alert = driver.switch_to.alert
        text = alert.text
        alert.accept()
        log(f"  ✓ {label} unexpected Alert 처리: {text}")
        time.sleep(0.3)
        return True
    except Exception:
        if exc:
            log(f"  ⚠ {label} unexpected Alert 처리 실패: {_short_error(exc)}")
        return False


def _has_security_code_elements(driver):
    try:
        if driver.find_elements(By.ID, "randeomChk"):
            return True
        if driver.find_elements(By.XPATH, "//tbody/tr[2]/td[2]//span[@class='guide']"):
            return True
    except Exception:
        return False
    return False


def _switch_to_security_code_window(driver, wait, parent_handle, before_handles, log, quiet=False):
    def find_security_window(d):
        handles = list(d.window_handles)
        preferred = [h for h in handles if h not in before_handles]
        candidates = preferred + [
            h for h in handles if h in before_handles and h != parent_handle
        ]

        for handle in candidates:
            try:
                d.switch_to.window(handle)
                if d.execute_script("return document.readyState") != "complete":
                    continue
                if _has_security_code_elements(d):
                    return handle
            except Exception:
                continue
        return False

    try:
        handle = wait.until(find_security_window)
        driver.switch_to.window(handle)
        _wait_for_page_idle(driver, log, "보안코드 팝업")
        log(f"  ✓ 보안코드 창 열림 ({len(driver.window_handles)}개 창 중 감지)")
        return handle
    except TimeoutException:
        if quiet:
            raise
        try:
            if parent_handle in driver.window_handles:
                driver.switch_to.window(parent_handle)
        except Exception:
            pass
        _err_box(
            log,
            "보안코드 창을 찾을 수 없음",
            "창은 열렸을 수 있지만 보안코드 입력칸(randeomChk) 또는 코드 텍스트(span.guide)를 찾지 못했습니다",
            [
                f"현재 열린 창 수: {len(driver.window_handles)}",
                "보안코드 팝업이 열려 있다면 팝업 화면 구조가 변경됐을 수 있습니다",
                "로그에 저장된 화면 캡처/HTML 파일을 확인하세요",
            ],
        )
        _log_debug_context(log, driver, "보안코드 창 감지 실패")
        raise


def _solve_security_code(driver, wait, parent_handle, before_handles, log):
    _handle_unexpected_alert(driver, log, "보안코드 진입 전")
    _drain_alerts(driver, log, "보안코드 창 대기 전", timeout=0.2, max_alerts=5)
    log("  → 보안코드 창 대기 중...")
    security_handle = None
    deadline = time.time() + 6
    last_err = None
    while time.time() < deadline and not security_handle:
        try:
            _drain_alerts(driver, log, "보안코드 대기 중", timeout=0.2, max_alerts=3)
            short_wait = WebDriverWait(driver, 1)
            security_handle = _switch_to_security_code_window(
                driver, short_wait, parent_handle, before_handles, log, quiet=True
            )
        except UnexpectedAlertPresentException as e:
            last_err = e
            _handle_unexpected_alert(driver, log, "보안코드 대기", e)
        except TimeoutException as e:
            last_err = e
            time.sleep(0.2)
        except Exception as e:
            last_err = e
            time.sleep(0.2)
    if not security_handle:
        raise last_err or TimeoutException("보안코드 창 대기 시간 초과")

    try:
        guide = wait.until(
            EC.presence_of_element_located((
                By.XPATH, "//tbody/tr[2]/td[2]//span[@class='guide']",
            ))
        )
        code_text = guide.text.strip()
        if not code_text:
            raise RuntimeError("보안코드 텍스트가 비어 있습니다")
    except Exception as e:
        _err_box(
            log,
            "보안코드 텍스트를 찾을 수 없음",
            _short_error(e),
            [
                "사이트 업데이트로 보안코드 창 구조가 변경됐을 수 있습니다",
                "Chrome 창에서 보안코드 팝업을 직접 확인하세요",
            ],
        )
        _log_debug_context(log, driver, "보안코드 텍스트 추출 실패")
        raise

    reversed_code = code_text[::-1]
    log(f"  → 보안코드 원문: {code_text}  →  뒤집은값: {reversed_code}")

    _safe_input(driver, wait, "randeomChk", reversed_code, "보안코드", log)
    log("  ✓ 보안코드 입력 완료")

    _click_element(
        driver,
        wait,
        (By.XPATH, "//button[contains(@onclick, 'goCompare')]"),
        "보안코드 확인 버튼 클릭 실패",
        log,
    )
    log("  ✓ 확인 버튼 클릭")

    handled, txt = _accept_alert(driver, timeout=2, retries=2)
    if handled and txt:
        log(f"  ✓ 보안코드 확인 Alert 처리: '{txt}'")

    try:
        WebDriverWait(driver, 3).until(
            lambda d: security_handle not in d.window_handles
            or not _has_security_code_elements(d)
        )
    except TimeoutException:
        _warn_box(log, "보안코드 창 닫힘 확인", "3초 내 자동 닫힘 확인이 안 되어 부모창으로 바로 복귀합니다")

    _switch_to_form_window(driver, log, preferred_handle=parent_handle)
    _wait_for_page_idle(driver, log, "보안코드 확인 후 부모 화면", timeout=5)
    try:
        WebDriverWait(driver, 6).until(
            lambda d: d.find_elements(
                By.XPATH, "//*[@onclick and contains(@onclick, 'popupAttachFile')]"
            )
        )
    except TimeoutException:
        _err_box(
            log,
            "보안코드 확인 후 첨부 영역을 찾을 수 없음",
            "보안코드 확인은 눌렀지만 부모 신청서 화면에 첨부 버튼이 나타나지 않았습니다",
            ["보안코드 팝업에 오류 메시지가 남아 있는지 확인하세요"],
        )
        _log_debug_context(log, driver, "보안코드 이후 첨부 영역 없음")
        raise


def _focus_current_window(driver):
    try:
        driver.execute_script("window.focus();")
    except Exception:
        pass


def _switch_to_form_window(driver, log, preferred_handle=None):
    handles = list(driver.window_handles)
    ordered = []
    if preferred_handle and preferred_handle in handles:
        ordered.append(preferred_handle)
    ordered.extend(h for h in handles if h not in ordered)

    for handle in ordered:
        try:
            driver.switch_to.window(handle)
            if _is_form_url(driver.current_url) or driver.find_elements(
                By.XPATH, "//*[@onclick and contains(@onclick, 'popupAttachFile')]"
            ):
                _focus_current_window(driver)
                return handle
        except UnexpectedAlertPresentException as e:
            _handle_unexpected_alert(driver, log, "신청서 창 복귀", e)
            continue
        except Exception:
            continue

    if driver.window_handles:
        driver.switch_to.window(driver.window_handles[0])
        _focus_current_window(driver)
    _warn_box(log, "신청서 창 복귀", "신청서 URL/첨부 버튼이 있는 창을 찾지 못해 첫 번째 창으로 전환했습니다")
    return driver.current_window_handle


# ──────────────────────────────────────────
# 신청서 작성 (1단계)
# ──────────────────────────────────────────

def _safe_select(driver, el_id, value, field_label, env_key, log):
    """드롭다운 선택 — 항목 없으면 가독성 있는 오류 출력."""
    try:
        Select(driver.find_element(By.ID, el_id)).select_by_visible_text(value)
    except NoSuchElementException:
        _err_box(
            log,
            f"[{field_label}] 드롭다운 선택 실패",
            f"'{value}' 항목을 드롭다운에서 찾을 수 없습니다",
            [
                f"env 파일의 {env_key} 값을 확인하세요  →  현재값: \"{value}\"",
                "사이트 드롭다운에 표시된 텍스트와 정확히 일치해야 합니다 (공백·괄호 포함)",
                "ev.or.kr 에 로그인된 상태인지 확인하세요",
            ],
        )
        raise
    except Exception as e:
        el = None
        try:
            el = driver.find_element(By.ID, el_id)
        except Exception:
            pass
        _err_box(
            log,
            f"[{field_label}] 드롭다운 조작 실패",
            _short_error(e),
            [
                f"env 파일의 {env_key} 값: \"{value}\"",
                "아래 요소 상태가 hidden/disabled인지 확인하세요",
            ],
        )
        _log_debug_context(log, driver, f"[{field_label}] 드롭다운 조작 실패", el)
        raise


def _safe_input(driver, wait, el_id, value, field_label, log):
    """입력 필드 — 요소를 찾지 못하면 가독성 있는 오류 출력."""
    el = None
    try:
        el = wait.until(EC.presence_of_element_located((By.ID, el_id)))
        try:
            _js_set_value(driver, el, value)
        except Exception as e:
            _warn_box(
                log,
                f"[{field_label}] JavaScript 입력 실패",
                f"{_short_error(e)} → WebDriver 입력으로 재시도합니다",
            )
            _log_debug_context(log, driver, f"[{field_label}] JavaScript 입력 실패", el)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            wait.until(EC.element_to_be_clickable((By.ID, el_id)))
            el.clear()
            el.send_keys(value)
    except TimeoutException:
        _err_box(
            log,
            f"[{field_label}] 입력 필드를 찾을 수 없음",
            f"id='{el_id}' 요소가 10초 내에 나타나지 않았습니다",
            [
                "페이지가 올바르게 로드됐는지 확인하세요",
                "이전 단계에서 신청유형 선택이 제대로 됐는지 확인하세요",
                "로그인 세션이 유지 중인지 확인하세요",
            ],
        )
        raise
    except Exception as e:
        _err_box(
            log,
            f"[{field_label}] 입력 실패",
            _short_error(e),
            ["아래 위치/요소 정보를 보고 사이트 화면이 예상 단계인지 확인하세요"],
        )
        _log_debug_context(log, driver, f"[{field_label}] 입력 실패", el)
        raise


def _run_form(driver, wait, cfg, log):
    log("━━━ [1단계] 신청서 작성 시작 ━━━")

    current_url = driver.current_url
    if not _is_form_url(current_url):
        log("  → 현재 페이지가 신청서 작성 페이지가 아닙니다.")
        log(f"  → 신청서 페이지로 이동합니다: {FORM_URL}")
        try:
            driver.get(FORM_URL)
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except WebDriverException as e:
            _err_box(
                log,
                "신청서 페이지 이동 실패",
                _short_error(e),
                [
                    "Chrome이 포트에 올바르게 연결되어 있는지 확인하세요",
                    "로그인 세션이 유지 중인지 확인하세요",
                    "이동 후 신청서 페이지가 보이면 [실행]을 다시 클릭하세요",
                ],
            )
            raise
        log("  ✓ 신청서 페이지로 이동 완료")
        log("  ⏹ 여기서 종료합니다. 신청서 페이지가 보이면 [실행]을 다시 클릭하세요.")
        return False

    log("  ✓ 신청서 페이지 확인 완료")

    # 신청유형
    val = cfg["APPLICATION_TYPE"]
    log(f"  → [신청유형] '{val}' 선택 중...")
    _safe_select(driver, "req_kind", val, "신청유형", "APPLICATION_TYPE", log)
    _wait_for_page_idle(driver, log, "신청유형 선택 후", timeout=5)
    log(f"  ✓ [신청유형] 완료")

    # 계약일자
    val = cfg["CONTRACT_DAY"]
    log(f"  → [계약일자] {val} 입력 중...")
    driver.execute_script(f"document.getElementById('contract_day').value = '{val}';")
    log(f"  ✓ [계약일자] 완료")

    # 차종
    val = cfg["CAR_MODEL"]
    log(f"  → [차종] '{val}' 선택 중...")
    _safe_select(driver, "model_cd", val, "차종", "CAR_MODEL", log)
    log(f"  ✓ [차종] 완료")

    # 신청대수
    val = cfg.get("CAR_COUNT", "1")
    log(f"  → [신청대수] {val}대 입력 중...")
    _safe_input(driver, wait, "req_cnt", val, "신청대수", log)
    log(f"  ✓ [신청대수] 완료")

    # 출고예정일
    val = cfg["DELIVERY_DATE"]
    log(f"  → [출고예정일] {val} 입력 중...")
    driver.execute_script(f"document.getElementById('delivery_sch_day').value = '{val}';")
    log(f"  ✓ [출고예정일] 완료")

    # 연락처
    log(f"  → [전화번호] {cfg['PHONE']} 입력 중...")
    _safe_input(driver, wait, "phone", cfg["PHONE"], "전화번호", log)
    log(f"  ✓ [전화번호] 완료")

    log(f"  → [휴대폰] {cfg['MOBILE']} 입력 중...")
    _safe_input(driver, wait, "mobile", cfg["MOBILE"], "휴대폰", log)
    log(f"  ✓ [휴대폰] 완료")

    email = cfg.get("EMAIL", "")
    log(f"  → [이메일] {email} 입력 중...")
    _safe_input(driver, wait, "email", email, "이메일", log)
    log(f"  ✓ [이메일] 완료")

    # 기관 정보
    log(f"  → [기관명] {cfg['ORG_NAME']} 입력 중...")
    _safe_input(driver, wait, "req_nm", cfg["ORG_NAME"], "기관명", log)
    log(f"  ✓ [기관명] 완료")

    val = cfg["APP_GUBUN"]
    log(f"  → [신청구분] '{val}' 선택 중...")
    _safe_select(driver, "grp_reqst_se", val, "신청구분", "APP_GUBUN", log)
    log(f"  ✓ [신청구분] 완료")

    log(f"  → [대표자] {cfg['NAME']} 입력 중...")
    _safe_input(driver, wait, "ceo", cfg["NAME"], "대표자", log)
    log(f"  ✓ [대표자] 완료")

    log(f"  → [법인번호] {cfg['B_NUM']} 입력 중...")
    _safe_input(driver, wait, "birth2", cfg["B_NUM"], "법인번호", log)
    log(f"  ✓ [법인번호] 완료")

    log(f"  → [사업자번호] {cfg['S_NUM']} 입력 중...")
    _safe_input(driver, wait, "busi_no", cfg["S_NUM"], "사업자번호", log)
    log(f"  ✓ [사업자번호] 완료")

    log(f"  → [개인사업장명] {cfg['ORG_NAME']} 입력 중...")
    _safe_input(driver, wait, "pri_busi_nm", cfg["ORG_NAME"], "개인사업장명", log)
    log(f"  ✓ [개인사업장명] 완료")

    log(f"  → [대리점연락처] {cfg['AGENCY_PHONE']} 입력 중...")
    _safe_input(driver, wait, "seller_phone", cfg["AGENCY_PHONE"], "대리점연락처", log)
    log(f"  ✓ [대리점연락처] 완료")

    log(f"  → [담당자명] {cfg['CONTACT_NAME']} 입력 중...")
    _safe_input(driver, wait, "contact_nm", cfg["CONTACT_NAME"], "담당자명", log)
    log(f"  ✓ [담당자명] 완료")

    log(f"  → [담당자연락처] {cfg['CONTACT_MOBILE']} 입력 중...")
    _safe_input(driver, wait, "contact_mobile", cfg["CONTACT_MOBILE"], "담당자연락처", log)
    log(f"  ✓ [담당자연락처] 완료")

    log(f"  → [제조수입사관리번호] {cfg['MANUFACTURER_ID']} 입력 중...")
    _safe_input(driver, wait, "seller_mgrid", cfg["MANUFACTURER_ID"], "제조수입사관리번호", log)
    log(f"  ✓ [제조수입사관리번호] 완료")

    # 주소 팝업
    log(f"  → [주소] 팝업 열기 (검색어: {cfg['ADDRESS']})")
    parent2 = driver.current_window_handle
    before2 = set(driver.window_handles)
    try:
        _click_element(
            driver,
            wait,
            (
                By.XPATH,
                "//*[@onclick and contains(@onclick, '/ev_ps/addrlink/addrPopup')]",
            ),
            "주소 팝업 버튼 클릭 실패",
            log,
        )
    except TimeoutException:
        _err_box(
            log,
            "주소 팝업 버튼을 찾을 수 없음",
            "주소 검색 버튼이 페이지에 나타나지 않았습니다",
            [
                "신청서 페이지가 올바르게 로드됐는지 확인하세요",
                "로그인 세션이 유지 중인지 확인하세요",
            ],
        )
        raise

    def _find_addr_popup(d):
        for h in d.window_handles:
            if h in before2:
                continue
            try:
                d.switch_to.window(h)
                if d.find_elements(By.ID, "keyword"):
                    return h
            except Exception:
                continue
        return False

    try:
        child2 = wait.until(_find_addr_popup)
    except TimeoutException:
        _err_box(
            log, "주소 팝업이 열리지 않음",
            "팝업 창이 10초 내에 열리지 않았습니다",
            ["브라우저 팝업 차단 설정을 해제하세요"],
        )
        raise
    driver.switch_to.window(child2)
    log("  ✓ 주소 팝업 열림")

    _safe_input(driver, wait, "keyword", cfg["ADDRESS"], "주소 검색어", log)
    log(f"  → 검색어 '{cfg['ADDRESS']}' 입력 후 검색 클릭")

    _click_element(
        driver,
        wait,
        (By.XPATH, "//button[contains(@onclick, 'searchUrlJuso')]"),
        "주소 검색 버튼 클릭 실패",
        log,
    )

    try:
        wait.until(
            lambda d: len(
                d.find_elements(By.XPATH, "//a[contains(@href, \"setMaping('1')\")]")
            ) > 0
        )
    except TimeoutException:
        _err_box(
            log,
            "주소 검색 결과 없음",
            f"'{cfg['ADDRESS']}' 로 검색했으나 결과가 없습니다",
            [
                "env 파일의 ADDRESS 값을 더 짧게 입력해 보세요",
                "예: '황탄리길 85-45' → '황탄리길'",
                "도로명·지번 형식이 맞는지 확인하세요",
            ],
        )
        raise

    log("  ✓ 주소 검색 결과 확인, 첫 번째 항목 선택 중...")
    for _ in range(3):
        try:
            a = driver.find_element(
                By.XPATH, "//a[contains(@href, \"setMaping('1')\")]"
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", a)
            driver.execute_script("arguments[0].click();", a)
            break
        except StaleElementReferenceException:
            time.sleep(0.3)

    time.sleep(0.1)
    addr2 = cfg.get("ADDRESS2", "")
    log(f"  → 상세주소 '{addr2}' 입력 중...")
    _safe_input(driver, wait, "rtAddrDetail", addr2, "상세주소", log)

    _click_element(
        driver,
        wait,
        (By.XPATH, "//button[contains(@onclick, 'setParent')]"),
        "주소 확인 버튼 클릭 실패",
        log,
    )
    log("  ✓ 주소 확인, 팝업 닫힘")

    driver.switch_to.window(parent2)

    # 저장
    log("  → 저장(goSave) 버튼 클릭 중...")
    parent3 = driver.current_window_handle
    before3 = set(driver.window_handles)
    try:
        _click_element(
            driver,
            wait,
            (By.XPATH, "//button[contains(@onclick, 'goSave')]"),
            "저장 버튼(goSave) 클릭 실패",
            log,
        )
    except TimeoutException:
        _err_box(
            log,
            "저장 버튼(goSave)을 찾을 수 없음",
            "저장 버튼이 페이지에 나타나지 않았습니다",
            [
                "주소 팝업이 정상적으로 닫혔는지 확인하세요",
                "입력 도중 페이지가 새로고침됐을 수 있습니다",
            ],
        )
        raise

    handled, texts = _drain_alerts(driver, log, "임시저장", timeout=1.0, max_alerts=2)
    if not handled:
        log("  ✓ (goSave alert 없음)")

    _solve_security_code(driver, wait, parent3, before3, log)
    log("✅ [1단계] 신청서 작성 완료")
    return True


# ──────────────────────────────────────────
# 파일 첨부 (2단계)
# ──────────────────────────────────────────

_REQUIRED_ATTACH_IDS = ["A", "A2", "A3", "A7"]


def _attach_slot_state(driver, attach_id):
    return driver.execute_script(
        """
        const attachId = arguments[0];
        const buttons = Array.from(document.querySelectorAll('[onclick*="popupAttachFile"]'));
        const button = buttons.find((el) => (el.getAttribute('onclick') || '').includes(`popupAttachFile('${attachId}')`));
        if (!button) return {exists: false, text: '', missing: true};

        const cell = button.closest('td') || button.parentElement;
        const text = (cell ? cell.innerText : button.outerText || '').replace(/\\s+/g, ' ').trim();
        return {
          exists: true,
          text,
          missing: text.includes('첨부파일 없음'),
          hasRegisterButton: text.includes('첨부파일 등록')
        };
        """,
        attach_id,
    )


def _verify_attach_saved(driver, wait, attach_id, file_path, log, timeout=3):
    file_name = os.path.basename(file_path)
    deadline = time.time() + timeout
    last_state = {}

    while time.time() < deadline:
        _switch_to_form_window(driver, log)
        last_state = _attach_slot_state(driver, attach_id)
        text = last_state.get("text", "")
        if last_state.get("exists") and not last_state.get("missing"):
            if file_name and file_name in text:
                log(f"  ✓ [{attach_id}] 부모 화면 첨부 확인: {file_name}")
            else:
                log(f"  ✓ [{attach_id}] 부모 화면 첨부 상태 변경 확인")
                if text:
                    log(f"  ↳ [{attach_id}] 표시 텍스트: {text[:160]}")
            return True
        time.sleep(0.2)

    _err_box(
        log,
        f"[{attach_id}] 첨부 반영 확인 실패",
        "팝업 저장 후에도 부모 화면에 '* 첨부파일 없음' 상태가 남아 있습니다",
        [
            "첨부 팝업의 Alert 메시지에 실패/용량/확장자 제한 안내가 있었는지 확인하세요",
            "파일이 실제로 업로드 가능한 형식인지 확인하세요",
            f"부모 화면 표시 텍스트: {last_state.get('text', '')[:160]}",
        ],
    )
    _log_debug_context(log, driver, f"[{attach_id}] 첨부 반영 확인 실패")
    return False


def _close_extra_attach_windows(driver, parent_handle):
    for handle in list(driver.window_handles):
        if handle == parent_handle:
            continue
        try:
            driver.switch_to.window(handle)
            if "popupAttach" in driver.current_url or "attach" in driver.title.lower():
                driver.close()
        except Exception:
            pass
    if parent_handle in driver.window_handles:
        driver.switch_to.window(parent_handle)


def _switch_to_attach_popup(driver, wait, parent_handle, before_handles, attach_id, log):
    def find_popup(d):
        handles = list(d.window_handles)
        preferred = [h for h in handles if h not in before_handles]
        candidates = preferred + [h for h in handles if h != parent_handle and h in before_handles]

        for handle in candidates:
            try:
                d.switch_to.window(handle)
                if d.execute_script("return document.readyState") != "complete":
                    continue
                if d.find_elements(By.ID, "filename"):
                    return handle
            except Exception:
                continue
        return False

    try:
        handle = wait.until(find_popup)
        driver.switch_to.window(handle)
        _wait_for_page_idle(driver, log, f"[{attach_id}] 첨부 팝업")
        log(f"  ✓ [{attach_id}] 첨부 팝업 감지")
        return handle
    except TimeoutException:
        _err_box(
            log,
            f"[{attach_id}] 첨부 팝업 감지 실패",
            "팝업은 열렸을 수 있지만 input#filename을 찾지 못했습니다",
            [
                "브라우저 팝업 차단 여부를 확인하세요",
                "이미 열린 첨부 팝업이 있으면 닫고 다시 시도하세요",
            ],
        )
        _log_debug_context(log, driver, f"[{attach_id}] 첨부 팝업 감지 실패")
        raise


def _set_file_input(driver, wait, file_path, attach_id, log):
    _wait_for_page_idle(driver, log, f"[{attach_id}] 파일 input 처리 전")
    file_el = wait.until(EC.presence_of_element_located((By.ID, "filename")))
    if (file_el.get_attribute("type") or "").lower() != "file":
        raise RuntimeError("#filename 요소가 file input이 아닙니다")

    log(f"  → [{attach_id}] 파일 경로 입력: {file_path}")
    driver.execute_script(
        """
        const el = arguments[0];
        el.removeAttribute('disabled');
        el.removeAttribute('readonly');
        el.style.display = 'block';
        el.style.visibility = 'visible';
        el.style.opacity = '1';
        el.style.position = 'fixed';
        el.style.left = '20px';
        el.style.top = '20px';
        el.style.width = '520px';
        el.style.height = '34px';
        el.style.zIndex = '2147483647';
        el.scrollIntoView({block:'center'});
        """,
        file_el,
    )
    wait.until(lambda d: file_el.is_enabled())
    file_el.send_keys(file_path)

    entered = file_el.get_attribute("value") or ""
    if not entered:
        raise RuntimeError("파일 input에 경로가 반영되지 않았습니다")
    log(f"  ✓ [{attach_id}] 파일 경로 입력 완료")


def _click_attach_save(driver, wait, attach_id, log):
    log(f"  → [{attach_id}] 첨부파일 등록 버튼 클릭 중...")
    _wait_for_page_idle(driver, log, f"[{attach_id}] 첨부파일 등록 전")
    save_btn = wait.until(
        EC.presence_of_element_located((
            By.XPATH,
            "//button[contains(@class,'btn-blue') and contains(@onclick,'goSave')]",
        ))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
    try:
        wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//button[contains(@class,'btn-blue') and contains(@onclick,'goSave')]",
        )))
        driver.execute_script("arguments[0].click();", save_btn)
    except ElementNotInteractableException:
        driver.execute_script("arguments[0].click();", save_btn)
        _warn_box(log, f"[{attach_id}] 등록 버튼 일반 클릭 실패", "JavaScript 클릭으로 진행했습니다")


def _handle_attach(driver, wait, attach_id, file_path, log):
    log(f"  → [{attach_id}] 첨부 팝업 열기 중...")
    parent_handle = _switch_to_form_window(driver, log)
    _close_extra_attach_windows(driver, parent_handle)
    before = set(driver.window_handles)

    _open_attach_popup_from_form(driver, wait, attach_id, log)

    child = _switch_to_attach_popup(driver, wait, parent_handle, before, attach_id, log)
    _set_file_input(driver, wait, file_path, attach_id, log)

    try:
        _click_attach_save(driver, wait, attach_id, log)
    except (TimeoutException, NoSuchElementException, ElementNotInteractableException) as e:
        _err_box(
            log,
            f"[{attach_id}] 첨부 저장 버튼을 찾을 수 없음",
            _short_error(e),
            ["첨부파일 팝업 창의 구조가 변경됐을 수 있습니다"],
        )
        _log_debug_context(log, driver, f"[{attach_id}] 첨부 저장 실패")
        raise

    handled, txt = _accept_alert(driver, timeout=1, retries=2)
    if handled:
        log(f"  ✓ [{attach_id}] Alert 처리: '{txt}'")

    child_handle = driver.current_window_handle
    try:
        WebDriverWait(driver, 1).until(lambda d: child_handle not in d.window_handles)
        log(f"  ✓ [{attach_id}] 팝업 닫힘")
    except TimeoutException:
        _warn_box(log, f"[{attach_id}] 팝업 자동 닫힘 안됨", "팝업을 닫고 부모 화면 반영을 확인합니다")
        try:
            driver.close()
        except Exception:
            pass

    try:
        if parent_handle in driver.window_handles:
            driver.switch_to.window(parent_handle)
        else:
            _switch_to_form_window(driver, log)
    except NoSuchWindowException:
        _switch_to_form_window(driver, log)
    _wait_for_page_idle(driver, log, f"[{attach_id}] 첨부 저장 후 부모 화면", timeout=2)

    handled2, txt2 = _accept_alert(driver, timeout=0.5, retries=2)
    if handled2:
        log(f"  ✓ [{attach_id}] 부모창 Alert 처리: '{txt2}'")

    if not _verify_attach_saved(driver, wait, attach_id, file_path, log, timeout=3):
        raise RuntimeError(f"[{attach_id}] 첨부 반영 확인 실패")

    log(f"  ✅ [{attach_id}] 첨부 완료")
    return True


def _handle_attach_with_retries(driver, wait, attach_id, file_path, log, max_retries=3):
    last_err = None
    for attempt in range(1, max_retries + 1):
        log(f"  → [{attach_id}] 업로드 시도 {attempt}/{max_retries}")
        parent_handle = _switch_to_form_window(driver, log)
        try:
            if _handle_attach(driver, wait, attach_id, file_path, log):
                return True
        except Exception as e:
            last_err = e
            _warn_box(log, f"[{attach_id}] 업로드 시도 {attempt} 실패", _short_error(e))
            try:
                _close_extra_attach_windows(driver, parent_handle)
                _switch_to_form_window(driver, log)
            except Exception:
                pass
            time.sleep(0.3)

    _err_box(
        log,
        f"[{attach_id}] 첨부파일 업로드 실패",
        f"{max_retries}회 재시도 후에도 실패했습니다: {_short_error(last_err)}",
        [
            "파일 경로와 PDF 형식을 확인하세요",
            "첨부 팝업이 열려 있으면 닫고 다시 실행하세요",
            "마지막 실패 시점의 화면 캡처/HTML 로그를 확인하세요",
        ],
    )
    _log_debug_context(log, driver, f"[{attach_id}] 3회 재시도 실패")
    raise RuntimeError(f"[{attach_id}] 첨부파일 업로드 실패")


def _run_attach(driver, wait, cfg, log):
    log("━━━ [2단계] 파일 첨부 및 지원신청 시작 ━━━")
    file_path = cfg.get("FILE1", "")
    log(f"  첨부 파일: {file_path}")

    _switch_to_form_window(driver, log)
    _wait_for_page_idle(driver, log, "첨부 반영 확인 전 부모 화면", timeout=3)
    log(f"  고정 첨부 순서: {', '.join(_REQUIRED_ATTACH_IDS)}")

    success_count = 0
    for attach_id in _REQUIRED_ATTACH_IDS:
        log(f"  → [{attach_id}] 처리 시작")
        _handle_attach_with_retries(driver, wait, attach_id, file_path, log, max_retries=3)
        success_count += 1

    log(f"  ✓ 첨부 완료 슬롯 수: {success_count}/{len(_REQUIRED_ATTACH_IDS)}")

    log("  → 지원신청 버튼 클릭 중...")
    _drain_alerts(driver, log, "지원신청 전", timeout=0.5)
    apply_locator = (
        By.XPATH, "//button[contains(@onclick, \"goApply('101'\")]"
    )
    try:
        _scroll_to_element(
            driver,
            wait,
            apply_locator,
            "지원신청 버튼",
            log,
        )
        _click_element(
            driver,
            wait,
            apply_locator,
            "지원신청 버튼 클릭 실패",
            log,
        )
        handled, txt = _accept_alert(driver, timeout=5, retries=2)
        if handled:
            log(f"  ✓ 지원신청 Alert 처리: '{txt}'")
        log("  ✅ 지원신청 완료")
    except TimeoutException:
        _err_box(
            log,
            "지원신청 버튼을 찾을 수 없음",
            "goApply('101') 버튼이 페이지에 나타나지 않았습니다",
            [
                "필수 첨부파일(A 슬롯)이 업로드됐는지 확인하세요",
                "Chrome 창에서 신청 가능한 상태인지 직접 확인하세요",
            ],
        )
        raise
    except Exception as e:
        _err_box(
            log,
            "지원신청 버튼 조작 실패",
            _short_error(e),
            ["첨부가 끝난 뒤 페이지가 지원신청 가능한 상태인지 확인하세요"],
        )
        _log_debug_context(log, driver, "지원신청 버튼 조작 실패")
        raise

    log("✅ [2단계] 완료")


# ──────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────

def run_all(env_path, port, log_cb, file1_path=None, driver_holder=None):
    log_cb(f"env 파일 로드: {os.path.basename(env_path)}")
    cfg = dotenv_values(env_path)
    if file1_path:
        cfg["FILE1"] = file1_path
        log_cb(f"FILE1 GUI 선택: {file1_path}")
    log_cb(f"  신청인: {cfg.get('NAME', '?')} / 기관: {cfg.get('ORG_NAME', '?')}")
    log_cb(f"  차종:   {cfg.get('CAR_MODEL', '?')}")
    log_cb(f"  포트:   :{port}")
    log_cb("")

    # env 유효성 검사 (실행 전 미리 확인)
    _validate_cfg(cfg, log_cb)

    opts = Options()
    opts.add_argument("--disable-popup-blocking")
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    opts.set_capability("unhandledPromptBehavior", "accept")

    log_cb(f"Chrome 127.0.0.1:{port} 연결 중...")
    try:
        driver = webdriver.Chrome(options=opts)
        if driver_holder is not None:
            driver_holder["driver"] = driver
    except WebDriverException as e:
        _err_box(
            log_cb,
            f"Chrome 연결 실패 (포트 :{port})",
            str(e),
            [
                f"[Chrome 열기] 버튼을 먼저 클릭하고 포트 :{port} Chrome이 실행 중인지 확인하세요",
                "이미 동일 포트로 연결된 다른 프로세스가 있는지 확인하세요",
                "ChromeDriver 버전이 Chrome 브라우저와 맞지 않을 수 있습니다",
                "  → pip install --upgrade selenium webdriver-manager 실행 후 재시도하세요",
            ],
        )
        raise

    wait = WebDriverWait(driver, 10)
    log_cb("✓ Chrome 연결 완료")
    log_cb("")

    try:
        should_continue = _run_form(driver, wait, cfg, log_cb)
        if not should_continue:
            return
        log_cb("")
        _run_attach(driver, wait, cfg, log_cb)
        log_cb("")
        log_cb("🎉 전체 완료!")
    except Exception as e:
        log_cb("")
        log_cb("─" * 52)
        log_cb(f"  실행이 중단됐습니다.")
        log_cb(f"  원인: {_short_error(e)}")
        log_cb(f"  위의 위치/요소/화면 캡처/HTML 저장 로그를 확인하고 재시도하세요.")
        log_cb("─" * 52)
        raise

