import time
import re
import uuid
import os
from datetime import datetime, date

from selenium import webdriver                                          # type: ignore
from selenium.webdriver.chrome.service import Service                   # type: ignore
from selenium.webdriver.chrome.options import Options                   # type: ignore
from selenium.webdriver.common.by import By                             # type: ignore  
from selenium.webdriver.support.ui import WebDriverWait                 # type: ignore
from selenium.webdriver.support import expected_conditions as EC        # type: ignore


# --- CONFIG ---
URL_ENT = "https://ent.cesi.fr/accueil-apprenant"
URL_EDT = "https://ent.cesi.fr/mon-emploi-du-temps"

# Charger les identifiants depuis les variables d'environnement
IDENTIFIANT = os.getenv("IDENTIFIANT", "").strip()
MOT_DE_PASSE = os.getenv("MOT_DE_PASSE", "").strip()

if not IDENTIFIANT or not MOT_DE_PASSE:
    raise ValueError("Les variables d'environnement IDENTIFIANT et MOT_DE_PASSE doivent être définies.")

TZ = "Europe/Paris"
NB_SEMAINES = 4
DELAI_ENTRE_SEMAINES_SECONDES = 2

MAX_CLICS_PREV_POUR_TROUVER_SEMAINE_COURANTE = 8  # sécurité


# ------------------ ICS (manuel) ------------------
def ics_escape(value: str) -> str:
    if value is None:
        return ""
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n")
    value = value.replace(",", "\\,")
    value = value.replace(";", "\\;")
    return value


def to_ics_dt(date_yyyy_mm_dd: str, hhmm: str) -> str:
    dt = datetime.strptime(f"{date_yyyy_mm_dd} {hhmm}", "%Y-%m-%d %H:%M")
    return dt.strftime("%Y%m%dT%H%M%S")


def build_ics(events: list[dict]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ENT CESI Scraper//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{TZ}",
    ]

    for ev in events:
        uid = str(uuid.uuid4())
        dtstart = to_ics_dt(ev["date"], ev["start"])
        dtend = to_ics_dt(ev["date"], ev["end"])

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{ics_escape(ev['title'])}",
            f"DTSTART;TZID={TZ}:{dtstart}",
            f"DTEND;TZID={TZ}:{dtend}",
        ]

        loc = ev.get("location", "").strip()
        if loc:
            lines.append(f"LOCATION:{ics_escape(loc)}")

        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ------------------ PARSING EDT ------------------
def parse_time_range(text: str) -> tuple[str, str]:
    m = re.search(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", text)
    if not m:
        raise ValueError(f"Format horaire inattendu: {text!r}")
    return m.group(1), m.group(2)


def get_week_signature(driver) -> str:
    sig = driver.execute_script("""
        const tds = Array.from(document.querySelectorAll('td.fc-day[data-date]'));
        const dates = [...new Set(tds.map(td => td.getAttribute('data-date')).filter(Boolean))].sort();
        return dates.join('|');
    """)
    return sig or ""


def week_contains_date(sig: str, yyyy_mm_dd: str) -> bool:
    # sig ressemble à "2026-02-16|2026-02-17|..."
    return yyyy_mm_dd in sig.split("|") if sig else False


def get_day_columns(driver) -> list[dict]:
    cols = driver.execute_script("""
        const tds = Array.from(document.querySelectorAll('td.fc-day[data-date]'));
        const byDate = new Map();
        for (const td of tds) {
            const date = td.getAttribute('data-date');
            if (!date) continue;
            const r = td.getBoundingClientRect();
            const prev = byDate.get(date);
            if (!prev || (r.right - r.left) > (prev.right - prev.left)) {
                byDate.set(date, { date, left: r.left, right: r.right });
            }
        }
        return Array.from(byDate.values()).sort((a,b) => a.left - b.left);
    """)
    if not cols:
        raise RuntimeError("Impossible de détecter les colonnes de jours via td.fc-day[data-date].")
    return cols


def date_for_event_by_x(driver, event_element, day_columns: list[dict]) -> str:
    mid_x = driver.execute_script("""
        const el = arguments[0];
        const r = el.getBoundingClientRect();
        return (r.left + r.right) / 2.0;
    """, event_element)

    for col in day_columns:
        if col["left"] <= mid_x <= col["right"]:
            return col["date"]

    closest = min(day_columns, key=lambda c: abs(((c["left"] + c["right"]) / 2.0) - mid_x))
    return closest["date"]


def scrape_events_week(driver) -> list[dict]:
    day_columns = get_day_columns(driver)
    event_elements = driver.find_elements(By.CSS_SELECTOR, "a.fc-time-grid-event")

    events = []
    for el in event_elements:
        title = el.find_element(By.CSS_SELECTOR, ".fc-title").text.strip()

        time_el = el.find_element(By.CSS_SELECTOR, ".fc-time")
        time_range = (time_el.get_attribute("data-full") or time_el.text).strip()
        start_hhmm, end_hhmm = parse_time_range(time_range)

        salle_el = el.find_elements(By.CSS_SELECTOR, ".fc-salles")
        location = salle_el[0].text.strip() if salle_el else ""

        date_yyyy_mm_dd = date_for_event_by_x(driver, el, day_columns)

        events.append({
            "title": title,
            "date": date_yyyy_mm_dd,
            "start": start_hhmm,
            "end": end_hhmm,
            "location": location,
        })

    events.sort(key=lambda e: (e["date"], e["start"], e["title"]))
    return events


def event_key(ev: dict) -> tuple:
    return (ev["date"], ev["start"], ev["end"], ev["title"], ev.get("location", ""))


def ensure_current_week_visible(driver, wait: WebDriverWait):
    """
    Force l'affichage de la semaine contenant aujourd'hui.
    Si la vue est déjà sur la bonne semaine: ne fait rien.
    Sinon clique sur "prev" jusqu'à trouver la date du jour.
    """
    today_str = date.today().strftime("%Y-%m-%d")

    sig = wait.until(lambda d: get_week_signature(d))
    if week_contains_date(sig, today_str):
        return

    # Si on est "trop en avance", on recule.
    for _ in range(MAX_CLICS_PREV_POUR_TROUVER_SEMAINE_COURANTE):
        prev_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.fc-prev-button")))
        prev_btn.click()
        time.sleep(1)  # petit délai pour laisser re-render

        wait.until(lambda d: get_week_signature(d) != sig)
        sig = get_week_signature(driver)

        if week_contains_date(sig, today_str):
            return

    # Si on n'a pas trouvé, on continue quand même (mais au moins pas de boucle infinie)
    print("Attention: impossible de retrouver la semaine courante automatiquement (limite atteinte).")


# ------------------ MAIN ------------------
def main():
    chrome_options = Options()
    chrome_options.add_argument("--incognito")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Utiliser le chromedriver du système
    try:
        # En Docker, le chromedriver est à /usr/bin/chromedriver
        # En local, chercher dans le PATH
        chromedriver_path = "/usr/bin/chromedriver"
        
        if not os.path.exists(chromedriver_path):
            # Fallback: chercher dans le PATH
            chromedriver_path = "chromedriver"
        
        driver = webdriver.Chrome(
            service=Service(chromedriver_path),
            options=chrome_options
        )
    except Exception as e:
        print(f"Erreur: Chrome/Chromium n'est pas correctement configuré: {e}")
        raise
    
    wait = WebDriverWait(driver, 25)

    try:
        # Connexion ENT
        driver.get(URL_ENT)

        champ_login = wait.until(EC.presence_of_element_located((By.ID, "login")))
        champ_login.clear()
        champ_login.send_keys(IDENTIFIANT)
        wait.until(EC.element_to_be_clickable((By.ID, "submit"))).click()

        champ_password = wait.until(EC.presence_of_element_located((By.ID, "passwordInput")))
        champ_password.clear()
        champ_password.send_keys(MOT_DE_PASSE)
        wait.until(EC.element_to_be_clickable((By.ID, "submitButton"))).click()

        wait.until(EC.url_contains("ent.cesi.fr"))

        # Aller sur l'emploi du temps
        driver.get(URL_EDT)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".js-calendar__wrapper")))

        # --- IMPORTANT: se repositionner sur la semaine courante ---
        ensure_current_week_visible(driver, wait)

        # --- Scrape 4 semaines (courante + 3 suivantes) ---
        all_events_map: dict[tuple, dict] = {}

        for i in range(NB_SEMAINES):
            sig = wait.until(lambda d: get_week_signature(d))

            # ⏳ Attente AVANT le scrape
            if i == 0:
                # Première semaine : laisser FullCalendar charger les events
                time.sleep(DELAI_ENTRE_SEMAINES_SECONDES)

            week_events = scrape_events_week(driver)

            added = 0
            for ev in week_events:
                k = event_key(ev)
                if k not in all_events_map:
                    all_events_map[k] = ev
                    added += 1

            print(f"Semaine {i+1}/{NB_SEMAINES}: {len(week_events)} cours trouvés, +{added} nouveaux.")

            if i == NB_SEMAINES - 1:
                break

            next_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.fc-next-button"))
            )
            next_btn.click()

            # ⏳ Attente entre chaque semaine
            time.sleep(DELAI_ENTRE_SEMAINES_SECONDES)

            wait.until(lambda d: get_week_signature(d) != sig)


        # Export final
        final_events = list(all_events_map.values())
        final_events.sort(key=lambda e: (e["date"], e["start"], e["title"]))

        print(f"Total unique: {len(final_events)} cours.")

        ics_text = build_ics(final_events)
        
        # Générer le nom du fichier avec la date et l'heure
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = f"emploi_du_temps_{timestamp}.ics"
        
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(ics_text)

        print(f"Fichier ICS généré: {out_path}")
        print("Scraping terminé avec succès!")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
