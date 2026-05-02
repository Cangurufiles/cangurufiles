#!/usr/bin/env python3
import json
import os
import re
import yfinance as yf
import requests
import csv
from datetime import datetime

# --- CONFIGURAZIONE PERCORSI ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_DATABASE = os.path.join(BASE_DIR, "database_prezzi.json")
FILE_HTML = os.path.join(BASE_DIR, "index.html")
FILE_CSV = os.path.join(BASE_DIR, "registro_can_guru.csv")
URL_MIMIT_CSV = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"

# --- PARAMETRI MANIFESTO ---
ACCISA_BENZINA = 0.6229
SCADENZA_BENZINA = "22-03-2026"

ACCISA_DIESEL = 0.4729
SCADENZA_DIESEL = "22-03-2026"

P_RAFF = 0.080
P_DIST = 0.130
IVA = 1.22
MARGINE_ARTURO = 1.03

def inizializza_csv():
    """Crea il CSV con l'intestazione se non esiste"""
    if not os.path.exists(FILE_CSV):
        with open(FILE_CSV, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["data", "brent_usd", "cambio_eurusd", "diesel_mimit", "benzina_mimit", "accisa_d", "accisa_b"])
        print(f"✔ Creato nuovo registro: {FILE_CSV}")

def recupera_mimit_csv():
    print("Arturo: Analisi CSV Mimit...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(URL_MIMIT_CSV, headers=headers, timeout=20)
        response.encoding = 'utf-8'
        linee = response.text.splitlines()
        reader = csv.DictReader(linee[1:], delimiter=';')
        somma_b, conta_b, somma_g, conta_g = 0, 0, 0, 0
        for riga in reader:
            try:
                p = float(riga['PREZZO MEDIO'].strip().replace(',', '.'))
                if 'SELF' in riga['EROGAZIONE'].upper():
                    if 'BENZINA' in riga['TIPOLOGIA'].upper():
                        somma_b += p; conta_b += 1
                    elif 'GASOLIO' in riga['TIPOLOGIA'].upper():
                        somma_g += p; conta_g += 1
            except: continue
        if conta_g == 0 or conta_b == 0: return None, None
        return round(somma_g/conta_g, 3), round(somma_b/conta_b, 3)
    except: return None, None

def aggiorna_sistema():
    print(f"--- {datetime.now().strftime('%d/%m/%Y %H:%M')} | SINCRONIZZAZIONE ---")
    inizializza_csv()

    try:
        brent = yf.Ticker("BZ=F").history(period="1d")['Close'].iloc[-1]
        cambio = yf.Ticker("EURUSD=X").history(period="1d")['Close'].iloc[-1]
    except:
        print("🛑 Errore mercati."); return

    diesel, benzina = recupera_mimit_csv()
    if diesel is None:
        print("🛑 Errore dati Mimit."); return

    oggi_str = datetime.now().strftime("%Y-%m-%d")

    # 1. PREPARAZIONE DATI
    nuovi_dati = {
        "data": oggi_str,
        "brent": round(float(brent), 2),
        "cambio": round(float(cambio), 4),
        "mimitDiesel": diesel,
        "mimitBenzina": benzina
    }

    # 2. AGGIORNAMENTO CSV (STORICO FISCALE)
    # Controlliamo se la data esiste già per evitare duplicati
    gia_presente = False
    with open(FILE_CSV, 'r', encoding='utf-8') as f:
        if oggi_str in f.read():
            gia_presente = True

    if not gia_presente:
        with open(FILE_CSV, 'a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                oggi_str,
                nuovi_dati["brent"],
                nuovi_dati["cambio"],
                diesel,
                benzina,
                ACCISA_DIESEL,
                ACCISA_BENZINA
            ])
        print("✔ Registro CSV aggiornato.")
    else:
        print("ℹ Dati odierni già presenti nel CSV.")

    # 3. AGGIORNAMENTO JSON DATABASE
    db_full = {
        "config": {
            "accisa_benzina": ACCISA_BENZINA,
            "scadenza_benzina": SCADENZA_BENZINA,
            "accisa_diesel": ACCISA_DIESEL,
            "scadenza_diesel": SCADENZA_DIESEL
        },
        "storico": []
    }

    if os.path.exists(FILE_DATABASE):
        with open(FILE_DATABASE, 'r', encoding='utf-8') as f:
            try:
                caricato = json.load(f)
                db_full["storico"] = caricato.get("storico", [])
            except: pass

    db_full["storico"] = [e for e in db_full["storico"] if e.get('data') != oggi_str]
    db_full["storico"].append(nuovi_dati)
    db_full["storico"].sort(key=lambda x: x['data'])

    with open(FILE_DATABASE, 'w', encoding='utf-8') as f:
        json.dump(db_full, f, indent=4)

    # 4. INIEZIONE NELL'HTML
    if os.path.exists(FILE_HTML):
        with open(FILE_HTML, 'r', encoding='utf-8') as f:
            html_content = f.read()

        db_js_string = json.dumps(db_full)
        pattern = r"// --- DATA START ---.*?// --- DATA END ---"
        replacement = f"// --- DATA START ---\nconst DATABASE_STORICO = {db_js_string};\n// --- DATA END ---"

        nuovo_html = re.sub(pattern, replacement, html_content, flags=re.DOTALL)

        with open(FILE_HTML, 'w', encoding='utf-8') as f:
            f.write(nuovo_html)
        print("✔ Dashboard HTML sincronizzata.")

    print("✔ Operazione completata.")

if __name__ == "__main__":
    aggiorna_sistema()
