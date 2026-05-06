import os
import time
import subprocess

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
)

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        r"Google\Chrome\Application\chrome.exe",
    ),
]

LOGIN_URL = "https://ev.or.kr/nportal/login.do"
FORM_URL = "https://ev.or.kr/ev_ps/ps/seller/sellerApplyform?car_type=11"

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


# ──────────────────────────────────────────
# Chrome 관련
# ──────────────────────────────────────────

def find_chrome():
    for p in _CHROME_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def open_chrome(port):
    chrome = find_chrome()
    if not chrome:
        raise FileNotFoundError("Chrome 실행 파일을 찾을 수 없습니다.")
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            LOGIN_URL,
        ],
        creationflags=subprocess.DETACHED_PROCESS,
    )


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
            break
        except NoSuchWindowException:
            return True, ""
        except Exception:
            break
    return False, ""


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


def _safe_input(wait, el_id, value, field_label, log):
    """입력 필드 — 요소를 찾지 못하면 가독성 있는 오류 출력."""
    try:
        wait.until(EC.element_to_be_clickable((By.ID, el_id))).send_keys(value)
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


def _run_form(driver, wait, cfg, log):
    log("━━━ [1단계] 신청서 작성 시작 ━━━")

    # 페이지 이동
    log(f"  → 페이지 이동 중...")
    try:
        driver.get(FORM_URL)
        time.sleep(1)
    except WebDriverException as e:
        _err_box(
            log,
            "페이지 이동 실패",
            str(e),
            [
                "Chrome이 포트에 올바르게 연결되어 있는지 확인하세요",
                "인터넷 연결 상태를 확인하세요",
            ],
        )
        raise
    log("  ✓ 페이지 로딩 완료")

    # 신청유형
    val = cfg["APPLICATION_TYPE"]
    log(f"  → [신청유형] '{val}' 선택 중...")
    _safe_select(driver, "req_kind", val, "신청유형", "APPLICATION_TYPE", log)
    time.sleep(0.5)
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
    _safe_input(wait, "req_cnt", val, "신청대수", log)
    log(f"  ✓ [신청대수] 완료")

    # 출고예정일
    val = cfg["DELIVERY_DATE"]
    log(f"  → [출고예정일] {val} 입력 중...")
    driver.execute_script(f"document.getElementById('delivery_sch_day').value = '{val}';")
    log(f"  ✓ [출고예정일] 완료")

    # 연락처
    log(f"  → [전화번호] {cfg['PHONE']} 입력 중...")
    _safe_input(wait, "phone", cfg["PHONE"], "전화번호", log)
    log(f"  ✓ [전화번호] 완료")

    log(f"  → [휴대폰] {cfg['MOBILE']} 입력 중...")
    _safe_input(wait, "mobile", cfg["MOBILE"], "휴대폰", log)
    log(f"  ✓ [휴대폰] 완료")

    email = cfg.get("EMAIL", "")
    log(f"  → [이메일] {email} 입력 중...")
    _safe_input(wait, "email", email, "이메일", log)
    log(f"  ✓ [이메일] 완료")

    # 기관 정보
    log(f"  → [기관명] {cfg['ORG_NAME']} 입력 중...")
    _safe_input(wait, "req_nm", cfg["ORG_NAME"], "기관명", log)
    log(f"  ✓ [기관명] 완료")

    val = cfg["APP_GUBUN"]
    log(f"  → [신청구분] '{val}' 선택 중...")
    _safe_select(driver, "grp_reqst_se", val, "신청구분", "APP_GUBUN", log)
    log(f"  ✓ [신청구분] 완료")

    log(f"  → [대표자] {cfg['NAME']} 입력 중...")
    _safe_input(wait, "ceo", cfg["NAME"], "대표자", log)
    log(f"  ✓ [대표자] 완료")

    log(f"  → [법인번호] {cfg['B_NUM']} 입력 중...")
    _safe_input(wait, "birth2", cfg["B_NUM"], "법인번호", log)
    log(f"  ✓ [법인번호] 완료")

    log(f"  → [사업자번호] {cfg['S_NUM']} 입력 중...")
    _safe_input(wait, "busi_no", cfg["S_NUM"], "사업자번호", log)
    log(f"  ✓ [사업자번호] 완료")

    log(f"  → [개인사업장명] {cfg['ORG_NAME']} 입력 중...")
    _safe_input(wait, "pri_busi_nm", cfg["ORG_NAME"], "개인사업장명", log)
    log(f"  ✓ [개인사업장명] 완료")

    log(f"  → [대리점연락처] {cfg['AGENCY_PHONE']} 입력 중...")
    _safe_input(wait, "seller_phone", cfg["AGENCY_PHONE"], "대리점연락처", log)
    log(f"  ✓ [대리점연락처] 완료")

    log(f"  → [담당자명] {cfg['CONTACT_NAME']} 입력 중...")
    _safe_input(wait, "contact_nm", cfg["CONTACT_NAME"], "담당자명", log)
    log(f"  ✓ [담당자명] 완료")

    log(f"  → [담당자연락처] {cfg['CONTACT_MOBILE']} 입력 중...")
    _safe_input(wait, "contact_mobile", cfg["CONTACT_MOBILE"], "담당자연락처", log)
    log(f"  ✓ [담당자연락처] 완료")

    log(f"  → [제조수입사관리번호] {cfg['MANUFACTURER_ID']} 입력 중...")
    _safe_input(wait, "seller_mgrid", cfg["MANUFACTURER_ID"], "제조수입사관리번호", log)
    log(f"  ✓ [제조수입사관리번호] 완료")

    # 주소 팝업
    log(f"  → [주소] 팝업 열기 (검색어: {cfg['ADDRESS']})")
    parent2 = driver.current_window_handle
    before2 = set(driver.window_handles)
    try:
        open_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//*[@onclick and contains(@onclick, '/ev_ps/addrlink/addrPopup')]",
            ))
        )
        open_btn.click()
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

    try:
        wait.until(lambda d: len(d.window_handles) > len(before2))
    except TimeoutException:
        _err_box(
            log, "주소 팝업이 열리지 않음",
            "팝업 창이 10초 내에 열리지 않았습니다",
            ["브라우저 팝업 차단 설정을 해제하세요"],
        )
        raise

    child2 = (set(driver.window_handles) - before2).pop()
    driver.switch_to.window(child2)
    log("  ✓ 주소 팝업 열림")

    kw = wait.until(EC.element_to_be_clickable((By.ID, "keyword")))
    kw.clear()
    kw.send_keys(cfg["ADDRESS"])
    log(f"  → 검색어 '{cfg['ADDRESS']}' 입력 후 검색 클릭")

    wait.until(
        EC.element_to_be_clickable((
            By.XPATH, "//button[contains(@onclick, 'searchUrlJuso')]"
        ))
    ).click()

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
    wait.until(EC.element_to_be_clickable((By.ID, "rtAddrDetail"))).send_keys(addr2)

    wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'setParent')]"))
    ).click()
    log("  ✓ 주소 확인, 팝업 닫힘")

    driver.switch_to.window(parent2)

    # 저장
    log("  → 저장(goSave) 버튼 클릭 중...")
    try:
        wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'goSave')]"))
        ).click()
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
    time.sleep(0.5)

    handled, txt = _accept_alert(driver, timeout=5)
    if handled:
        log(f"  ✓ Alert 확인: '{txt}'")
    else:
        log("  ✓ (goSave alert 없음)")

    # 보안코드
    log("  → 보안코드 창 대기 중...")
    parent3 = driver.current_window_handle
    before3 = set(driver.window_handles)
    try:
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > len(before3))
    except TimeoutException:
        _err_box(
            log,
            "보안코드 창이 열리지 않음",
            "저장 후 보안코드 팝업이 10초 내에 열리지 않았습니다",
            [
                "입력값에 유효성 오류가 있을 수 있습니다 (날짜 형식, 번호 자릿수 등)",
                "Alert 창이 떴다가 자동 닫혔을 수 있습니다 — 직접 확인해 보세요",
                "이미 제출된 신청건인지 확인하세요",
            ],
        )
        raise

    child3 = (set(driver.window_handles) - before3).pop()
    driver.switch_to.window(child3)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    log("  ✓ 보안코드 창 열림")

    try:
        code_text = driver.find_element(
            By.XPATH, "//tbody/tr[2]/td[2]//span[@class='guide']"
        ).text.strip()
    except NoSuchElementException:
        _err_box(
            log,
            "보안코드 텍스트를 찾을 수 없음",
            "보안코드 창의 구조가 예상과 다릅니다",
            [
                "사이트 업데이트로 보안코드 창 구조가 변경됐을 수 있습니다",
                "Chrome 창에서 보안코드 팝업을 직접 확인하세요",
            ],
        )
        raise

    reversed_code = code_text[::-1]
    log(f"  → 보안코드 원문: {code_text}  →  뒤집은값: {reversed_code}")

    random_box = wait.until(EC.element_to_be_clickable((By.ID, "randeomChk")))
    random_box.clear()
    random_box.send_keys(reversed_code)
    log("  ✓ 보안코드 입력 완료")

    wait.until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'goCompare')]"))
    ).click()
    log("  ✓ 확인 버튼 클릭")

    driver.switch_to.window(parent3)
    log("✅ [1단계] 신청서 작성 완료")


# ──────────────────────────────────────────
# 파일 첨부 (2단계)
# ──────────────────────────────────────────

def _handle_attach(driver, wait, attach_id, file_path, log):
    log(f"  → [{attach_id}] 첨부 팝업 열기 중...")
    parent_handle = driver.current_window_handle
    before = set(driver.window_handles)

    try:
        attach_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                f"//button[contains(@onclick, \"popupAttachFile('{attach_id}')\")]",
            ))
        )
        attach_btn.click()
    except TimeoutException:
        _err_box(
            log,
            f"[{attach_id}] 첨부 버튼을 찾을 수 없음",
            f"popupAttachFile('{attach_id}') 버튼이 페이지에 없습니다",
            [
                "1단계(신청서 작성)가 정상 완료됐는지 확인하세요",
                "보안코드 인증 후 첨부파일 버튼이 나타나는지 확인하세요",
                f"이 슬롯({attach_id})이 현재 신청 유형에 필요한지 확인하세요",
            ],
        )
        raise

    try:
        wait.until(lambda d: len(d.window_handles) > len(before))
    except TimeoutException:
        _err_box(
            log, f"[{attach_id}] 첨부 팝업이 열리지 않음",
            "팝업 창이 10초 내에 열리지 않았습니다",
            ["브라우저 팝업 차단 설정을 해제하세요"],
        )
        raise

    child = (set(driver.window_handles) - before).pop()
    driver.switch_to.window(child)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    log(f"  ✓ [{attach_id}] 첨부 팝업 열림")

    file_el = wait.until(EC.presence_of_element_located((By.ID, "filename")))
    driver.execute_script(
        """
        const el = arguments[0];
        el.removeAttribute('disabled');
        el.removeAttribute('readonly');
        el.style.cssText = 'display:block;visibility:visible;opacity:1;'
                         + 'position:static;width:420px;height:32px;z-index:999999;';
        """,
        file_el,
    )
    time.sleep(0.2)

    log(f"  → [{attach_id}] 파일 경로 입력: {file_path}")
    last_err = None
    for attempt in range(2):
        try:
            file_el.send_keys(file_path)
            last_err = None
            break
        except (ElementNotInteractableException, InvalidArgumentException, Exception) as e:
            last_err = e
            _warn_box(log, f"[{attach_id}] 파일 입력 시도 {attempt + 1} 실패", repr(e))
            time.sleep(0.3)
    if last_err:
        _err_box(
            log,
            f"[{attach_id}] 파일 업로드 실패",
            repr(last_err),
            [
                f"파일 경로가 올바른지 확인하세요: {file_path}",
                "경로에 공백이나 특수문자가 있으면 큰따옴표로 묶으세요",
                "해당 파일이 실제로 존재하는지 확인하세요",
            ],
        )
        raise RuntimeError(f"[{attach_id}] 파일 업로드 실패: {repr(last_err)}")
    log(f"  ✓ [{attach_id}] 파일 경로 입력 완료")

    log(f"  → [{attach_id}] 저장 버튼 클릭 중...")
    try:
        popup_form = wait.until(
            EC.presence_of_element_located((
                By.XPATH,
                "//form[@name='frm' and @action='/ev_ps/ps/comm/popupAttach/cud'"
                " and .//h1[contains(normalize-space(.), '첨부파일')]]",
            ))
        )
        save_btn = popup_form.find_element(
            By.XPATH,
            ".//div[contains(@class,'content-button-group')]"
            "//button[contains(@class,'btn-blue') and contains(@onclick,'goSave')]",
        )
        wait.until(EC.element_to_be_clickable(save_btn))
        save_btn.click()
    except (TimeoutException, NoSuchElementException) as e:
        _err_box(
            log,
            f"[{attach_id}] 첨부 저장 버튼을 찾을 수 없음",
            repr(e),
            ["첨부파일 팝업 창의 구조가 변경됐을 수 있습니다"],
        )
        raise

    handled, txt = _accept_alert(driver, timeout=5, retries=2)
    if handled:
        log(f"  ✓ [{attach_id}] Alert 처리: '{txt}'")

    child_handle = driver.current_window_handle
    try:
        WebDriverWait(driver, 3).until(lambda d: child_handle not in d.window_handles)
        log(f"  ✓ [{attach_id}] 팝업 닫힘")
    except TimeoutException:
        _warn_box(log, f"[{attach_id}] 팝업 자동 닫힘 안됨", "계속 진행합니다")

    try:
        if parent_handle in driver.window_handles:
            driver.switch_to.window(parent_handle)
        else:
            driver.switch_to.window(driver.window_handles[0])
    except NoSuchWindowException:
        driver.switch_to.window(driver.window_handles[0])

    handled2, txt2 = _accept_alert(driver, timeout=3, retries=2)
    if handled2:
        log(f"  ✓ [{attach_id}] 부모창 Alert 처리: '{txt2}'")

    log(f"  ✅ [{attach_id}] 첨부 완료")


def _run_attach(driver, wait, cfg, log):
    log("━━━ [2단계] 파일 첨부 및 지원신청 시작 ━━━")
    file_path = cfg.get("FILE1", "")
    log(f"  첨부 파일: {file_path}")

    for attach_id in ["A", "A2", "A3"]:
        log(f"  → [{attach_id}] 처리 시작")
        try:
            _handle_attach(driver, wait, attach_id, file_path, log)
        except Exception as e:
            _warn_box(log, f"[{attach_id}] 실패 — 다음 슬롯으로 넘어갑니다", repr(e))
            try:
                if driver.window_handles:
                    driver.switch_to.window(driver.window_handles[0])
            except Exception:
                pass

    log("  → 지원신청 버튼 클릭 중...")
    try:
        wait.until(
            EC.element_to_be_clickable((
                By.XPATH, "//button[contains(@onclick, \"goApply('101'\")]"
            ))
        ).click()
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

    log("✅ [2단계] 완료")


# ──────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────

def run_all(env_path, port, log_cb, file1_path=None):
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

    log_cb(f"Chrome 127.0.0.1:{port} 연결 중...")
    try:
        driver = webdriver.Chrome(options=opts)
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
        _run_form(driver, wait, cfg, log_cb)
        log_cb("")
        _run_attach(driver, wait, cfg, log_cb)
        log_cb("")
        log_cb("🎉 전체 완료!")
    except Exception as e:
        log_cb("")
        log_cb("─" * 52)
        log_cb(f"  실행이 중단됐습니다.")
        log_cb(f"  위의 ❌ 오류 메시지를 확인하고 수정 후 재시도하세요.")
        log_cb("─" * 52)
        raise
