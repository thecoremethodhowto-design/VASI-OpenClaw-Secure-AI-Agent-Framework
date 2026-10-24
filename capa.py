"""Denetim zincirinin ucunu makinenin DISINA capalar (RFC 3161 zaman damgasi).

NEDEN
    Iki tanik (dosya ve veritabani) ayni makinede. Makineye ve veritabaninin
    super kullanicisina erisen biri ikisini birlikte yeniden yazabilir
    (tests/test_audit_store_pg.py::test_SINIR_super_kullanici_tanigi_hala_silebilir).
    MITRE ATT&CK M1029 (Remote Data Storage) tam olarak bunu soyler: kaniti
    yerel makineden cikar.

NASIL
    Belli araliklarla zincirin o anki ucu -- (sira, ozet) -- disaridaki bir
    zaman damgasi otoritesine (TSA, varsayilan freeTSA) gonderilir. TSA,
    "bu ozet su saatte vardi" diyen IMZALI bir makbuz dondurur. Makbuzu
    geriye tarihli olarak kimse uretemez: imza anahtari TSA'da, bu makinede
    degil. Makbuzun bir kopyasi Telegram'dan sahibine gider; makine silinse
    bile kopya onun telefonunda kalir.

    Capalanan metin (makbuz bunun SHA-256 ozetini imzalar):

        vasi-capa 1
        sira=<N>
        ozet=<32 hex>

    Makbuz dosyasi: capa-<sira:08d>-<ozet>.tsr. Metin dosya adindan yeniden
    kurulur; adi degistirilen bir makbuz imzayla uyusmaz.

NE YAKALAR
    - capalanmis bir halkanin sonradan yeniden yazilmasi (ozet tutmaz)
    - zincirin sonunun kesilip yeniden kurulmasi (capa, zincirin ilerisinde)
    - ayni siraya iki farkli capa (biri zinciri yeniden yazip yeniden capaladi)
    - sahte, bozuk ya da baska bir TSA'nin makbuzu (imza / sertifika)

NE YAKALAYAMAZ (testlerde test_SINIR_ olarak yazili)
    - son capadan SONRA yazilan halkalar korunmaz: pencere, capa sikligidir
    - bu makinedeki makbuzlar silinebilir. Sahtesi uretilemez ama "hic
      yoktu" denebilir. Buna karsi duran, sahibin Telegram'daki kopyalaridir:
      onlar bu dogrulayiciya verilince silinen capa yeniden ortaya cikar.

GUVEN
    Imza, depodaki TSA sertifikasiyla dogrulanir (scripts/capa/freetsa/).
    Sertifika makinede degil, depoda durur; parmak izi TSA'nin sitesinde
    yayinlanir. Sertifika yoksa makbuz yine saklanir ama imzasi
    "dogrulanmadi" olarak raporlanir -- sessizce gecilmez.

KATMAN KURALI
    Yalnizca standart kutuphane + audit_chain (ayni kural: yerel modul yok).
    Imza dogrulamasi icin `cryptography` gerekir; yoksa ozet ve zaman yine
    kontrol edilir, imza "dogrulanamadi (cryptography yok)" der. macOS'ta:

        python3 capa.py denetim/denetim.log --capa denetim/capa
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Telegram ayni adi ikinci kez indirince "capa-...(1).tsr" ya da "capa-... (1).tsr" yapar.
MAKBUZ_ADI = re.compile(r"^capa-(?P<sira>\d{8})-(?P<ozet>[0-9a-f]{32})(?: ?\(\d+\))?\.tsr$")
VARSAYILAN_TSA = "https://freetsa.org/tsr"
_EN_FAZLA_YANIT = 64 * 1024

# ── OID'ler ──────────────────────────────────────────────────────────────────
OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_TSTINFO = "1.2.840.113549.1.9.16.1.4"
OID_CONTENT_TYPE = "1.2.840.113549.1.9.3"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
OID_SHA256 = "2.16.840.1.101.3.4.2.1"
_OZET_ALGORITMALARI = {
    "1.3.14.3.2.26": "sha1",
    "2.16.840.1.101.3.4.2.1": "sha256",
    "2.16.840.1.101.3.4.2.2": "sha384",
    "2.16.840.1.101.3.4.2.3": "sha512",
}
_IMZA_ALGORITMALARI = {     # oid -> (anahtar turu, ozet; None = signer'in ozeti)
    "1.2.840.10045.4.3.2": ("ec", "sha256"),
    "1.2.840.10045.4.3.3": ("ec", "sha384"),
    "1.2.840.10045.4.3.4": ("ec", "sha512"),
    "1.2.840.10045.2.1": ("ec", None),
    "1.2.840.113549.1.1.11": ("rsa", "sha256"),
    "1.2.840.113549.1.1.12": ("rsa", "sha384"),
    "1.2.840.113549.1.1.13": ("rsa", "sha512"),
    "1.2.840.113549.1.1.1": ("rsa", None),
}


class CapaHatasi(Exception):
    """Makbuz alinamadi ya da gecersiz."""


# ── DER: en kucuk okuyucu ve yazici ──────────────────────────────────────────

@dataclass
class _Oge:
    etiket: int
    deger: bytes
    ham: bytes          # etiket + uzunluk + deger

    def cocuklar(self) -> list:
        return _hepsini_oku(self.deger)


def _oku(b: bytes, i: int = 0):
    if i + 2 > len(b):
        raise CapaHatasi("DER: beklenmeyen son")
    bas = i
    etiket = b[i]
    if etiket & 0x1F == 0x1F:
        raise CapaHatasi("DER: uzun etiket desteklenmiyor")
    n = b[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        if k == 0 or k > 4 or i + k > len(b):
            raise CapaHatasi("DER: gecersiz uzunluk")
        n = int.from_bytes(b[i:i + k], "big")
        i += k
    son = i + n
    if son > len(b):
        raise CapaHatasi("DER: uzunluk veriyi asiyor")
    return _Oge(etiket, b[i:son], b[bas:son]), son


def _hepsini_oku(b: bytes) -> list:
    i, ogeler = 0, []
    while i < len(b):
        o, i = _oku(b, i)
        ogeler.append(o)
    return ogeler


def _tek(b: bytes) -> _Oge:
    o, son = _oku(b)
    if son != len(b):
        raise CapaHatasi("DER: fazladan bayt")
    return o


def _beklenen(o: _Oge, etiket: int, ne: str) -> _Oge:
    if o.etiket != etiket:
        raise CapaHatasi(f"DER: {ne} bekleniyordu (etiket {o.etiket:#x})")
    return o


def _oid_coz(o: _Oge) -> str:
    _beklenen(o, 0x06, "OID")
    b = o.deger
    if not b:
        raise CapaHatasi("DER: bos OID")
    parcalar, deger = [], 0
    for x in b:
        deger = (deger << 7) | (x & 0x7F)
        if not x & 0x80:
            parcalar.append(deger)
            deger = 0
    ilk = parcalar[0]
    bas = [min(ilk // 40, 2), ilk - 40 * min(ilk // 40, 2)]
    return ".".join(str(p) for p in bas + parcalar[1:])


def _tamsayi(o: _Oge) -> int:
    _beklenen(o, 0x02, "INTEGER")
    return int.from_bytes(o.deger, "big", signed=True)


def _zaman_coz(o: _Oge) -> datetime:
    _beklenen(o, 0x18, "GeneralizedTime")
    m = re.fullmatch(r"(\d{14})(?:\.(\d{1,6})\d*)?Z", o.deger.decode("ascii", "replace"))
    if not m:
        raise CapaHatasi("DER: zaman bicimi tanınmadi")
    z = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if m.group(2):
        z += timedelta(microseconds=int(m.group(2).ljust(6, "0")))
    return z


def _uzunluk(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(etiket: int, deger: bytes) -> bytes:
    return bytes([etiket]) + _uzunluk(len(deger)) + deger


def _oid_yaz(oid: str) -> bytes:
    p = [int(x) for x in oid.split(".")]
    govde = bytearray([40 * p[0] + p[1]])
    for x in p[2:]:
        parca = [x & 0x7F]
        x >>= 7
        while x:
            parca.append(0x80 | (x & 0x7F))
            x >>= 7
        govde.extend(reversed(parca))
    return _tlv(0x06, bytes(govde))


def _tamsayi_yaz(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True)
    return _tlv(0x02, b)


# ── Capa metni ve istek ──────────────────────────────────────────────────────

def capa_metni(sira: int, ozet: str) -> bytes:
    if sira < 1 or not re.fullmatch(r"[0-9a-f]{32}", ozet):
        raise ValueError("capa: gecersiz sira ya da ozet")
    return f"vasi-capa 1\nsira={sira}\nozet={ozet}\n".encode("ascii")


def makbuz_adi(sira: int, ozet: str) -> str:
    return f"capa-{sira:08d}-{ozet}.tsr"


def istek_olustur(veri_ozeti: bytes, nonce: int) -> bytes:
    """RFC 3161 TimeStampReq: v1, SHA-256 ozeti, nonce, sertifika iste."""
    alg = _tlv(0x30, _oid_yaz(OID_SHA256) + b"\x05\x00")
    imprint = _tlv(0x30, alg + _tlv(0x04, veri_ozeti))
    return _tlv(0x30, _tamsayi_yaz(1) + imprint + _tamsayi_yaz(nonce) + b"\x01\x01\xff")


# ── Makbuz ayristirma ve dogrulama ──────────────────────────────────────────

@dataclass
class Makbuz:
    zaman: datetime
    seri: int
    imprint_alg: str
    imprint: bytes
    nonce: int | None
    imza: str = "dogrulanmadi"      # "dogrulandi" | "dogrulanmadi: <neden>" | "gecersiz: <neden>"
    _signed_data: _Oge | None = None
    _tstinfo: bytes = b""

    @property
    def imza_dogru(self) -> bool:
        return self.imza == "dogrulandi"


def makbuz_coz(tsr: bytes) -> Makbuz:
    """TimeStampResp'i ayristirir. Durum 'verildi' degilse ya da bicim bozuksa CapaHatasi.

    Bozuk bir dosya baska bir hata turuyle (IndexError...) dogrulayiciyi
    dusurmemeli: bagimsiz inceleme (Ekim 2026) dort baytlik bir dosyayla
    hem dogrulayiciyi hem Telegram kopyalarini durdurdu.
    """
    try:
        return _makbuz_coz(tsr)
    except CapaHatasi:
        raise
    except Exception as e:
        raise CapaHatasi(f"makbuz biçimi bozuk ({e.__class__.__name__})") from e


def _makbuz_coz(tsr: bytes) -> Makbuz:
    resp = _beklenen(_tek(tsr), 0x30, "TimeStampResp").cocuklar()
    if not resp:
        raise CapaHatasi("bos yanit")
    durum = _beklenen(resp[0], 0x30, "PKIStatusInfo").cocuklar()
    kod = _tamsayi(durum[0])
    if kod not in (0, 1):
        raise CapaHatasi(f"TSA reddetti (durum {kod})")
    if len(resp) < 2:
        raise CapaHatasi("yanitta makbuz yok")
    ci = _beklenen(resp[1], 0x30, "ContentInfo").cocuklar()
    if _oid_coz(ci[0]) != OID_SIGNED_DATA:
        raise CapaHatasi("makbuz SignedData degil")
    sd = _beklenen(_tek(_beklenen(ci[1], 0xA0, "[0]").deger), 0x30, "SignedData")
    sdc = sd.cocuklar()
    encap = _beklenen(sdc[2], 0x30, "EncapsulatedContentInfo").cocuklar()
    if _oid_coz(encap[0]) != OID_TSTINFO:
        raise CapaHatasi("icerik TSTInfo degil")
    econtent = _beklenen(_tek(_beklenen(encap[1], 0xA0, "[0]").deger), 0x04, "OCTET STRING").deger
    tst = _beklenen(_tek(econtent), 0x30, "TSTInfo").cocuklar()
    if _tamsayi(tst[0]) != 1:
        raise CapaHatasi("TSTInfo surumu 1 degil")
    mi = _beklenen(tst[2], 0x30, "MessageImprint").cocuklar()
    alg_oid = _oid_coz(mi[0].cocuklar()[0])
    imprint = _beklenen(mi[1], 0x04, "OCTET STRING").deger
    seri = _tamsayi(tst[3])
    zaman = _zaman_coz(tst[4])
    nonce = None
    for o in tst[5:]:
        if o.etiket == 0x02:
            nonce = _tamsayi(o)
    return Makbuz(zaman, seri, _OZET_ALGORITMALARI.get(alg_oid, alg_oid), imprint,
                  nonce, _signed_data=sd, _tstinfo=econtent)


def _sertifikalar(dizin):
    """(tsa, kok) -- cryptography x509 nesneleri; dosya yoksa None."""
    from cryptography import x509
    dizin = Path(dizin)
    tsa = kok = None
    if (dizin / "tsa.crt").exists():
        tsa = x509.load_pem_x509_certificate((dizin / "tsa.crt").read_bytes())
    if (dizin / "cacert.pem").exists():
        kok = x509.load_pem_x509_certificate((dizin / "cacert.pem").read_bytes())
    return tsa, kok


def imzayi_dogrula(m: Makbuz, sertifika_dizini) -> str:
    """Makbuzun imzasini depodaki TSA sertifikasiyla dogrular; sonucu m.imza'ya yazar."""
    try:
        m.imza = _imza_sonucu(m, sertifika_dizini)
    except Exception as e:      # bozuk imza yapisi: bulgu, cokme degil
        m.imza = f"gecersiz: imza yapısı bozuk ({e.__class__.__name__})"
    return m.imza


def _imza_sonucu(m: Makbuz, sertifika_dizini) -> str:
    if sertifika_dizini is None or not (Path(sertifika_dizini) / "tsa.crt").exists():
        return "dogrulanmadi: TSA sertifikası yok"
    try:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    except ImportError:
        return "dogrulanmadi: cryptography yok"
    try:
        tsa, kok = _sertifikalar(sertifika_dizini)
    except Exception as e:
        return f"dogrulanmadi: sertifika okunamadı ({e.__class__.__name__})"

    sdc = m._signed_data.cocuklar()
    gomulu = []
    signer_infos = None
    for o in sdc[3:]:
        if o.etiket == 0xA0:
            gomulu = [x.ham for x in o.cocuklar()]
        elif o.etiket == 0x31:
            signer_infos = o.cocuklar()
    if not signer_infos or len(signer_infos) != 1:
        return "gecersiz: tek bir imzacı bekleniyordu"
    si = signer_infos[0].cocuklar()
    tsa_der = tsa.public_bytes(serialization.Encoding.DER)
    if gomulu and tsa_der not in gomulu:
        return "gecersiz: makbuzu depodaki TSA sertifikası imzalamamış"
    sid = si[1]
    if sid.etiket == 0x30:
        ihrac, seri = sid.cocuklar()
        if (_tamsayi(seri) != tsa.serial_number
                or ihrac.ham != tsa.issuer.public_bytes()):
            return "gecersiz: imzacı depodaki TSA sertifikası değil"
    ozet_oid = _oid_coz(si[2].cocuklar()[0])
    ozet_adi = _OZET_ALGORITMALARI.get(ozet_oid)
    if ozet_adi is None:
        return f"gecersiz: bilinmeyen özet algoritması {ozet_oid}"
    i = 3
    if si[i].etiket != 0xA0:
        return "gecersiz: imzalı öznitelik yok"
    attrs_oge = si[i]
    i += 1
    imza_oid = _oid_coz(si[i].cocuklar()[0])
    imza = _beklenen(si[i + 1], 0x04, "OCTET STRING").deger

    icerik_turu = mesaj_ozeti = None
    for a in attrs_oge.cocuklar():
        ac = a.cocuklar()
        oid, degerler = _oid_coz(ac[0]), ac[1].cocuklar()
        if oid == OID_CONTENT_TYPE:
            icerik_turu = _oid_coz(degerler[0])
        elif oid == OID_MESSAGE_DIGEST:
            mesaj_ozeti = _beklenen(degerler[0], 0x04, "OCTET STRING").deger
    if icerik_turu != OID_TSTINFO:
        return "gecersiz: imzalı içerik türü TSTInfo değil"
    if mesaj_ozeti != hashlib.new(ozet_adi, m._tstinfo).digest():
        return "gecersiz: imza, makbuzun içeriğini kapsamıyor"

    imzali = b"\x31" + attrs_oge.ham[1:]       # [0] IMPLICIT -> SET OF
    tur_ozet = _IMZA_ALGORITMALARI.get(imza_oid)
    if tur_ozet is None:
        return f"gecersiz: desteklenmeyen imza algoritması {imza_oid}"
    tur, imza_ozeti = tur_ozet
    h = {"sha1": hashes.SHA1, "sha256": hashes.SHA256, "sha384": hashes.SHA384,
         "sha512": hashes.SHA512}[imza_ozeti or ozet_adi]()
    anahtar = tsa.public_key()
    try:
        if tur == "ec" and isinstance(anahtar, ec.EllipticCurvePublicKey):
            anahtar.verify(imza, imzali, ec.ECDSA(h))
        elif tur == "rsa" and isinstance(anahtar, rsa.RSAPublicKey):
            anahtar.verify(imza, imzali, padding.PKCS1v15(), h)
        else:
            return "gecersiz: imza algoritması sertifikanın anahtarına uymuyor"
    except InvalidSignature:
        return "gecersiz: imza tutmuyor"

    if not (tsa.not_valid_before_utc <= m.zaman <= tsa.not_valid_after_utc):
        return "gecersiz: makbuz zamanı TSA sertifikasının geçerlilik süresi dışında"
    try:
        eku = tsa.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        if x509.oid.ExtendedKeyUsageOID.TIME_STAMPING not in eku:
            return "gecersiz: sertifika zaman damgası için değil"
    except x509.ExtensionNotFound:
        return "gecersiz: sertifikada kullanım amacı yok"
    if kok is not None:
        try:
            tsa.verify_directly_issued_by(kok)
        except Exception:
            return "gecersiz: TSA sertifikası depodaki kök sertifikadan gelmiyor"
    return "dogrulandi"


def _ozetle(m: Makbuz, metin: bytes) -> bool:
    if m.imprint_alg not in ("sha256", "sha384", "sha512"):
        return False
    return hashlib.new(m.imprint_alg, metin).digest() == m.imprint


# ── Damgalama ────────────────────────────────────────────────────────────────

def _http_gonder(url: str, veri: bytes, zaman_asimi: float) -> bytes:
    istek = urllib.request.Request(
        url, data=veri, method="POST",
        headers={"Content-Type": "application/timestamp-query",
                 "Accept": "application/timestamp-reply"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        govde = yanit.read(_EN_FAZLA_YANIT + 1)
    if len(govde) > _EN_FAZLA_YANIT:
        raise CapaHatasi("TSA yanıtı çok büyük")
    return govde


def damgala(url: str, sira: int, ozet: str, sertifika_dizini=None,
            zaman_asimi: float = 20.0, gonder=None) -> tuple[str, bytes, Makbuz]:
    """(dosya adi, makbuz baytlari, Makbuz). Gecersiz makbuz SAKLANMAZ: CapaHatasi.

    Sertifika depoda varsa imza hemen dogrulanir; tutmazsa makbuz reddedilir.
    Yoksa makbuz yine kabul edilir (ozet ve nonce kontrol edilerek) ve
    imzasi 'dogrulanmadi' olarak kalir.
    """
    metin = capa_metni(sira, ozet)
    nonce = secrets.randbits(63) | 1
    istek = istek_olustur(hashlib.sha256(metin).digest(), nonce)
    try:
        tsr = (gonder or _http_gonder)(url, istek, zaman_asimi)
    except CapaHatasi:
        raise
    except Exception as e:
        raise CapaHatasi(f"TSA'ya ulaşılamadı: {' '.join(str(e).split())[:160]}") from e
    m = makbuz_coz(tsr)
    if m.imprint_alg != "sha256" or m.imprint != hashlib.sha256(metin).digest():
        raise CapaHatasi("makbuz başka bir özeti damgalamış")
    if m.nonce != nonce:
        raise CapaHatasi("makbuzun nonce değeri isteğinkiyle uyuşmuyor")
    sonuc = imzayi_dogrula(m, sertifika_dizini)
    if sonuc.startswith("gecersiz"):
        raise CapaHatasi(f"makbuz reddedildi: {sonuc}")
    return makbuz_adi(sira, ozet), tsr, m


def kaydet(dizin, ad: str, tsr: bytes) -> Path:
    """Makbuzu atomik yazar. Var olan bir makbuzun USTUNE YAZMAZ."""
    dizin = Path(dizin)
    dizin.mkdir(parents=True, exist_ok=True)
    hedef = dizin / ad
    if hedef.exists():
        if hedef.read_bytes() == tsr:
            return hedef
        raise CapaHatasi(f"{ad} zaten var; üstüne yazılmaz")
    gecici = dizin / f".{ad}.{secrets.token_hex(4)}.tmp"
    with open(gecici, "wb") as f:
        f.write(tsr)
        f.flush()
        os.fsync(f.fileno())
    os.replace(gecici, hedef)   # ayni dosya sistemi: atomik
    return hedef




# ── Zincirle karsilastirma ──────────────────────────────────────────────────
#
# Bagimsiz inceleme (Ekim 2026) ilk surumu uc yoldan kirdi; uc kural:
#
#   1) Bir capa yalnizca halkanin OZET ALANIYLA degil, halkanin KENDISIYLE
#      karsilastirilir: ozet(onceki ozet, govde) yeniden hesaplanir. Govdesi
#      degistirilip ozet alani birakilan satir boylece capada da kirik cikar.
#   2) Capalanmis bir halka artik bulunamiyorsa bu "bilgi" degil: dosyanin
#      ortasindan gitmisse BULGU, dosyalarin basindan gitmisse UYARI (sahte
#      bir rotasyon kaydiyla gercek rotasyon ayni gorunur; ikisini ayiran
#      yalnizca tanik ya da insandir). Uyari varken "tutuyor" denmez.
#   3) Onay anahtarsizdir. Capalandiktan SONRA bozulmus bir halkayi onaylayan
#      bir onay (onayin sirasi capanin sirasindan buyuk) uyari olarak
#      gosterilir: "bu onayi sen mi verdin?"

@dataclass
class Capa:
    sira: int
    ozet: str
    dosya: str
    makbuz: Makbuz | None = None
    hata: str | None = None


@dataclass
class CapaRaporu:
    capalar: list = field(default_factory=list)      # gecerli Capa'lar, siraya gore
    sorunlar: list = field(default_factory=list)     # (sira, aciklama) -- BULGU
    uyarilar: list = field(default_factory=list)     # aciklama -- "tutuyor" denmez
    bilgiler: list = field(default_factory=list)
    hesaplanamayan: list = field(default_factory=list)   # yeniden hesaplanamayan capali halkalar
    imzasi_dogrulanan: int = 0
    zincir_son_sira: int = 0

    @property
    def son(self) -> Capa | None:
        return self.capalar[-1] if self.capalar else None

    @property
    def saglam(self) -> bool:
        return not self.sorunlar

    @property
    def capasiz_halka(self) -> int:
        son = self.son
        return max(0, self.zincir_son_sira - (son.sira if son else 0))


def makbuzlari_oku(dizin) -> list:
    """Dizindeki (alt klasorler dahil) makbuzlar, siraya gore.

    Telegram'dan indirilen kopyalar "capa-...(1).tsr" adini alabilir ve
    klasorlere dagilabilir: sessizce atlanmasinlar.
    """
    dizin = Path(dizin)
    if not dizin.is_dir():
        return []
    capalar = []
    for p in sorted(dizin.rglob("capa-*.tsr")):
        m = MAKBUZ_ADI.match(p.name)
        if m and p.is_file():
            capalar.append(Capa(int(m.group("sira")), m.group("ozet"),
                                str(p.relative_to(dizin))))
    capalar.sort(key=lambda c: (c.sira, c.dosya))
    return capalar


_SATIR_ZAMANI = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _satir_zamani(govde: str):
    m = _SATIR_ZAMANI.match(govde or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# Olagan isleyiste dogmayan, yalnizca bir mudahaleyle olusan bulgu turleri.
# Yarim satir (cokme), zincirsiz satir ve yazicinin kendi kaydettigi dis
# mudahale meşru bir onaydan sonra da gorulebilir: onlar sorgulanmaz. Ikinci
# inceleme (Ekim 2026): hepsi sorgulaninca her gercek onay kalici bir uyari
# birakiyordu -- uyariya alisan sahip, gercek saldiriyi da gormezden gelir.
_MUDAHALE_TURLERI = {"degistirilmis", "eksik", "eklenmis"}


def onayli_bulgular(dosya_raporu) -> list:
    """[(bulgu sirasi, onu onaylayan ilk onayin sirasi)] -- audit_chain.Rapor'dan.

    Yalnizca icerik degisikligi turleri (degistirilmis/eksik/eklenmis).
    """
    sonuc = []
    for x in getattr(dosya_raporu, "onaylanan", []):
        if getattr(x, "tur", None) not in _MUDAHALE_TURLERI:
            continue
        sira = x.sira if x.sira is not None else (x.sonra or 0)
        onaylar = [o[0] for o in dosya_raporu.onaylar if x.kimlik in o[3]]
        if onaylar:
            sonuc.append((sira, min(onaylar)))
    return sonuc


def capalari_dogrula(dizinler, dosya_halkalari, tanik_halkalari=None,
                     sertifika_dizini=None, simdi: datetime | None = None,
                     aralik_sn: int | None = None, imza_sayisi: int | None = None,
                     zincir_son_sira: int | None = None, govdeler=None,
                     onaylar=None) -> CapaRaporu:
    """Makbuzlari zincirin iki kopyasiyla karsilastirir.

    dizinler        : makbuz klasoru ya da klasorler (botun klasoru + sahibin
                      Telegram'dan indirdigi kopyalar). Ayni icerik iki kez sayilmaz.
    dosya_halkalari : {sira: ozet alani} -- denetim dosyalarindan
    govdeler        : {sira: govde} -- verilirse capalanan halka yeniden hesaplanir
    tanik_halkalari : {sira: ozet} -- veritabanindan (yoksa None)
    onaylar         : onayli_bulgular() ciktisi -- capadan sonra verilen onaylar
    imza_sayisi     : yalnizca son N makbuzun imzasi dogrulanir (None = hepsi).
                      Ozet ve zaman HER makbuzda kontrol edilir.
    """
    if isinstance(dizinler, (str, Path)):
        dizinler = [dizinler]
    simdi = simdi or datetime.now(timezone.utc)
    govdeler = govdeler or {}
    r = CapaRaporu()
    r.zincir_son_sira = (zincir_son_sira if zincir_son_sira is not None
                         else max(dosya_halkalari, default=0))

    adaylar, goruldu = [], set()
    for d in dizinler:
        for c in makbuzlari_oku(d):
            c.dosya = str(Path(d) / c.dosya)
            try:
                ham = Path(c.dosya).read_bytes()
            except OSError as e:
                r.sorunlar.append((c.sira, f"çapa {c.sira}: makbuz okunamadı ({e.__class__.__name__})"))
                continue
            anahtar = (c.sira, c.ozet, hashlib.sha256(ham).digest())
            if anahtar in goruldu:
                continue
            goruldu.add(anahtar)
            adaylar.append((c, ham))
    adaylar.sort(key=lambda x: (x[0].sira, x[0].ozet))
    imzalanacak = set(range(len(adaylar)) if imza_sayisi is None
                      else range(max(0, len(adaylar) - imza_sayisi), len(adaylar)))

    for i, (c, ham) in enumerate(adaylar):
        try:
            c.makbuz = makbuz_coz(ham)
            dogru_ozet = _ozetle(c.makbuz, capa_metni(c.sira, c.ozet))
        except (CapaHatasi, ValueError) as e:
            r.sorunlar.append((c.sira, f"çapa {c.sira}: makbuz geçersiz ({e})"))
            continue
        if not dogru_ozet:
            r.sorunlar.append((c.sira, f"çapa {c.sira}: makbuz bu sıra ve özeti damgalamamış "
                                       f"(dosya adı değiştirilmiş olabilir)"))
            continue
        if i in imzalanacak:
            sonuc = imzayi_dogrula(c.makbuz, sertifika_dizini)
            if sonuc == "dogrulandi":
                r.imzasi_dogrulanan += 1
            elif sonuc.startswith("gecersiz"):
                r.sorunlar.append((c.sira, f"çapa {c.sira}: {sonuc}"))
                continue
        r.capalar.append(c)

    # Ayni siraya iki farkli capa: zincir yeniden yazilip yeniden capalanmis.
    sira_ozet = {}
    for c in r.capalar:
        sira_ozet.setdefault(c.sira, set()).add(c.ozet)
    for sira, ozetler in sorted(sira_ozet.items()):
        if len(ozetler) > 1:
            r.sorunlar.append((sira, f"sıra {sira} için iki farklı çapa var: zincir çapalandıktan "
                                     f"sonra yeniden yazılmış"))

    # Zaman sirasi: TSA'nin saati guvenilir; daha buyuk sira daha erken
    # damgalanmis olamaz -- olmussa sonradan kurulmus bir zincirin capasidir.
    onceki = None
    for c in r.capalar:
        if onceki is not None and c.sira > onceki.sira and c.makbuz.zaman < onceki.makbuz.zaman:
            r.sorunlar.append((c.sira, f"çapa {c.sira}, daha küçük sıralı çapa {onceki.sira}'den "
                                       f"önce damgalanmış"))
        onceki = c

    ilk_dosya = min(dosya_halkalari, default=None)
    gec_kalan = []
    for c in r.capalar:
        zaman = f"{c.makbuz.zaman:%Y-%m-%d %H:%M} UTC"
        if c.sira in dosya_halkalari:
            alan = dosya_halkalari[c.sira]
            hesap = None
            if c.sira in govdeler:
                onceki_oz = (dosya_halkalari.get(c.sira - 1) if c.sira > 1
                             else "0" * 32)
                if onceki_oz is not None:
                    hesap = _zincir_ozeti(onceki_oz, govdeler[c.sira])
                else:
                    # Dosyanin ilk halkasi: oncekisi rotasyonla gitmis. Yalnizca
                    # ozet alani karsilastirilabildi; "yeniden yazilmamis" denmez.
                    r.hesaplanamayan.append(c.sira)
            if alan != c.ozet or (hesap is not None and hesap != c.ozet):
                r.sorunlar.append((c.sira, f"sıra {c.sira} çapalandıktan sonra dosyada yeniden "
                                           f"yazılmış (çapa {zaman})"))
            lz = _satir_zamani(govdeler.get(c.sira))
            if lz is not None:
                fark = c.makbuz.zaman.replace(tzinfo=None) - lz
                tolerans = timedelta(seconds=2 * (aralik_sn or 3600)) + timedelta(hours=15)
                if fark > tolerans or fark < -timedelta(hours=15):
                    gec_kalan.append((c.sira, fark))
        elif c.sira > r.zincir_son_sira:
            r.sorunlar.append((c.sira, f"zincir çapanın gerisinde: sıra {c.sira} çapalanmış, dosya "
                                       f"{r.zincir_son_sira}'de bitiyor (sonu kesilmiş)"))
        elif ilk_dosya is not None and c.sira >= ilk_dosya:
            r.sorunlar.append((c.sira, f"çapalanmış sıra {c.sira} dosyada yok (silinmiş)"))
        elif tanik_halkalari is not None and c.sira in tanik_halkalari:
            pass                                    # asagida tanikla karsilastirilir
        else:
            r.uyarilar.append(f"çapa {c.sira} ({zaman}) karşılaştırılamadı: halka dosyalarda "
                              f"yok. Rotasyonla gitmiş olabilir; çapa yeniyse bu beklenmez")
        if tanik_halkalari is not None and c.sira in tanik_halkalari and tanik_halkalari[c.sira] != c.ozet:
            r.sorunlar.append((c.sira, f"sıra {c.sira} çapalandıktan sonra tanıkta yeniden yazılmış"))
    if gec_kalan:
        s, fark = max(gec_kalan, key=lambda x: abs(x[1]))
        r.uyarilar.append(f"{len(gec_kalan)} çapa halkasından çok sonra damgalanmış (en çok: sıra "
                          f"{s}, {abs(fark.total_seconds()) / 3600:.0f} saat). Zincir sonradan "
                          f"yeniden yazılıp yeniden çapalanmış olabilir")

    # Capalandiktan SONRA bozulmus bir halkayi onaylayan onay.
    for bulgu, onay in (onaylar or []):
        kapsayan = [c.sira for c in r.capalar if bulgu <= c.sira < onay]
        if kapsayan:
            r.uyarilar.append(f"sıra {bulgu}'deki bulgu, çapalandıktan (sıra {min(kapsayan)}) sonra "
                              f"sıra {onay}'deki bir onayla onaylanmış. Bu onayı sen verdin mi? "
                              f"Onay anahtarsızdır")

    son = r.son
    if son is None:
        if r.zincir_son_sira:
            r.uyarilar.append("hiç çapa yok: zincirin hiçbir halkası makine dışında kayıtlı değil")
    elif aralik_sn and r.capasiz_halka:
        gecen = simdi - son.makbuz.zaman
        if gecen > timedelta(seconds=2 * aralik_sn):
            saat = gecen.total_seconds() / 3600
            r.uyarilar.append(f"çapa gecikti: son çapa {saat:.1f} saat önce, ondan sonra "
                              f"{r.capasiz_halka} halka çapasız")
    return r


def _zincir_ozeti(onceki: str, govde: str) -> str:
    # audit_chain.ozet ile ayni: dogrulayici onu cagirmak yerine kendisi hesaplar.
    return hashlib.sha256(f"{onceki}\n{govde}".encode("utf-8")).hexdigest()[:32]


def ozet_satiri(r: CapaRaporu, simdi: datetime | None = None) -> str:
    simdi = simdi or datetime.now(timezone.utc)
    son = r.son
    if r.sorunlar:
        return f"çapa tutmuyor: {len(r.sorunlar)} bulgu"
    if son is None:
        return "çapa yok"
    dk = int((simdi - son.makbuz.zaman).total_seconds() // 60)
    zaman = f"{dk} dk önce" if dk < 120 else f"{dk // 60} saat önce"
    imza = (f"{r.imzasi_dogrulanan} imza doğrulandı" if r.imzasi_dogrulanan
            else "imza doğrulanmadı")
    return (f"çapalı: sıra ≤ {son.sira} ({zaman}) · {len(r.capalar)} çapa · {imza}"
            + (f" · {r.capasiz_halka} halka çapasız" if r.capasiz_halka else ""))


def rapor_metni(r: CapaRaporu) -> str:
    satirlar = ["⚓ Makine dışı çapa (RFC 3161 zaman damgası)"]
    satirlar.append("   " + ozet_satiri(r))
    son = r.son
    if son is not None:
        satirlar.append(f"   Son çapa: sıra {son.sira} · {son.makbuz.zaman:%Y-%m-%d %H:%M:%S} UTC · "
                        f"makbuz no {son.makbuz.seri}")
    for _, s in r.sorunlar[:20]:
        satirlar.append(f"🔴 {s}")
    if len(r.sorunlar) > 20:
        satirlar.append(f"   … ve {len(r.sorunlar) - 20} bulgu daha")
    for u in r.uyarilar[:10]:
        satirlar.append(f"⚠️ {u}")
    for b in r.bilgiler[:5]:
        satirlar.append(f"ℹ️ {b}")
    if r.hesaplanamayan:
        satirlar.append(f"ℹ️ çapa {', '.join(map(str, r.hesaplanamayan))}: dosyanın ilk halkası, "
                        f"yalnızca özet alanı karşılaştırıldı (gövdeye zincir doğrulaması bakar)")
    if not r.sorunlar and not r.uyarilar and not r.hesaplanamayan and son is not None:
        satirlar.append(f"✅ Çapalanmış {son.sira} halka sonradan yeniden yazılmamış.")
    return "\n".join(satirlar)


def sertifika_parmak_izi(dizin) -> str | None:
    p = Path(dizin) / "tsa.crt"
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ── Komut satiri ─────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    """python3 capa.py <denetim.log> --capa <klasor> [--capa <kopyalar>] --sertifika <klasor>

    Cikis: 0 capalar ve zincir tutuyor · 1 bulgu (capa ya da zincir) ·
    2 kullanim/okuma hatasi · 3 bulgu yok ama uyari var ("tutuyor" denmez).

    --sertifika: TSA sertifikasini BU MAKINEDEN degil, GitHub'daki depodan ya
    da kendi bilgisayarindan ver. Makineyi ele geciren biri oradaki
    sertifikayi kendi sahte TSA'sininkiyle degistirebilir. Kullanilan
    sertifikanin parmak izi ekrana yazilir: freetsa.org'dakiyle karsilastir.
    """
    import argparse

    import audit_chain

    p = argparse.ArgumentParser(description="Denetim zincirini makine dışı çapalarla karşılaştırır.")
    p.add_argument("denetim", help="denetim.log (döndürülmüş yedekler kendiliğinden okunur)")
    p.add_argument("--capa", action="append", required=True,
                   help="makbuz klasörü; Telegram'dan indirdiğin kopyalar için tekrar ver")
    p.add_argument("--sertifika", default=str(Path(__file__).resolve().parent / "scripts" / "capa" / "freetsa"),
                   help="TSA sertifika klasörü (tsa.crt, cacert.pem) -- GitHub'daki kopyadan")
    p.add_argument("--aralik-sn", type=int, default=3600)
    a = p.parse_args(argv)
    try:
        dosya_r = audit_chain.dogrula_dosyalar(audit_chain.dosyalari_sirala(a.denetim))
        halkalar = {sira: oz for sira, oz, _k, _g in dosya_r.halkalar}
        govdeler = {sira: g for sira, _o, _k, g in dosya_r.halkalar}
        r = capalari_dogrula(a.capa, halkalar, sertifika_dizini=a.sertifika,
                             zincir_son_sira=dosya_r.son_sira, govdeler=govdeler,
                             onaylar=onayli_bulgular(dosya_r), aralik_sn=a.aralik_sn)
    except Exception as e:
        print(f"❌ Doğrulanamadı: {e.__class__.__name__}: {e}")
        return 2
    print(rapor_metni(r))
    pi = sertifika_parmak_izi(a.sertifika)
    print(f"   TSA sertifikası: {a.sertifika}/tsa.crt · SHA-256 {pi or 'YOK'}")
    if not dosya_r.saglam:
        print(f"🔴 Zincirin kendisi kırık: {audit_chain.ozet_satiri(dosya_r)} "
              f"(python3 audit_chain.py {a.denetim})")
        return 1
    if dosya_r.onaylanan:
        print(f"ℹ️ Zincirde {len(dosya_r.onaylanan)} onaylı bulgu var; onaylar anahtarsızdır.")
    if not r.saglam:
        return 1
    return 3 if r.uyarilar else 0


if __name__ == "__main__":
    sys.exit(main())
