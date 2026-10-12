"""Synthetic bank-statement fixture and independent PDF redaction judge.

All people and transactions here are invented.  Public sample statements
inform the layout; no customer statement is copied into the benchmark.
"""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
import subprocess
import tempfile


@dataclass(frozen=True)
class Transaction:
    key: str
    date: str
    description: str
    amount: str
    balance: str
    sender: str = ''


ROWS = (
    Transaction('TX-01', '02/09/2026', 'Faster Payment from Amina El-Sayed / rent',
                '+1,250.00', '3,410.45', 'Amina El-Sayed'),
    Transaction('TX-02', '02/09/2026', 'Card payment to Olivia Price / books',
                '-25.00', '3,385.45'),
    Transaction('TX-03', '03/09/2026', 'Transfer from Jo Park / invoice 17',
                '+25.00', '3,410.45', 'Jo Park'),
    Transaction('TX-04', '03/09/2026', 'Refund from Northside Books Ltd',
                '+25.00', '3,435.45'),
    Transaction('TX-05', '05/09/2026', 'Faster Payment from Leo Martin / gift',
                '+110.07', '3,545.52', 'Leo Martin'),
    Transaction('TX-06', '07/09/2026', 'Standing order to Jo Park / utilities',
                '-110.07', '3,435.45'),
    Transaction('TX-07', '10/09/2026', 'Transfer from Amina El-Sayed / September',
                '+310.00', '3,745.45', 'Amina El-Sayed'),
    Transaction('TX-08', '11/09/2026', 'Interest credited',
                '+0.42', '3,745.87'),
)


def render(path, rows=ROWS, mode='original'):
    """Build an accessible PDF; `overlay` is a deliberately unsafe control."""
    from reportlab.pdfgen import canvas

    target = Path(path)
    pdf = canvas.Canvas(str(target), pagesize=(595, 842))
    pdf.setTitle('RigMark synthetic current-account statement')
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(48, 790, 'Current account statement - example only')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(48, 771, 'Fictional data. Statement period: 01/09/2026 - 30/09/2026')
    pdf.drawString(48, 749, 'Reference     Date          Transaction                                      Amount        Balance')
    for index, row in enumerate(rows):
        y = 728 - index * 34
        pdf.setFont('Helvetica', 10)
        pdf.drawString(48, y, row.key)
        pdf.drawString(105, y, row.date)
        description = row.description
        if mode in ('redacted', 'over_redacted', 'missing_amount') and row.sender:
            description = description.replace(row.sender, '[REDACTED]', 1)
        if mode == 'over_redacted':
            description = '[REDACTED]'
        pdf.drawString(174, y, description)
        pdf.drawRightString(515, y, '' if mode == 'missing_amount' else row.amount)
        pdf.drawRightString(575, y, row.balance)
        if mode == 'overlay' and row.sender:
            prefix = row.description.split(row.sender, 1)[0]
            pdf.setFillColorRGB(0, 0, 0)
            pdf.rect(174 + pdf.stringWidth(prefix, 'Helvetica', 10), y - 2,
                     pdf.stringWidth(row.sender, 'Helvetica', 10), 12,
                     fill=1, stroke=0)
            pdf.setFillColorRGB(0, 0, 0)
    pdf.save()
    return target


def _text(path):
    return subprocess.check_output(['pdftotext', '-layout', str(path), '-'],
                                   text=True, timeout=15)


def _flat(text):
    return re.sub(r'\s+', ' ', text).casefold().strip()


def _letters(text):
    return re.sub(r'[^a-z0-9]', '', text.casefold())


def judge(path, rows=ROWS):
    """Check preserved transaction data and absence of recoverable names."""
    path = Path(path)
    try:
        text = _text(path)
    except (OSError, subprocess.SubprocessError):
        return {'valid_pdf': False}
    flat = _flat(text)
    pieces = re.split(r'(?=TX-\d\d\b)', text)
    by_key = {}
    for piece in pieces:
        match = re.match(r'(TX-\d\d)\b', piece)
        if match:
            by_key.setdefault(match.group(1), []).append(_flat(piece))
    counts_ok = set(by_key) == {r.key for r in rows} and all(
        len(by_key.get(r.key, [])) == 1 for r in rows)
    values_ok = counts_ok and all(
        all(_flat(value) in by_key[row.key][0]
            for value in (row.date, row.amount, row.balance))
        for row in rows)
    unchanged_text = counts_ok and all(
        all(_flat(part) in by_key[row.key][0]
            for part in (row.description.split(row.sender, 1) if row.sender
                         else (row.description,)))
        for row in rows)
    no_extractable_names = all(
        _flat(row.sender) not in by_key[row.key][0]
        for row in rows if row.sender) if counts_ok else False
    # The source PDF is text based.  OCR is a second independent check against
    # a candidate that rasterises the page or leaves visible text behind.
    try:
        with tempfile.TemporaryDirectory(prefix='rigmark-bank-ocr-') as d:
            image = Path(d) / 'page'
            subprocess.run(['pdftoppm', '-f', '1', '-l', '1', '-r', '180',
                            '-png', '-singlefile', str(path), str(image)],
                           check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
            ocr = subprocess.check_output(['tesseract', str(image) + '.png',
                                           'stdout', 'tsv'], text=True,
                                          stderr=subprocess.DEVNULL, timeout=30)
        words = []
        for line in ocr.splitlines()[1:]:
            fields = line.split('\t', 11)
            if len(fields) == 12 and fields[11].strip():
                words.append((int(fields[7]), int(fields[6]), fields[11]))
        positions = {word: y for y, x, word in words if word in {r.key for r in rows}}
        if len(positions) != len(rows):
            no_visible_names = False
        else:
            ordered = sorted((y, key) for key, y in positions.items())
            bands = {}
            for i, (top, key) in enumerate(ordered):
                end = ordered[i + 1][0] if i + 1 < len(ordered) else top + 100
                bands[key] = _letters(' '.join(
                    word for y, x, word in sorted(words)
                    if top - 3 <= y < end - 3))
            no_visible_names = all(_letters(row.sender) not in bands[row.key]
                                   for row in rows if row.sender)
    except (OSError, subprocess.SubprocessError):
        no_visible_names = False
    non_sender_name_preserved = all(
        _flat(row.description) in by_key[row.key][0]
        for row in rows if not row.sender) if counts_ok else False
    return {'valid_pdf': True, 'transaction_count': counts_ok,
            'transaction_order': [m.group(0) for m in re.finditer(r'TX-\d\d\b', text)]
                                 == [r.key for r in rows],
            'dates_amounts_balances': values_ok,
            'other_text_preserved': unchanged_text and non_sender_name_preserved,
            'no_extractable_sender_names': no_extractable_names,
            'no_visible_sender_names': no_visible_names}


def selftest():
    with tempfile.TemporaryDirectory(prefix='rigmark-bank-control-') as d:
        root = Path(d)
        good = judge(render(root / 'good.pdf', mode='redacted'))
        bad_overlay = judge(render(root / 'overlay.pdf', mode='overlay'))
        bad_original = judge(render(root / 'original.pdf'))
        bad_over_redacted = judge(render(root / 'over.pdf', mode='over_redacted'))
        bad_amount = judge(render(root / 'amount.pdf', mode='missing_amount'))
        bad_order = judge(render(root / 'order.pdf', rows=tuple(reversed(ROWS)),
                                 mode='redacted'))
    return {'reference': good, 'overlay_control': bad_overlay,
            'unredacted_control': bad_original,
            'over_redacted_control': bad_over_redacted,
            'missing_amount_control': bad_amount,
            'wrong_order_control': bad_order}
