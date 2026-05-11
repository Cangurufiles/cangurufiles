#!/usr/bin/env python3
import json, os, csv, requests, re, yfinance as yf
from datetime import datetime

# ================== PATH ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_CSV = os.path.join(BASE_DIR, "registro_can_guru.csv")
FILE_JSON = os.path.join(BASE_DIR, "database_prezzi.json")
FILE_HTML = os.path.join(BASE_DIR, "index.html") # <--- Trapiantato

URL_MIMIT = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"

# ================== CONFIG ==================
P_RAFF = 0.080
P_DIST = 0.130
ACCISA_D = 0.4729
ACCISA_B = 0.6229

# ================== UTIL ==================
def calcola_arturo(brent, cambio, accisa):
    mat = brent / cambio / 159
    base = mat + P_RAFF + P_DIST + accisa
    ebitda = base * 0.03
    iva = (base + ebitda) * 0.22
    prezzo = (base + ebitda) * 1.22

    return {
        "materia_prima": round(mat, 4),
        "raffinazione": P_RAFF,
        "distribuzione": P_DIST,
        "accisa": accisa,
        "ebitda": round(ebitda, 4),
        "iva": round(iva, 4),
        "prezzo_equo": round(prezzo, 3)
    }

# ================== MERCATI ==================
def get_last_from_csv():
    try:
        with open(FILE_CSV, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            if not rows: return None, None
            last = rows[-1]
            return float(last["brent_usd"]), float(last["cambio_eurusd"])
    except: return None, None

def get_mercati():
    try:
        brent = yf.Ticker("BZ=F").history(period="5d")['Close'].dropna().iloc[-1]
        cambio = yf.Ticker("EURUSD=X").history(period="5d")['Close'].dropna().iloc[-1]
        return float(brent), float(cambio)
    except:
        print("⚠️ Mercati non disponibili → fallback CSV")
        return get_last_from_csv()

# ================== MIMIT ==================
def get_mimit():
    try:
        r = requests.get(URL_MIMIT, timeout=20)
        lines = r.text.splitlines()
        reader = csv.DictReader(lines[1:], delimiter=';')
        b = g = bc = gc = 0
        for row in reader:
            try:
                p = float(row['PREZZO MEDIO'].replace(',', '.'))
                if 'SELF' in row['EROGAZIONE'].upper():
                    if 'BENZINA' in row['TIPOLOGIA'].upper():
                        b += p; bc += 1
                    elif 'GASOLIO' in row['TIPOLOGIA'].upper():
                        g += p; gc += 1
            except: continue
        return round(g/gc, 3), round(b/bc, 3)
    except:
        print("⚠️ Errore download MIMIT"); return None, None

# ================== AGGIORNAMENTO HTML ==================
def sync_html(db_data):
    """Il cuore del trapianto: scrive il JSON dentro index.html"""
    if not os.path.exists(FILE_HTML):
        print("⚠️ index.html non trovato, salto sync.")
        return

    try:
        with open(FILE_HTML, 'r', encoding='utf-8') as f:
            content = f.read()

        db_js_string = json.dumps(db_data)
        # Cerco i tag commentati che avevi inserito nell'HTML
        pattern = r"// --- DATA START ---.*?// --- DATA END ---"
        replacement = f"// --- DATA START ---\nconst DATABASE_STORICO = {db_js_string};\n// --- DATA END ---"

        if re.search(pattern, content, re.DOTALL):
            nuovo_html = re.sub(pattern, replacement, content, flags=re.DOTALL)
            with open(FILE_HTML, 'w', encoding='utf-8') as f:
                f.write(nuovo_html)
            print("✔ Dashboard HTML sincronizzata.")
        else:
            print("⚠️ Tag // --- DATA START --- non trovati nell'HTML.")
    except Exception as e:
        print(f"🛑 Errore Sync HTML: {e}")

# ================== LOGICA CORE ==================
def init_csv():
    if not os.path.exists(FILE_CSV):
        with open(FILE_CSV,'w',newline='',encoding='utf-8') as f:
            csv.writer(f).writerow(["data","brent_usd","cambio_eurusd","diesel_mimit","benzina_mimit","accisa_d","accisa_b"])

def append_today():
    today = datetime.now().strftime("%Y-%m-%d")
    # Facciamo il check se già fatto
    if os.path.exists(FILE_CSV):
        with open(FILE_CSV,'r',encoding='utf-8') as f:
            if any(today in line for line in f.readlines()):
                print("✔ Già aggiornato oggi")
                return

    brent, cambio = get_mercati()
    diesel, benzina = get_mimit()

    if brent and diesel:
        with open(FILE_CSV,'a',newline='',encoding='utf-8') as f:
            csv.writer(f).writerow([today, round(brent,2), round(cambio,4), diesel, benzina, ACCISA_D, ACCISA_B])
        print("✔ CSV aggiornato")

def build_and_sync():
    # 1. Carica dati manuali in un dizionario per data
    manual_map = {}
    if os.path.exists("manual_data.csv"):
        with open("manual_data.csv", 'r', encoding='utf-8') as f:
            m_reader = csv.DictReader(f)
            for row in m_reader:
                manual_map[row['data']] = row

    db = {
        "config": {"versione": "3.1", "accisa_d": ACCISA_D, "accisa_b": ACCISA_B},
        "meta": {"aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M")},
        "storico": []
    }

    with open(FILE_CSV,'r',encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            data_corrente = r["data"]
            b, c = float(r["brent_usd"]), float(r["cambio_eurusd"])
            art_d = calcola_arturo(b, c, float(r["accisa_d"]))
            art_b = calcola_arturo(b, c, float(r["accisa_b"]))

            # Recupera dati manuali se esistono
            m = manual_map.get(data_corrente, {})

            db["storico"].append({
                "data": data_corrente, "brent": b, "cambio": c,
                "diesel": {
                    "mimit": float(r["diesel_mimit"]),
                    "eni": float(m.get("gasolio_eni", 0)), # <--- Aggiunto
                    "bianche": float(m.get("gasolio_bianche", 0)), # <--- Aggiunto
                    "arturo": art_d["prezzo_equo"],
                    "mancia": round(float(r["diesel_mimit"]) - art_d["prezzo_equo"], 3),
                    "breakdown": art_d
                },
                "benzina": {
                    "mimit": float(r["benzina_mimit"]),
                    "eni": float(m.get("benzina_eni", 0)), # <--- Aggiunto
                    "bianche": float(m.get("benzina_bianche", 0)), # <--- Aggiunto
                    "arturo": art_b["prezzo_equo"],
                    "mancia": round(float(r["benzina_mimit"]) - art_b["prezzo_equo"], 3),
                    "breakdown": art_b}
            })

    # Scrivi il JSON
    with open(FILE_JSON,'w',encoding='utf-8') as f:
        json.dump(db, f, indent=2)
    print("✔ JSON aggiornato")

    # Esegui il trapianto nell'HTML
    sync_html(db)

# ================== MAIN ==================
if __name__ == "__main__":
    print("=== ARTURO ENGINE v3.1 (Sync Edition) ===")
    init_csv()
    append_today()
    build_and_sync()
