from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import pdfplumber
import pandas as pd
import os
import re
from io import BytesIO
from datetime import datetime
import tempfile

app = Flask(__name__, template_folder='templates')
CORS(app)

UPLOAD_FOLDER = tempfile.gettempdir()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

transactions_store = {}

def parse_date(date_str):
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    months = {'jan': '01', 'peb': '02', 'feb': '02', 'mar': '03', 'apr': '04', 'mei': '05', 'jun': '06', 'jul': '07', 'agu': '08', 'aug': '08', 'sep': '09', 'okt': '10', 'oct': '10', 'nov': '11', 'des': '12', 'dec': '12'}
    match = re.search(r'(\d{1,2})-(\w+)-(\d{4})', date_str.lower())
    if match:
        day, month, year = match.groups()
        month_num = months.get(month[:3], '01')
        return f"{int(month_num)}/{int(day)}/{year}"
    match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
    if match:
        day, month, year = match.groups()
        return f"{int(month)}/{int(day)}/{year}"
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match:
        year, month, day = match.groups()
        return f"{int(month)}/{int(day)}/{year}"
    return date_str

def parse_number(text):
    if not text:
        return 0
    text = str(text).replace('.', '').replace(',', '').strip()
    try:
        return int(text)
    except:
        return 0

def extract_from_pdf(pdf_path):
    transactions = []
    metadata = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
            saham_match = re.search(r'(CUAN|BBRI|ASII|BMRI|PTRO|TLKM|UNTR|INDF|ADRO)', first_page_text.upper())
            metadata['saham'] = saham_match.group(1) if saham_match else 'UNKNOWN'
            name_match = re.search(r'Nama\s*\(sesuai SID\)\s*:\s*([^\n]+)', first_page_text)
            metadata['big_player'] = name_match.group(1).strip() if name_match else 'Unknown'
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    for row_idx in range(1, len(table)):
                        row = table[row_idx]
                        if not any(cell for cell in row if cell):
                            continue
                        try:
                            if len(row) >= 9:
                                transaction_type = str(row[0]).strip() if row[0] else ''
                                jumlah_saham = parse_number(row[6]) if row[6] else 0
                                harga = parse_number(row[8]) if row[8] else 0
                                tanggal = parse_date(str(row[9]) if len(row) > 9 and row[9] else '')
                                if transaction_type and jumlah_saham and harga and tanggal:
                                    trans = {
                                        'saham': metadata.get('saham', 'UNKNOWN'),
                                        'date': tanggal,
                                        'broker': 'Penjualan' if 'Penjualan' in transaction_type else 'Pembelian',
                                        'big_player': metadata.get('big_player', 'Unknown'),
                                        'jumlah_sebelum': 0,
                                        'change': -jumlah_saham if 'Penjualan' in transaction_type else jumlah_saham,
                                        'jumlah_sesudah': 0,
                                        'harga': harga
                                    }
                                    transactions.append(trans)
                        except:
                            continue
        return transactions, metadata
    except Exception as e:
        print(f"PDF Error: {e}")
        return [], metadata

def calculate_balances(transactions):
    if not transactions:
        return transactions
    transactions = sorted(transactions, key=lambda x: x['date'])
    balances = {}
    for trans in transactions:
        saham = trans['saham']
        if saham not in balances:
            balances[saham] = 50000000000
        trans['jumlah_sebelum'] = balances[saham]
        trans['jumlah_sesudah'] = balances[saham] + trans['change']
        balances[saham] = trans['jumlah_sesudah']
    return transactions

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process', methods=['POST'])
def process_pdfs():
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files'}), 400
        files = request.files.getlist('files')
        all_transactions = []
        for file in files:
            if file.filename == '' or not file.filename.endswith('.pdf'):
                continue
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(temp_path)
            transactions, meta = extract_from_pdf(temp_path)
            all_transactions.extend(transactions)
            try:
                os.remove(temp_path)
            except:
                pass
        if not all_transactions:
            return jsonify({'success': False, 'error': 'No data found'}), 400
        all_transactions = calculate_balances(all_transactions)
        transactions_store['current'] = all_transactions
        return jsonify({'success': True, 'data': all_transactions, 'count': len(all_transactions)}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/download', methods=['GET'])
def download_excel():
    try:
        if 'current' not in transactions_store:
            return jsonify({'error': 'No data'}), 400
        df = pd.DataFrame(transactions_store['current'])
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='All Transactions', index=False)
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=f'saham_merged_{datetime.now().strftime("%Y%m%d")}.xlsx')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
