"""Regenerates the two sample PDFs in seed/knowledge (text-based and image-only/scanned).

Run: python3 seed/make_pdfs.py  — output is deterministic.
"""
from pathlib import Path

OUT = Path(__file__).parent / "knowledge"


def build_pdf(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def text_pdf(lines: list[str]) -> bytes:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    sb = stream.encode("latin-1")
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(sb)} >>\nstream\n".encode() + sb + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ])


def image_only_pdf() -> bytes:
    w = h = 64
    pixels = bytes((x * 4) % 256 for y in range(h) for x in range(w))
    content = b"q 400 0 0 400 100 300 cm /Im1 Do Q"
    return build_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8 /Length {len(pixels)} >>\nstream\n".encode()
        + pixels + b"\nendstream",
    ])


if __name__ == "__main__":
    (OUT / "community-guidelines.pdf").write_bytes(text_pdf([
        "Community Guidelines (SYNTHETIC evaluation document)",
        "1. Be kind and specific when giving feedback.",
        "2. No unsolicited direct-message selling to other members.",
        "3. Moderators may remove posts that share personal contact details publicly.",
        "4. Report spam using the post menu; moderators review reports within 24 hours.",
        "5. Members who repeatedly break guidelines receive one warning before removal.",
        "6. Automated assistant replies are labelled and may be corrected by staff.",
    ]))
    (OUT / "scanned-welcome-letter.pdf").write_bytes(image_only_pdf())
    print("pdfs written")
