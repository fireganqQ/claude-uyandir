"""
Claude Uyandırma
----------------
ayarlar.json'daki saatlerde Claude Desktop'a ayarlanan mesajı gönderir.

Kullanım:
    python uyandir.py            -> zamanlayıcıyı başlatır (sürekli çalışır)
    python uyandir.py --simdi    -> mesajı hemen bir kez gönderir (test)
    python uyandir.py --plan     -> sıradaki gönderim saatlerini listeler
    python uyandir.py --kontrol  -> Claude penceresini bulup öne getirir, mesaj göndermez
"""

import ctypes
import json
import logging
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path

import pyperclip
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

KLASOR = Path(__file__).resolve().parent
AYAR_DOSYASI = KLASOR / "ayarlar.json"
LOG_DOSYASI = KLASOR / "uyandir.log"
CLAUDE_APP_ID = r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"
KACIRMA_TOLERANSI = timedelta(minutes=3)  # PC uykudan geç uyanırsa bu süre içinde yine gönderir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DOSYASI, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("uyandir")


# ---------------------------------------------------------------- ayarlar
def ayarlari_oku() -> dict:
    with open(AYAR_DOSYASI, encoding="utf-8") as f:
        ayar = json.load(f)
    if not str(ayar.get("mesaj", "")).strip():
        raise ValueError("ayarlar.json: 'mesaj' boş olamaz")
    if float(ayar["aralik_saat"]) <= 0:
        raise ValueError("ayarlar.json: 'aralik_saat' 0'dan büyük olmalı")
    _saat_dakika(ayar["baslangic_saati"])
    return ayar


def _saat_dakika(metin: str) -> int:
    """'HH:MM' -> gün içindeki dakika."""
    s, d = str(metin).strip().split(":")
    s, d = int(s), int(d)
    if not (0 <= s < 24 and 0 <= d < 60):
        raise ValueError(f"Geçersiz saat: {metin}")
    return s * 60 + d


def sonraki_gonderim(ayar: dict, baslangic_ani: datetime, simdi: datetime) -> datetime:
    """Program açıldığında ilk gönderim zamanını hesaplar.
    - Bugünkü başlangıç saati henüz gelmediyse: o saatte başlar.
    - Geçtiyse: başlangıç saatinden itibaren aralık serisindeki bir sonraki slota devam eder
      (son KACIRMA_TOLERANSI içinde kaçmış slot varsa hemen gönderir)."""
    dk = _saat_dakika(ayar["baslangic_saati"])
    capa = datetime.combine(baslangic_ani.date(), datetime.min.time()) + timedelta(minutes=dk)
    if simdi <= capa:
        return capa
    adim = timedelta(hours=float(ayar["aralik_saat"]))
    k = int((simdi - capa) / adim)
    slot = capa + k * adim
    if simdi - slot <= KACIRMA_TOLERANSI:
        return slot
    return slot + adim


# ---------------------------------------------------------------- pencere
def _exe_yolu(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        k32.CloseHandle(h)


def claude_penceresi_bul():
    """Claude Desktop ana penceresini bulur (CLI'deki claude.exe ile karışmaz)."""
    for w in Desktop(backend="win32").windows(class_name="Chrome_WidgetWin_1", visible_only=False):
        try:
            if w.window_text() != "Claude":
                continue
            yol = _exe_yolu(w.process_id()).lower()
            if "windowsapps" in yol and yol.endswith("claude.exe"):
                return w
        except Exception:
            continue
    return None


def claude_on_plana_getir(ayar: dict):
    w = claude_penceresi_bul()
    if w is None or not w.is_visible():
        log.info("Claude Desktop açılıyor / gösteriliyor...")
        os.startfile(CLAUDE_APP_ID)
        bitis = time.time() + float(ayar.get("uygulama_acilis_bekleme_sn", 8)) + 15
        while time.time() < bitis:
            time.sleep(1)
            w = claude_penceresi_bul()
            if w is not None and w.is_visible():
                break
        time.sleep(float(ayar.get("uygulama_acilis_bekleme_sn", 8)))
        w = claude_penceresi_bul()
    if w is None:
        raise RuntimeError("Claude Desktop penceresi bulunamadı")

    if w.is_minimized():
        w.restore()
    # Windows'un odak kilidini aşmak için ALT basıp bırak, sonra odakla
    send_keys("{VK_MENU}")
    w.set_focus()
    time.sleep(0.5)
    if ctypes.windll.user32.GetForegroundWindow() != w.handle:
        raise RuntimeError("Claude penceresi öne getirilemedi")
    return w


# ---------------------------------------------------------------- gönderim
def mesaj_gonder(ayar: dict) -> None:
    mesaj = str(ayar["mesaj"])
    claude_on_plana_getir(ayar)

    if ayar.get("yeni_sohbet_ac"):
        send_keys(ayar.get("yeni_sohbet_kisayolu", "^n"))
        time.sleep(2)

    time.sleep(float(ayar.get("gonderim_oncesi_bekleme_sn", 2)))

    try:
        eski_pano = pyperclip.paste()
    except Exception:
        eski_pano = None

    pyperclip.copy(mesaj)
    time.sleep(0.2)
    send_keys("^v")
    time.sleep(0.5)
    send_keys("{ENTER}")
    time.sleep(0.5)

    if eski_pano is not None:
        try:
            pyperclip.copy(eski_pano)
        except Exception:
            pass
    log.info("Mesaj gönderildi: %r", mesaj)


def guvenli_gonder(ayar: dict, deneme: int = 3) -> bool:
    for i in range(1, deneme + 1):
        try:
            mesaj_gonder(ayar)
            return True
        except Exception as e:
            log.error("Gönderim hatası (deneme %d/%d): %s", i, deneme, e)
            time.sleep(10)
    return False


# ---------------------------------------------------------------- zamanlayıcı
def zamanlayici() -> None:
    """Başlangıç saatinden itibaren, sen kapatana kadar her 'aralik_saat'te bir gönderir.
    Gece yarısında sıfırlanmaz; seri kesintisiz devam eder."""
    log.info("Zamanlayıcı başladı. Durdurmak için pencereyi kapat veya Ctrl+C.")
    acilis = datetime.now()
    son_anahtar = None
    sonraki = None

    while True:
        try:
            ayar = ayarlari_oku()  # her turda yeniden okunur: ayar değişikliği anında geçerli
        except Exception as e:
            log.error("Ayar hatası: %s", e)
            time.sleep(30)
            continue

        simdi = datetime.now()
        anahtar = (ayar["baslangic_saati"], float(ayar["aralik_saat"]))
        if anahtar != son_anahtar:  # ilk açılış veya saat/aralık değişti -> yeniden planla
            if son_anahtar is not None:
                acilis = simdi
            sonraki = sonraki_gonderim(ayar, acilis, simdi)
            son_anahtar = anahtar
            log.info("Her %s saatte bir gönderilecek. Sıradaki: %s",
                     ayar["aralik_saat"], sonraki.strftime("%d.%m %H:%M"))

        if simdi >= sonraki:
            if simdi - sonraki <= KACIRMA_TOLERANSI:
                guvenli_gonder(ayar)
            else:
                log.warning("%s gönderimi kaçırıldı (bilgisayar uykuda olabilir).",
                            sonraki.strftime("%d.%m %H:%M"))
            adim = timedelta(hours=float(ayar["aralik_saat"]))
            while sonraki <= datetime.now():
                sonraki += adim
            log.info("Sıradaki gönderim: %s", sonraki.strftime("%d.%m %H:%M"))

        time.sleep(15)


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--simdi":
        sys.exit(0 if guvenli_gonder(ayarlari_oku(), deneme=1) else 1)
    elif arg == "--plan":
        ayar = ayarlari_oku()
        simdi = datetime.now()
        t = sonraki_gonderim(ayar, simdi, simdi)
        adim = timedelta(hours=float(ayar["aralik_saat"]))
        print("Sıradaki 8 gönderim:", ", ".join((t + i * adim).strftime("%d.%m %H:%M") for i in range(8)))
    elif arg == "--kontrol":
        w = claude_on_plana_getir(ayarlari_oku())
        print(f"Claude penceresi bulundu ve öne getirildi (hwnd={w.handle}).")
    else:
        try:
            zamanlayici()
        except KeyboardInterrupt:
            log.info("Durduruldu.")


if __name__ == "__main__":
    main()
