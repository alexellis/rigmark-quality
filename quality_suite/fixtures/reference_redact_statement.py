"""Known-good bank PDF implementation for control testing only."""
from pathlib import Path
import re
import subprocess
import sys

from reportlab.pdfgen import canvas


ROW = re.compile(
    r'^(TX-\d\d)\s+(\d\d/\d\d/\d{4})\s+(.+?)\s+'
    r'([+-][\d,]+\.\d\d)\s+([\d,]+\.\d\d)\s*$')
HUMAN_INBOUND = re.compile(
    r'^(Faster Payment from|Transfer from) (.+?)( / .+)$')


def redact_pdf(input_path, output_path):
    text = subprocess.check_output(
        ['pdftotext', '-layout', str(input_path), '-'], text=True)
    rows = []
    for line in text.splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        key, date, description, amount, balance = match.groups()
        sender = HUMAN_INBOUND.match(description)
        if sender and not sender.group(2).endswith((' Ltd', ' LLC', ' CIC', ' Inc')):
            description = sender.group(1) + ' [REDACTED]' + sender.group(3)
        rows.append((key, date, description, amount, balance))
    if not rows:
        raise ValueError('statement rows not found')
    pdf = canvas.Canvas(str(output_path), pagesize=(595, 842))
    pdf.setTitle('Redacted example current-account statement')
    pdf.setFont('Helvetica-Bold', 16)
    pdf.drawString(48, 790, 'Current account statement - example only')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(48, 771, 'Fictional data. Statement period: 01/09/2026 - 30/09/2026')
    pdf.drawString(48, 749, 'Reference     Date          Transaction                                      Amount        Balance')
    for index, (key, date, description, amount, balance) in enumerate(rows):
        y = 728 - index * 34
        pdf.drawString(48, y, key)
        pdf.drawString(105, y, date)
        pdf.drawString(174, y, description)
        pdf.drawRightString(515, y, amount)
        pdf.drawRightString(575, y, balance)
    pdf.save()


if __name__ == '__main__':
    redact_pdf(Path(sys.argv[1]), Path(sys.argv[2]))
