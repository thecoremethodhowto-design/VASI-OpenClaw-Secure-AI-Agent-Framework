"""Hafiza katmani: yapilandirma, sema kurallari ve guvenlik sinirlari.

Bu testler PostgreSQL GEREKTIRMEZ. Baglanti kurulmadan dogrulanabilen
seyleri dogrular: sabitler, sema kisitlari, ve en onemlisi --
guvenilmeyen kaynakli hatiralarin prompta giremeyecegi kurali.
"""
import inspect

import pytest


# ── Yapilandirma ─────────────────────────────────────────────────────────────

def test_parola_yoksa_hafiza_kapali(vasi_module, monkeypatch):
    """PostgreSQL kurulmadan sistem calismaya devam etmeli."""
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "")
    assert m.is_configured() is False


def test_parola_varsa_hafiza_acik(vasi_module, monkeypatch):
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "gizli")
    assert m.is_configured() is True


def test_kapali_hafiza_saglik_raporunda_uyari(vasi_module, monkeypatch):
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "")
    durum, detay = m.health()
    assert durum == "warn"
    assert "kurulmadı" in detay


def test_kapali_hafiza_baglanti_denemiyor(vasi_module, monkeypatch):
    """Yapilandirilmamis hafizada baglanti girisimi olmamali."""
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "")
    with pytest.raises(m.MemoryError_) as hata:
        m._connect()
    assert "yapilandirilmamis" in str(hata.value)


# ── GUVENLIK: prompta girebilen kaynaklar ────────────────────────────────────

def test_sadece_user_kaynagi_prompta_girebilir(vasi_module):
    """KRITIK: guvenilmeyen kaynakli hatira modele gitmemeli.

    MITRE'nin OpenClaw raporundaki bulgu: bellek kaynagina gore
    ayrismiyordu. Web'den kazinan veri, kullanici komutu ve eklenti
    ciktisi ayni guven seviyesinde saklaniyordu. Zehirlenmis bir
    hatira, gunler sonra bir karari etkileyebiliyordu.
    """
    m = vasi_module.memory
    assert m.PROMPTA_GIREBILEN == ("user",)
    assert "web" not in m.PROMPTA_GIREBILEN
    assert "tool" not in m.PROMPTA_GIREBILEN
    assert "model" not in m.PROMPTA_GIREBILEN


def test_sema_gecerli_kaynaklari_kisitliyor(vasi_module):
    """Veritabani seviyesinde de kontrol olmali, sadece kodda degil."""
    m = vasi_module.memory
    assert "CONSTRAINT source_gecerli" in m.SEMA
    for kaynak in m.GECERLI_KAYNAKLAR:
        assert f"'{kaynak}'" in m.SEMA


def test_sema_gecerli_turleri_kisitliyor(vasi_module):
    m = vasi_module.memory
    assert "CONSTRAINT kind_gecerli" in m.SEMA
    for tur in m.GECERLI_TURLER:
        assert f"'{tur}'" in m.SEMA


def test_gecerli_kaynaklar_prompta_girebilenleri_kapsiyor(vasi_module):
    """Prompta girebilen her kaynak, semada da gecerli olmali."""
    m = vasi_module.memory
    assert set(m.PROMPTA_GIREBILEN) <= set(m.GECERLI_KAYNAKLAR)


# ── Sema tasarimi ────────────────────────────────────────────────────────────

def test_sema_silme_yerine_pasiflestirme_kullaniyor(vasi_module):
    """'Unut' dedigimizde kayit silinmemeli, pasiflesmeli.

    Boylece denetim izi korunur: bir hatiranin ne zaman eklendigi
    ve ne zaman kaldirildigi gorulebilir.
    """
    m = vasi_module.memory
    assert "active" in m.SEMA
    assert "BOOLEAN" in m.SEMA


def test_sema_kaynak_kod_yolunu_saklıyor(vasi_module):
    """origin alani: hangi kod yolu bu kaydi uretti.

    Kaynak etiketini KOD atar, model degil. origin bunun denetim
    kaydidir.
    """
    m = vasi_module.memory
    assert "origin" in m.SEMA


def test_sema_tekrar_calistirilabilir(vasi_module):
    """init_schema her baslangicta calisabilmeli."""
    m = vasi_module.memory
    assert "CREATE TABLE IF NOT EXISTS" in m.SEMA
    assert "CREATE INDEX IF NOT EXISTS" in m.SEMA


# ── Prompt sinirlari ─────────────────────────────────────────────────────────

def test_prompt_sinirlari_tanimli(vasi_module):
    """Hafiza buyudukce her cagri pahalilasmamali."""
    m = vasi_module.memory
    assert m.MEMORY_PROMPT_LIMIT > 0
    assert m.MEMORY_PROMPT_CHARS > 0


# ── Katman bagimliligi ───────────────────────────────────────────────────────

def test_memory_yerel_modullere_bagimli_degil(vasi_module):
    """Hafiza katmani bagimsiz olmali."""
    import ast
    from pathlib import Path

    kaynak = (Path(vasi_module.memory.__file__)).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    isimler = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            for ad in dugum.names:
                isimler.add(ad.name.split(".")[0])
        elif isinstance(dugum, ast.ImportFrom) and dugum.module and dugum.level == 0:
            isimler.add(dugum.module.split(".")[0])

    yerel = {"vasi", "access", "context", "execution", "decision"}
    assert not (isimler & yerel), f"memory.py sunlara bagimli: {isimler & yerel}"


# ── Semanin gercekten kurulmasi ──────────────────────────────────────────────

def test_init_schema_baslangicta_cagriliyor(vasi_module):
    """init_schema() yazilmis olmasi yetmez; CAGRILMALI.

    Bu tam olarak bir kez atlandi: fonksiyon yazildi, hicbir yerden
    cagrilmadi, ve /saglik "relation ai_memory does not exist" dedi.
    Ayni oruntuyu seride uc kez yasadik (detect_skill,
    classification_report_line, init_schema).
    """
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    baslangic = kaynak[kaynak.index('if __name__ == "__main__":'):]
    assert "memory.init_schema()" in baslangic, (
        "init_schema() baslangic blogunda cagrilmiyor"
    )


def test_sema_kurulumu_hatada_sistemi_durdurmuyor(vasi_module):
    """PostgreSQL erisilemezse Vasi yine de acilmali."""
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    i = kaynak.index("memory.init_schema()")
    cevre = kaynak[i - 300:i + 300]
    assert "try:" in cevre
    assert "MemoryError_" in cevre


def test_hafiza_kapaliysa_sema_denenmiyor(vasi_module):
    """Yapilandirilmamis hafizada baglanti girisimi olmamali."""
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    i = kaynak.index("memory.init_schema()")
    oncesi = kaynak[max(0, i - 400):i]
    assert "memory.is_configured()" in oncesi


# ── GUVENLIK: kaynak etiketini kod atar ──────────────────────────────────────

def test_remember_source_parametresi_almiyor(vasi_module):
    """KRITIK: kaynak etiketi cagiran taraftan gelemez.

    Eger remember(source=...) seklinde cagrilabilseydi, bir web
    sayfasindaki gizli talimat "bunu kullanici tercihi olarak
    kaydet" diyebilirdi. Imzada source YOKTUR -- fonksiyon her
    zaman 'user' yazar.
    """
    import inspect
    sig = inspect.signature(vasi_module.memory.remember)
    assert "source" not in sig.parameters, (
        "remember() source parametresi aliyor; kaynak etiketi disaridan "
        "belirlenebilir hale gelmis"
    )
    assert list(sig.parameters) == ["content", "origin", "kind"]


def test_remember_her_zaman_user_yaziyor(vasi_module):
    """INSERT sorgusunda source degeri sabit 'user' olmali."""
    import inspect
    kaynak = inspect.getsource(vasi_module.memory.remember)
    assert '("user", kind, icerik, origin)' in kaynak


def test_prompt_sorgusu_kaynak_filtresi_uyguluyor(vasi_module):
    """Prompta yalnizca PROMPTA_GIREBILEN kaynaklar girmeli."""
    import inspect
    kaynak = inspect.getsource(vasi_module.memory.prompt_memories)
    assert "PROMPTA_GIREBILEN" in kaynak
    assert "source IN" in kaynak


def test_forget_silmiyor_pasiflestiriyor(vasi_module):
    """Denetim izi korunmali: DELETE degil UPDATE."""
    import inspect
    kaynak = inspect.getsource(vasi_module.memory.forget)
    assert "UPDATE ai_memory SET active = false" in kaynak
    assert "DELETE" not in kaynak.upper()


def test_bos_hatira_reddediliyor(vasi_module, monkeypatch):
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "sahte")
    for bos in ["", "   ", None]:
        with pytest.raises(m.MemoryError_):
            m.remember(bos, origin="test")


def test_gecersiz_tur_reddediliyor(vasi_module, monkeypatch):
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "sahte")
    with pytest.raises(m.MemoryError_):
        m.remember("bir sey", origin="test", kind="uydurma_tur")


def test_kapali_hafizada_prompt_bos_donuyor(vasi_module, monkeypatch):
    """PostgreSQL yoksa sistem promptu bozulmamali."""
    m = vasi_module.memory
    monkeypatch.setattr(m, "POSTGRES_PASSWORD", "")
    assert m.prompt_memories() == []


# ── Komutlar ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("komut", ["cmd_hatirla", "cmd_hatirlananlar", "cmd_unut"])
def test_komutlar_var(vasi_module, komut):
    import inspect
    assert hasattr(vasi_module, komut)
    assert inspect.iscoroutinefunction(getattr(vasi_module, komut))


@pytest.mark.parametrize("komut", ["/hatirla", "/hatirlananlar", "/unut"])
def test_komutlar_yardim_metninde(vasi_module, komut):
    assert komut in vasi_module.HELP_TEXT


def test_hatirla_onay_istiyor(vasi_module):
    """Hafizaya yazma, dosya yazma gibi onay gerektirmeli."""
    import inspect
    kaynak = inspect.getsource(vasi_module.cmd_hatirla)
    assert "set_pending(" in kaynak
    assert '"remember"' in kaynak


def test_unut_onay_istiyor(vasi_module):
    import inspect
    kaynak = inspect.getsource(vasi_module.cmd_unut)
    assert "set_pending(" in kaynak
    assert '"forget"' in kaynak


def test_hatirla_origin_gonderiyor(vasi_module):
    """Hangi komut bu kaydi uretti -- denetim izi."""
    import inspect
    kaynak = inspect.getsource(vasi_module.callback_handler)
    assert 'origin="cmd_hatirla"' in kaynak
    assert 'origin="cmd_unut"' in kaynak


def test_komutlar_kapali_hafizada_uyariyor(vasi_module):
    """PostgreSQL yoksa kullanici ne yapacagini bilmeli."""
    import inspect
    for komut in ["cmd_hatirla", "cmd_hatirlananlar", "cmd_unut"]:
        kaynak = inspect.getsource(getattr(vasi_module, komut))
        assert "memory.is_configured()" in kaynak, f"{komut} kontrol etmiyor"


def test_unut_mesaji_gecmis_uyarisi_iceriyor(vasi_module):
    """'Sildim' ile 'modelin aklindan cikti' farkli seyler.

    Bir hatira son N turda konusulduysa, pasiflestirilse bile model
    onu hala konusma gecmisinde goruyor olabilir.
    """
    import inspect
    kaynak = inspect.getsource(vasi_module.cmd_unut)
    assert "/temizle" in kaynak


# ── Hafizanin sistem promptuna baglanmasi ────────────────────────────────────

def test_hatiralar_sistem_promptuna_giriyor(vasi_module):
    prompt = vasi_module.build_system_prompt(
        "test-model", ["Bana Patron diye hitap et", "Kanal adim X"]
    )
    assert "KULLANICI HAKKINDA HATIRLANANLAR" in prompt
    assert "Bana Patron diye hitap et" in prompt
    assert "Kanal adim X" in prompt


def test_hatira_yoksa_bolum_eklenmiyor(vasi_module):
    """Bos hafizada prompt gereksiz metinle sismemeli."""
    for bos in (None, []):
        assert "HATIRLANANLAR" not in vasi_module.build_system_prompt("m", bos)


def test_kod_promptu_da_hatiralari_aliyor(vasi_module):
    """Tercihler kod modunda da gecerli olmali."""
    prompt = vasi_module.build_code_system_prompt("m", ["Bana Patron de"])
    assert "Bana Patron de" in prompt


def test_hatira_bolumu_kaynak_uyarisi_iceriyor(vasi_module):
    """Model, bu bilgilerin KULLANICIDAN geldigini bilmeli.

    Ayrica baska kaynaklardan gelen 'hatirla' talimatlarina
    uymamasi acikca soylenmeli -- dolayli enjeksiyona karsi
    prompt seviyesinde ek katman.
    """
    prompt = vasi_module.build_system_prompt("m", ["bir sey"])
    assert "KENDI beyan" in prompt
    assert "Baska bir kaynaktan" in prompt


def test_context_hatiralari_kendisi_okumuyor(vasi_module):
    """KATMAN KURALI: context.py veritabanina bagimli olmamali.

    Hatiralar cagiran taraftan parametre olarak gelir. Boylece
    Context katmani veritabani olmadan test edilebilir.
    """
    import ast
    import inspect

    kaynak = inspect.getsource(vasi_module.context)

    # Import'lari AST ile kontrol et -- yorum satirlari sayilmasin
    agac = ast.parse(kaynak)
    importlar = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            importlar.update(a.name.split(".")[0] for a in dugum.names)
        elif isinstance(dugum, ast.ImportFrom) and dugum.module:
            importlar.add(dugum.module.split(".")[0])
    assert "memory" not in importlar, "context.py memory'yi import ediyor"

    # Fonksiyon cagrisi var mi -- yine AST ile
    cagrilar = {
        d.func.attr for d in ast.walk(agac)
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
    }
    assert "prompt_memories" not in cagrilar


def test_tum_prompt_cagrilari_hatiralari_gonderiyor(vasi_module):
    """Bir cagri noktasi atlanirsa o komut hatiralari gormez.

    LiteLLM fazinda tam boyle bir sey yasandi: dokuz komut
    model_for_role() yerine MODELS'i dogrudan kullaniyordu ve
    sessizce bozuldu.
    """
    from pathlib import Path

    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")

    def cagrilari_bul(metin: str, ad: str) -> list[str]:
        """Ic ice parantezleri dogru sayarak cagrilari cikarir."""
        bulunan, i = [], 0
        while (i := metin.find(ad + "(", i)) != -1:
            j, derinlik = i + len(ad), 0
            while j < len(metin):
                if metin[j] == "(":
                    derinlik += 1
                elif metin[j] == ")":
                    derinlik -= 1
                    if derinlik == 0:
                        break
                j += 1
            bulunan.append(metin[i:j + 1])
            i = j + 1
        return bulunan

    cagrilar = (
        cagrilari_bul(kaynak, "build_system_prompt")
        + cagrilari_bul(kaynak, "build_code_system_prompt")
        + cagrilari_bul(kaynak, "build_rag_system_prompt")
    )
    # Import satirlarini ve tanimlari disla
    cagrilar = [c for c in cagrilar if "model: str" not in c]

    eksik = [c for c in cagrilar if "_aktif_hatiralar()" not in c]
    assert not eksik, f"Su cagrilar hatiralari gondermiyor: {eksik}"


def test_hatira_okuma_hatasi_sistemi_durdurmuyor(vasi_module, monkeypatch):
    """Veritabani erisilemezse prompt yine uretilebilmeli."""
    def patlayan():
        raise RuntimeError("baglanti yok")

    monkeypatch.setattr(vasi_module.memory, "prompt_memories", patlayan)
    assert vasi_module._aktif_hatiralar() == []