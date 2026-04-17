
import os
import time
import random
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL    = "https://www.justice.gov"
START_URL   = "https://www.justice.gov/epstein/doj-disclosures/data-set-12-files"
OUTPUT_DIR  = "dataset12_pdfs"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ── 1. Inicia Chrome via Selenium ──────────────────────────────────────────────
def init_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )
    return driver


# ── 2. Extrai links PDF de uma pagina já carregada no driver ───────────────────
def extract_pdf_links(driver):
    links = []
    anchors = driver.find_elements(By.TAG_NAME, "a")
    for a in anchors:
        href = a.get_attribute("href") or ""
        if href.lower().endswith(".pdf"):
            text = a.text.strip()
            links.append((href, text))
    return links


def ensure_age_verified(driver, wait):
    if any(
        cookie.get("name") == "justiceGovAgeVerified" and cookie.get("value") == "true"
        for cookie in driver.get_cookies()
    ):
        return

    try:
        yes_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Yes']"))
        )
    except TimeoutException:
        return

    yes_button.click()

    wait.until(
        lambda current_driver: any(
            cookie.get("name") == "justiceGovAgeVerified" and cookie.get("value") == "true"
            for cookie in current_driver.get_cookies()
        )
    )
    time.sleep(1)


# ── 3. Detecta total de paginas ────────────────────────────────────────────────
def get_total_pages(driver):
    page_nums = [0]
    anchors = driver.find_elements(By.TAG_NAME, "a")
    for a in anchors:
        href = a.get_attribute("href") or ""
        if "?page=" in href:
            try:
                num = int(href.split("?page=")[1].split("&")[0])
                page_nums.append(num)
            except ValueError:
                pass
    return max(page_nums) + 1


# ── 4. Copia cookies do Selenium para o requests.Session ──────────────────────
def selenium_cookies_to_session(driver, session):
    session.cookies.clear()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])


def is_valid_pdf_file(filepath):
    if not os.path.exists(filepath):
        return False

    try:
        with open(filepath, "rb") as file_handle:
            return file_handle.read(5) == b"%PDF-"
    except OSError:
        return False


# ── 5. Baixa PDF usando requests com os cookies do browser ────────────────────
def download_pdf(url, output_dir, session, referer):
    filename = url.split("/")[-1]
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        if is_valid_pdf_file(filepath):
            print(f"  [JA EXISTE] {filename}")
            return "skip"

        os.remove(filepath)
        print(f"  [INVALIDO] removendo arquivo quebrado: {filename}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
        "Referer": referer,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        time.sleep(random.uniform(0.8, 2.0))
        resp = session.get(url, headers=headers, timeout=60, stream=True)
        resp.raise_for_status()

        content_type = (resp.headers.get("Content-Type") or "").lower()
        chunk_iterator = resp.iter_content(chunk_size=16384)
        first_chunk = next(chunk_iterator, b"")

        if "application/pdf" not in content_type or not first_chunk.startswith(b"%PDF-"):
            preview = first_chunk[:120].decode("utf-8", errors="ignore").strip()
            print(
                f"  [ERRO] {filename}: resposta nao e PDF valido "
                f"(content-type={content_type or 'desconhecido'}, preview={preview!r})"
            )
            return "error"

        with open(filepath, "wb") as f:
            f.write(first_chunk)
            for chunk in chunk_iterator:
                f.write(chunk)

        size_kb = os.path.getsize(filepath) / 1024
        print(f"  [OK] {filename} ({size_kb:.1f} KB)")
        return "ok"
    except Exception as e:
        print(f"  [ERRO] {filename}: {e}")
        return "error"


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=== DOJ Epstein Library - Data Set 12 Downloader v3 (Selenium) ===")
    print(f"Diretorio de saida: {os.path.abspath(OUTPUT_DIR)}\n")

    print("Iniciando Chrome via Selenium...")
    driver = init_driver(headless=True)
    wait   = WebDriverWait(driver, 15)
    sess   = requests.Session()

    try:
        # Visita pagina inicial
        print(f"Acessando: {START_URL}")
        driver.get(START_URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        ensure_age_verified(driver, wait)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
        time.sleep(random.uniform(2, 3))

        total_pages = get_total_pages(driver)
        print(f"Total de paginas: {total_pages}\n")

        all_pdf_links = []

        for page_num in range(total_pages):
            if page_num == 0:
                page_url = START_URL
            else:
                page_url = f"{START_URL}?page={page_num}"
                print(f"Navegando para pagina {page_num + 1}: {page_url}")
                driver.get(page_url)
                ensure_age_verified(driver, wait)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "a")))
                time.sleep(random.uniform(2, 4))

            links = extract_pdf_links(driver)
            print(f"Pagina {page_num + 1}/{total_pages}: {len(links)} PDFs encontrados")
            all_pdf_links.extend(links)

        # Remove duplicatas
        seen = set()
        unique_links = []
        for url, name in all_pdf_links:
            if url not in seen:
                seen.add(url)
                unique_links.append((url, name))

        print(f"\nTotal de PDFs unicos coletados: {len(unique_links)}")
        print("Copiando cookies do browser para requests...\n")
        selenium_cookies_to_session(driver, sess)

    finally:
        driver.quit()
        print("Browser encerrado.\n")

    # Downloads via requests (mais rapido que Selenium para binarios)
    print("Iniciando downloads...\n")
    baixados = erros = pulados = 0

    for i, (url, _) in enumerate(unique_links, 1):
        print(f"[{i}/{len(unique_links)}] {url.split('/')[-1]}")
        result = download_pdf(url, OUTPUT_DIR, sess, referer=START_URL)
        if result == "ok":
            baixados += 1
        elif result == "skip":
            pulados += 1
        else:
            erros += 1

    print(f"\n{'='*50}")
    print(f"Concluido!")
    print(f"  Baixados  : {baixados}")
    print(f"  Ja tinham : {pulados}")
    print(f"  Erros     : {erros}")
    print(f"  Total dir : {len(os.listdir(OUTPUT_DIR))} arquivos")
    print(f"  Local     : {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
