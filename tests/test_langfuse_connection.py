"""
Tests untuk memverifikasi koneksi Langfuse berjalan sempurna (Langfuse v4+).

Mencakup:
1. Env vars tersedia dan format valid
2. Import langfuse berhasil
3. langfuse.langchain.CallbackHandler dapat diinisialisasi
4. Koneksi ke Langfuse Cloud berhasil (auth_check)
5. Trace/span dapat dibuat dan di-flush tanpa error
6. Handler terintegrasi dengan benar di main.py (_langfuse_handler tidak None)
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()


# ── 1. Env vars ──────────────────────────────────────────────────────────────

def test_langfuse_env_vars_exist():
    assert os.getenv("LANGFUSE_PUBLIC_KEY"), "LANGFUSE_PUBLIC_KEY tidak ditemukan di .env"
    assert os.getenv("LANGFUSE_SECRET_KEY"), "LANGFUSE_SECRET_KEY tidak ditemukan di .env"
    assert os.getenv("LANGFUSE_BASE_URL"), "LANGFUSE_BASE_URL tidak ditemukan di .env"


def test_langfuse_env_vars_format():
    pub = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sec = os.getenv("LANGFUSE_SECRET_KEY", "")
    url = os.getenv("LANGFUSE_BASE_URL", "")
    assert pub.startswith("pk-lf-"), f"LANGFUSE_PUBLIC_KEY format tidak valid: {pub}"
    assert sec.startswith("sk-lf-"), f"LANGFUSE_SECRET_KEY format tidak valid: {sec}"
    assert url.startswith("https://"), f"LANGFUSE_BASE_URL harus https: {url}"


# ── 2. Import ────────────────────────────────────────────────────────────────

def test_langfuse_importable():
    try:
        import langfuse
    except ImportError:
        raise AssertionError("Package 'langfuse' tidak terinstall. Jalankan: pip install langfuse")


def test_langfuse_langchain_callback_importable():
    """Langfuse v4+ menggunakan langfuse.langchain bukan langfuse.callback."""
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError as e:
        raise AssertionError(
            f"langfuse.langchain.CallbackHandler tidak dapat diimport: {e}\n"
            "Pastikan langchain terinstall: pip install langchain"
        )


# ── 3. Inisialisasi CallbackHandler ─────────────────────────────────────────

def test_langfuse_callback_handler_init():
    """Langfuse v4+: CallbackHandler hanya terima public_key, sisanya dari env vars."""
    from langfuse.langchain import CallbackHandler
    handler = CallbackHandler(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"))
    assert handler is not None


# ── 4. Auth check ke Langfuse Cloud ─────────────────────────────────────────

def test_langfuse_auth_check():
    from langfuse import Langfuse
    client = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL"),
    )
    result = client.auth_check()
    assert result is True, "Langfuse auth_check() gagal — periksa kredensial atau koneksi internet"


# ── 5. Trace/span creation & flush (Langfuse v4 API) ─────────────────────────

def test_langfuse_observation_and_flush():
    from langfuse import Langfuse
    client = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        base_url=os.getenv("LANGFUSE_BASE_URL"),
    )
    trace_id = client.create_trace_id()
    assert trace_id is not None, "Gagal membuat trace_id"

    # Langfuse v4+: gunakan as_type bukan type, trace_id tidak ada sebagai param langsung
    span = client.start_observation(
        name="test-connection-span",
        as_type="span",
        input={"query": "ping"},
    )
    assert span is not None, "Gagal membuat span"
    span.end()  # Langfuse v4: end() tidak terima output, output diset saat start_observation

    client.flush()  # pastikan semua event terkirim sebelum test selesai


# ── 6. Integrasi di main.py ──────────────────────────────────────────────────

def test_main_langfuse_handler_initialized():
    """Verifikasi bahwa _langfuse_handler di main.py tidak None saat env vars tersedia."""
    # Bersihkan cache modul agar main.py diimport ulang segar
    for mod_key in list(sys.modules.keys()):
        if mod_key in ("main",) or mod_key.startswith("src."):
            del sys.modules[mod_key]

    import main as app_main
    assert app_main._langfuse_handler is not None, (
        "_langfuse_handler di main.py adalah None — "
        "pastikan LANGFUSE_PUBLIC_KEY dan LANGFUSE_SECRET_KEY di-set di .env"
    )
