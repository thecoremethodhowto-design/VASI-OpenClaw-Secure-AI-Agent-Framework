"""Testler icin bellekte calisan bir RFC 3161 zaman damgasi otoritesi.

Gercek TSA'ya (freeTSA) testlerden istek atilmaz. Bu sinif ayni bicimde,
GERCEKTEN imzali makbuz uretir: kendi kok ve TSA sertifikasini olusturur,
istegi okur, TSTInfo'yu imzalar. Ayristiricinin gercek bir uygulamanin
makbuzunu okuyabildigi ayrica tests/veri/capa_openssl/ altindaki OpenSSL
makbuzuyla sinaniyor.

Saldiri testleri icin ayarlanabilir: baska bir ozeti damgalamak, nonce'u
degistirmek, zamani geriye almak, baska bir anahtarla imzalamak.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import capa  # noqa: E402

_t, _oid, _int = capa._tlv, capa._oid_yaz, capa._tamsayi_yaz
_SHA256_ALG = _t(0x30, _oid(capa.OID_SHA256) + b"\x05\x00")


def _sertifika(ad, anahtar, veren_ad, veren_anahtar, ca: bool):
    simdi = datetime.now(timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ad)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, veren_ad)]))
         .public_key(anahtar.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(simdi - timedelta(days=3650))
         .not_valid_after(simdi + timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if not ca:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True)
    return b.sign(veren_anahtar, hashes.SHA256())


class SahteTSA:
    def __init__(self, ad="Sahte TSA"):
        self.kok_anahtar = ec.generate_private_key(ec.SECP256R1())
        self.kok = _sertifika(f"{ad} Kok", self.kok_anahtar, f"{ad} Kok", self.kok_anahtar, True)
        self.anahtar = ec.generate_private_key(ec.SECP256R1())
        self.sertifika = _sertifika(ad, self.anahtar, f"{ad} Kok", self.kok_anahtar, False)
        self.seri = 0
        self.istekler = []
        # Saldiri ayarlari
        self.zaman = None           # None = simdi
        self.baska_ozet = False
        self.nonce_kaydir = 0
        self.durum = 0
        self.imzalayan = None       # None = kendi anahtari

    def sertifikalari_yaz(self, dizin) -> Path:
        dizin = Path(dizin)
        dizin.mkdir(parents=True, exist_ok=True)
        (dizin / "tsa.crt").write_bytes(self.sertifika.public_bytes(serialization.Encoding.PEM))
        (dizin / "cacert.pem").write_bytes(self.kok.public_bytes(serialization.Encoding.PEM))
        return dizin

    def __call__(self, url, istek: bytes, zaman_asimi=None) -> bytes:
        """capa._http_gonder ile ayni imza: (url, istek, zaman_asimi) -> yanit."""
        self.istekler.append(istek)
        return self.yanit(istek)

    def yanit(self, istek: bytes) -> bytes:
        req = capa._tek(istek).cocuklar()
        mi = req[1]
        nonce = next((capa._tamsayi(o) for o in req[2:] if o.etiket == 0x02), None)
        if self.durum:
            return _t(0x30, _t(0x30, _int(self.durum)))
        if self.baska_ozet:
            mi_ham = _t(0x30, _SHA256_ALG + _t(0x04, hashlib.sha256(b"baska").digest()))
        else:
            mi_ham = mi.ham
        self.seri += 1
        zaman = self.zaman or datetime.now(timezone.utc)
        tst = _t(0x30, _int(1) + _oid("1.2.3.4.1") + mi_ham + _int(self.seri)
                 + _t(0x18, zaman.strftime("%Y%m%d%H%M%SZ").encode())
                 + (_int(nonce + self.nonce_kaydir) if nonce is not None else b""))
        attrs = (_t(0x30, _oid(capa.OID_CONTENT_TYPE) + _t(0x31, _oid(capa.OID_TSTINFO)))
                 + _t(0x30, _oid(capa.OID_MESSAGE_DIGEST)
                      + _t(0x31, _t(0x04, hashlib.sha256(tst).digest()))))
        imzalayan = self.imzalayan or self.anahtar
        imza = imzalayan.sign(_t(0x31, attrs), ec.ECDSA(hashes.SHA256()))
        sid = _t(0x30, self.sertifika.issuer.public_bytes() + _int(self.sertifika.serial_number))
        signer = _t(0x30, _int(1) + sid + _SHA256_ALG + _t(0xA0, attrs)
                    + _t(0x30, _oid("1.2.840.10045.4.3.2")) + _t(0x04, imza))
        sd = _t(0x30, _int(3) + _t(0x31, _SHA256_ALG)
                + _t(0x30, _oid(capa.OID_TSTINFO) + _t(0xA0, _t(0x04, tst)))
                + _t(0xA0, self.sertifika.public_bytes(serialization.Encoding.DER))
                + _t(0x31, signer))
        ci = _t(0x30, _oid(capa.OID_SIGNED_DATA) + _t(0xA0, sd))
        return _t(0x30, _t(0x30, _int(0)) + ci)
