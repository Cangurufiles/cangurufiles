#!/usr/bin/env python3
"""
Arturo Engine v4.0 - Genera data.json per la dashboard statica.
"""
import csv
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf

# ---------- CONFIGURAZIONE ----------
BASE_DIR = Path(__file__).parent.resolve()
FILE_CSV = BASE_DIR / "registro_can_guru.csv"
FILE_JSON = BASE_DIR / "data.json"
MANUAL_CSV = BASE_DIR / "manual_data.csv"

# Parametri fissi di calcolo
P_RAFF = 0.080
P_DIST = 0.130

ACCISA_D = 0.4729
SCADENZA_D = "22/05/2026"

ACCISA_B = 0.6229
SCADENZA_B = "22/05/2026"

URL_MIMIT = "https://www.mimit.gov.it/images/stories/carburanti/MediaRegionaleStradale.csv"

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ---------- FUNZIONI DI CALCOLO ----------
def calcola_arturo(brent_usd, cambio_eurusd, accisa):
    """Calcola il prezzo equo e il breakdown."""
    mat = brent_usd / cambio_eurusd / 159  # costo materia prima per litro
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

# ---------- FETCH DATI ----------
def get_mercati():
    """Ottiene Brent e cambio EUR/USD da Yahoo Finance. Fallback all'ultima riga del CSV."""
    try:
        brent = yf.Ticker("BZ=F").history(period="5d")['Close'].dropna().iloc[-1]
        cambio = yf.Ticker("EURUSD=X").history(period="5d")['Close'].dropna().iloc[-1]
        logger.info(f"Mercati: Brent={brent:.2f}, Cambio={cambio:.4f}")
        return float(brent), float(cambio)
    except Exception as e:
        logger.warning(f"Impossibile ottenere dati da Yahoo Finance: {e}")
        return last_from_csv()

def last_from_csv():
    """Legge l'ultima riga del CSV storico come fallback."""
    if not FILE_CSV.exists():
        logger.error("CSV storico non trovato, impossibile fallback.")
        return None, None
    try:
        with open(FILE_CSV, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return None, None
            last = rows[-1]
            return float(last["brent_usd"]), float(last["cambio_eurusd"])
    except Exception as e:
        logger.error(f"Errore nel leggere il CSV di fallback: {e}")
        return None, None

def get_mimit():
    """Scarica e calcola i prezzi medi MIMIT per diesel e benzina (self service)."""
    try:
        response = requests.get(URL_MIMIT, timeout=30)
        response.raise_for_status()
        lines = response.text.splitlines()
        if len(lines) < 2:
            raise ValueError("CSV MIMIT troppo corto")
        # La prima riga è un header estraneo, la seconda è la vera intestazione
        reader = csv.DictReader(lines[1:], delimiter=';')
        diesel_vals = []
        benzina_vals = []
        for row in reader:
            try:
                prezzo = float(row['PREZZO MEDIO'].replace(',', '.'))
                if 'SELF' in row['EROGAZIONE'].upper():
                    if 'BENZINA' in row['TIPOLOGIA'].upper():
                        benzina_vals.append(prezzo)
                    elif 'GASOLIO' in row['TIPOLOGIA'].upper():
                        diesel_vals.append(prezzo)
            except (KeyError, ValueError):
                continue
        if not diesel_vals or not benzina_vals:
            raise ValueError("Nessun prezzo valido trovato nel CSV MIMIT")
        d_medio = round(sum(diesel_vals) / len(diesel_vals), 3)
        b_medio = round(sum(benzina_vals) / len(benzina_vals), 3)
        logger.info(f"MIMIT: diesel={d_medio}, benzina={b_medio}")
        return d_medio, b_medio
    except Exception as e:
        logger.error(f"Errore download MIMIT: {e}")
        return None, None

# ---------- GESTIONE CSV STORICO ----------
def init_csv():
    """Crea il CSV storico se non esiste."""
    if not FILE_CSV.exists():
        with open(FILE_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["data", "brent_usd", "cambio_eurusd", "diesel_mimit", "benzina_mimit", "accisa_d", "accisa_b"])
        logger.info("Creato nuovo CSV storico.")

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def append_today():
    """Aggiunge la riga di oggi se non già presente."""
    oggi = today_str()
    if FILE_CSV.exists():
        with open(FILE_CSV, 'r', encoding='utf-8') as f:
            if any(oggi in line for line in f):
                logger.info("Dati di oggi già presenti nel CSV.")
                return

    brent, cambio = get_mercati()
    diesel, benzina = get_mimit()

    if brent is None or diesel is None:
        logger.error("Impossibile ottenere dati completi per oggi. CSV non aggiornato.")
        return

    with open(FILE_CSV, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([oggi, round(brent, 2), round(cambio, 4), diesel, benzina, ACCISA_D, ACCISA_B])
    logger.info("CSV aggiornato con i dati di oggi.")

# ---------- COSTRUZIONE JSON ----------
def build_json():
    """Crea il database JSON completo."""
    # Carica dati manuali (operatori ENI/IP)
    manual_map = {}
    if MANUAL_CSV.exists():
        with open(MANUAL_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                manual_map[row['data']] = row

    db = {
        "config": {
            "versione": "4.0",
            "accisa_d": ACCISA_D,
            "scadenza_d": SCADENZA_D,
            "accisa_b": ACCISA_B,
            "scadenza_b": SCADENZA_B
        },
        "meta": {
            "aggiornamento": datetime.now().strftime("%Y-%m-%d %H:%M")
        },
        "storico": []
    }

    if not FILE_CSV.exists():
        logger.error("CSV storico non trovato. Impossibile costruire JSON.")
        return

    with open(FILE_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data = row["data"]
            brent = float(row["brent_usd"])
            cambio = float(row["cambio_eurusd"])
            accisa_d = float(row["accisa_d"])
            accisa_b = float(row["accisa_b"])

            art_d = calcola_arturo(brent, cambio, accisa_d)
            art_b = calcola_arturo(brent, cambio, accisa_b)

            man = manual_map.get(data, {})
            eni_d = float(man.get("gasolio_eni", 0))
            bianche_d = float(man.get("gasolio_bianche", 0))
            eni_b = float(man.get("benzina_eni", 0))
            bianche_b = float(man.get("benzina_bianche", 0))

            db["storico"].append({
                "data": data,
                "brent": brent,
                "cambio": cambio,
                "diesel": {
                    "mimit": float(row["diesel_mimit"]),
                    "eni": eni_d,
                    "bianche": bianche_d,
                    "arturo": art_d["prezzo_equo"],
                    "mancia": round(float(row["diesel_mimit"]) - art_d["prezzo_equo"], 3),
                    "breakdown": art_d
                },
                "benzina": {
                    "mimit": float(row["benzina_mimit"]),
                    "eni": eni_b,
                    "bianche": bianche_b,
                    "arturo": art_b["prezzo_equo"],
                    "mancia": round(float(row["benzina_mimit"]) - art_b["prezzo_equo"], 3),
                    "breakdown": art_b
                }
            })

    with open(FILE_JSON, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    logger.info(f"JSON generato: {FILE_JSON} ({len(db['storico'])} record)")

# ---------- MAIN ----------
def main():
    logger.info("=== ARTURO ENGINE v4.0 ===")
    init_csv()
    append_today()
    build_json()
    logger.info("Operazione completata.")

if __name__ == "__main__":
    main()
