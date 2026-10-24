# Çapa: TSA sertifikaları

`capa.py`, zincirin ucunu bir zaman damgası otoritesine (RFC 3161, varsayılan
[freeTSA](https://freetsa.org/)) damgalatır. Makbuzun imzası bu klasördeki
sertifikayla doğrulanır:

    freetsa/tsa.crt      imzayı atan sertifika
    freetsa/cacert.pem   onu veren kök sertifika

Bir kez indir (parmak izlerini freetsa.org'daki değerlerle karşılaştırır):

    sh scripts/capa/sertifika_indir.sh

Sertifikalar yoksa Vasi yine çapa atar, ama `/saglik` "imza doğrulanmadı"
der: makbuzun özeti ve zamanı kontrol edilir, imzası edilmez.

Neden depoda: makineyi ele geçiren biri kendi sahte TSA'sını kurup sertifikayı
değiştirebilirdi. Depodaki (GitHub'daki) kopya buna karşı durur.
