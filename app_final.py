from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import pdfplumber
import pandas as pd
import os
import re
from io import BytesIO
from datetime import datetime
import tempfile

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = tempfile.gettempdir()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Data storage untuk session
transactions_store = {}

def parse_date(date_str):
    """Parse various date formats"""
    if not date_str:
        return ""
    
    date_str = str(date_str).strip()
    months = {
        'jan': '01', 'peb': '02', 'feb': '02', 'mar': '03', 'apr': '04', 'mei': '05', 'jun': '06',
        'jul': '07', 'agu': '08', 'aug': '08', 'sep': '09', 'okt': '10', 'oct': '10', 'nov': '11', 'des': '12', 'dec': '12'
    }
    
    # Try DD-MMM-YYYY format (10-Apr-2026)
    match = re.search(r'(\d{1,2})-(\w+)-(\d{4})', date_str.lower())
    if match:
        day, month, year = match.groups()
        month_num = months.get(month[:3], '01')
        return f"{month_num}/{day.lstrip('0') or '0'}/{year}"
    
    # Try DD/MM/YYYY format
    match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_str)
    if match:
        day, month, year = match.groups()
        return f"{month.lstrip('0') or '0'}/{day.lstrip('0') or '0'}/{year}"
    
    # Try YYYY-MM-DD format
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', date_str)
    if match:
        year, month, day = match.groups()
        return f"{month.lstrip('0') or '0'}/{day.lstrip('0') or '0'}/{year}"
    
    return date_str

def parse_number(text):
    """Parse number string"""
    if not text:
        return 0
    text = str(text).replace('.', '').replace(',', '').strip()
    try:
        return int(text)
    except:
        return 0

def extract_from_pdf(pdf_path):
    """Extract transactions from POJK format PDF"""
    transactions = []
    metadata = {}
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Extract metadata dari halaman pertama
            first_page_text = pdf.pages[0].extract_text()
            
            # Extract saham code
            saham_match = re.search(r'(CUAN|BBRI|ASII|BMRI|PTRO|TLKM|UNTR|INDF|ADRO)', first_page_text.upper())
            metadata['saham'] = saham_match.group(1) if saham_match else 'UNKNOWN'
            
            # Extract big player name
            name_match = re.search(r'Nama\s*\(sesuai SID\)\s*:\s*([^\n]+)', first_page_text)
            metadata['big_player'] = name_match.group(1).strip() if name_match else 'Unknown'
            
            # Extract initial balance jika ada
            balance_match = re.search(r'Jumlah Saham Sebelum Transaksi\s*:\s*([\d.,]+)', first_page_text)
            metadata['initial_balance'] = parse_number(balance_match.group(1)) if balance_match else 50000000000
            
            # Extract dari setiap page
            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                
                if not tables:
                    continue
                
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Identify transaction table
                    headers = ' '.join(str(h).lower() for h in table[0] if h)
                    if 'jumlah' not in headers and 'harga' not in headers:
                        continue
                    
                    # Process rows
                    for row_idx in range(1, len(table)):
                        row = table[row_idx]
                        
                        if not any(cell for cell in row if cell):
                            continue
                        
                        try:
                            # Parse transaction
                            if len(row) >= 9:
                                transaction_type = str(row[0]).strip() if row[0] else ''
                                jumlah_saham = parse_number(row[6])
                                harga = parse_number(row[8])
                                tanggal = parse_date(str(row[9]) if row[9] else '')
                                
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
                        except Exception as e:
                            print(f"Error parsing row: {e}")
                            continue
        
        return transactions, metadata
    
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return [], metadata

def calculate_balances(transactions):
    """Calculate running balances"""
    if not transactions:
        return transactions
    
    # Sort by date
    transactions = sorted(transactions, key=lambda x: x['date'])
    
    # Group by saham
    saham_groups = {}
    for trans in transactions:
        saham = trans['saham']
        if saham not in saham_groups:
            saham_groups[saham] = []
        saham_groups[saham].append(trans)
    
    # Calculate balances per saham
    result = []
    balances = {}
    
    for trans in transactions:
        saham = trans['saham']
        
        if saham not in balances:
            balances[saham] = 50000000000
        
        trans['jumlah_sebelum'] = balances[saham]
        trans['jumlah_sesudah'] = balances[saham] + trans['change']
        balances[saham] = trans['jumlah_sesudah']
        
        result.append(trans)
    
    return result

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/process', methods=['POST'])
def process_pdfs():
    """Process multiple PDF files"""
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'No files provided'})
    
    files = request.files.getlist('files')
    
    if not files:
        return jsonify({'success': False, 'error': 'No files selected'})
    
    all_transactions = []
    
    try:
        for file in files:
            if file.filename == '':
                continue
            
            if not file.filename.endswith('.pdf'):
                continue
            
            # Save temp file
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(temp_path)
            
            # Extract
            transactions, meta = extract_from_pdf(temp_path)
            all_transactions.extend(transactions)
            
            # Cleanup
            try:
                os.remove(temp_path)
            except:
                pass
        
        if not all_transactions:
            return jsonify({'success': False, 'error': 'No transactions found in PDFs'})
        
        # Calculate balances
        all_transactions = calculate_balances(all_transactions)
        
        # Store untuk download
        transactions_store['current'] = all_transactions
        
        return jsonify({
            'success': True,
            'data': all_transactions,
            'count': len(all_transactions)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/download', methods=['GET'])
def download_excel():
    """Download merged Excel"""
    try:
        if 'current' not in transactions_store:
            return jsonify({'error': 'No data to download'}), 400
        
        df = pd.DataFrame(transactions_store['current'])
        
        # Create Excel file in memory
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='All Transactions', index=False)
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'saham_merged_{datetime.now().strftime("%Y%m%d")}.xlsx'
        )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(debug=False, port=int(os.environ.get('PORT', 5000)))
