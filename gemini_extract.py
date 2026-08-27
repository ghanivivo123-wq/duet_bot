import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)
# Silence google_genai verbose AFC warnings
logging.getLogger("google_genai").setLevel(logging.ERROR)

# Initialize client
_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """Lazy initialize Gemini client."""
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in configuration.")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


SYSTEM_INSTRUCTION = """
Kamu adalah asisten OCR dan analisis bukti transaksi keuangan (QRIS dan Nota belanja fisik) di Indonesia.
Tugasmu adalah membaca gambar bukti transaksi secara teliti dan mengembalikan data terstruktur dalam format JSON.

PANDUAN EKSTRAKSI:
1. jenis_bukti:
   - "QRIS" jika merupakan screenshot/bukti pembayaran QRIS digital (GoPay, OVO, Dana, ShopeePay, BCA QR, QRIS Bank, dsb).
   - "Nota" jika merupakan struk belanja fisik, nota tulis tangan, invoice kasir, atau bill restoran.

2. nominal:
   - Nominal total pembayaran dalam bentuk angka murni (integer/float tanpa format rupiah, misal: 45000).
   - Untuk Nota: WAJIB HANYA ambil TOTAL AKHIR / GRAND TOTAL / TOTAL BAYAR. JANGAN ekstrak rincian per item belanjaan.
   - Jika ada diskon/pajak, ambil angka final yang dibayar.

3. merchant:
   - Nama toko, restoran, pedagang, atau nama penerima transfer QRIS (misal: "Indomaret", "Kopi Kenangan", "Warung Bu Siti").
   - Jika tidak terbaca atau tidak ada, berikan nilai string kosong "".

4. tanggal:
   - Tanggal transaksi dalam format "YYYY-MM-DD".
   - Jika tanggal tidak tertera pada bukti, gunakan tanggal hari ini yang disediakan di prompt.

5. waktu:
   - Waktu/jam transaksi dalam format "HH:MM" (24 jam, misal "14:35").
   - Jika tidak ada atau tidak terbaca, berikan nilai string kosong "".

6. keterangan:
   - Keterangan singkat mengenai transaksi tersebut.
   - Jika pengguna memberikan catatan/keterangan tambahan di prompt, prioritaskan dan padukan catatan pengguna dengan konteks merchant.
   - Contoh: "Beli kopi & roti", "Makan siang nasi padang", "Bensin motor".

7. kategori:
   - Kategorikan pengeluaran ini secara BEBAS dan akurat ke dalam bahasa Indonesia (TIDAK dibatasi daftar kaku).
   - Contoh: "Makanan & Minuman", "Belanja Bulanan", "Transportasi", "Kebutuhan Rumah", "Kesehatan & Obat", "Hiburan", "Tagihan & Utilitas", "Pendidikan", "Pakaian", "Elektronik", dsb.

8. confidence:
   - "high": Jika gambar jelas, nominal total dan merchant terbaca dengan sangat yakin.
   - "medium": Jika ada bagian yang agak buram tapi nominal utama masih bisa disimpulkan dengan wajar.
   - "low": Jika gambar sangat buram, terpotong, atau nominal/merchant diragukan.

FORMAT JSON OUTPUT (WAJIB VALID JSON):
{
  "jenis_bukti": "QRIS" | "Nota",
  "nominal": 50000,
  "merchant": "Nama Toko",
  "tanggal": "YYYY-MM-DD",
  "waktu": "HH:MM",
  "keterangan": "Beli sesuatu",
  "kategori": "Makanan & Minuman",
  "confidence": "high" | "medium" | "low"
}
"""


def _clean_json_string(text: str) -> str:
    """Clean markdown code blocks and whitespace from JSON response."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


from PIL import Image
import io

def _optimize_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Resize and compress image for ultra-fast upload and OCR processing."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Resize if larger than 1200px for optimal speed & accuracy
        max_dim = 1200
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=82, optimize=True)
        return out_buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"


def extract_expense_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    user_caption: str = "",
) -> Dict[str, Any]:
    """
    Extract expense data from receipt/QRIS image using Gemini.
    Optimized for high-speed response.
    """
    # Optimize image size for faster network transfer
    image_bytes, mime_type = _optimize_image(image_bytes)

    today_str = datetime.now().strftime("%Y-%m-%d")
    current_time_str = datetime.now().strftime("%H:%M")

    prompt_parts = [
        f"Konteks Waktu Saat Ini: Tanggal {today_str}, Jam {current_time_str}.\n"
    ]
    if user_caption.strip():
        prompt_parts.append(f"Catatan dari Pengguna: \"{user_caption.strip()}\"\n")
    else:
        prompt_parts.append("Catatan dari Pengguna: (tidak ada catatan tambahan)\n")

    prompt_parts.append(
        "Tolong ekstrak data transaksi dari gambar bukti pembayaran terlampir sesuai instruksi JSON."
    )
    prompt_text = "".join(prompt_parts)

    try:
        client = get_gemini_client()

        # Build GenerateContentConfig (Disable thinking budget for instant response)
        config_kwargs = {
            "response_mime_type": "application/json",
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": 0.1,
        }

        # Set thinking_budget=0 to disable thinking overhead and return output instantly
        try:
            if hasattr(types, "ThinkingConfig"):
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception as e:
            logger.debug("ThinkingConfig not set: %s", e)

        gen_config = types.GenerateContentConfig(**config_kwargs)

        # Auto-correct model name typos
        target_model = (config.GEMINI_MODEL or "gemini-3.6-flash").strip()
        if target_model.endswith("flas"):
            target_model += "h"
        if not target_model.startswith("gemini-"):
            target_model = "gemini-3.6-flash"

        # List of candidate models for fallback (ultra-fast 3.6-flash first)
        candidate_models = [target_model, "gemini-3.6-flash", "gemini-flash-latest", "gemini-3.7-flash"]
        # Deduplicate preserving order
        candidate_models = list(dict.fromkeys(candidate_models))

        response = None
        last_err = None

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type,
                        ),
                        prompt_text,
                    ],
                    config=gen_config,
                )
                if response and response.text:
                    logger.info("Berhasil ekstraksi menggunakan model: %s", model_name)
                    break
            except Exception as call_err:
                last_err = call_err
                logger.warning("Gagal memanggil model '%s': %s. Mencoba fallback...", model_name, call_err)
                continue

        if not response or not response.text:
            raise last_err or ValueError("Tidak ada respon dari Gemini API.")

        raw_text = response.text or ""
        cleaned_json = _clean_json_string(raw_text)
        
        parsed_data = json.loads(cleaned_json)

        # Validate and sanitize fields
        jenis_bukti = str(parsed_data.get("jenis_bukti", "Nota")).strip()
        if jenis_bukti.upper() in ["QRIS", "Q-RIS"]:
            jenis_bukti = "QRIS"
        else:
            jenis_bukti = "Nota"

        # Nominal sanitization
        raw_nominal = parsed_data.get("nominal")
        if raw_nominal is None:
            raise ValueError("Field 'nominal' tidak ditemukan dalam hasil ekstraksi.")
        
        if isinstance(raw_nominal, str):
            # Clean non-digit characters except dot/comma
            cleaned_num = re.sub(r"[^\d.]", "", raw_nominal.replace(",", "."))
            nominal = float(cleaned_num) if cleaned_num else 0
        else:
            nominal = float(raw_nominal)

        if nominal <= 0:
            raise ValueError("Nominal yang terdeteksi 0 atau negatif.")

        # Convert to int if whole number
        if nominal.is_integer():
            nominal = int(nominal)

        # Tanggal sanitization
        tanggal = str(parsed_data.get("tanggal", today_str)).strip()
        # Verify YYYY-MM-DD
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", tanggal):
            tanggal = today_str

        # Waktu sanitization
        waktu = str(parsed_data.get("waktu", "")).strip()
        if waktu and not re.match(r"^\d{1,2}:\d{2}$", waktu):
            waktu = ""

        merchant = str(parsed_data.get("merchant", "")).strip()
        keterangan = str(parsed_data.get("keterangan", user_caption or merchant or "Pengeluaran")).strip()
        kategori = str(parsed_data.get("kategori", "Lain-lain")).strip() or "Lain-lain"
        confidence = str(parsed_data.get("confidence", "medium")).lower().strip()
        if confidence not in ["high", "medium", "low"]:
            confidence = "medium"

        sanitized = {
            "jenis_bukti": jenis_bukti,
            "nominal": nominal,
            "merchant": merchant,
            "tanggal": tanggal,
            "waktu": waktu,
            "keterangan": keterangan,
            "kategori": kategori,
            "confidence": confidence,
        }

        return {
            "success": True,
            "data": sanitized,
            "raw_response": raw_text,
            "error": None,
        }

    except Exception as exc:
        logger.error("Gagal melakukan ekstraksi dengan Gemini: %s", exc, exc_info=True)
        return {
            "success": False,
            "data": None,
            "raw_response": getattr(locals().get("response", None), "text", ""),
            "error": str(exc),
        }
