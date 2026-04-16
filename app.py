from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import pdfplumber
import pandas as pd
import os
from werkzeug.utils import secure_filename
import json
from datetime import datetime

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

UPLOAD_FOLDER = '/tmp/pdf_uploads'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_transactions_from_pdf(pdf_path):
    """Extract transaction data from POJK format PDF"""
    transactions = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            metadata = {}
            
            # Extract metadata from first page
            first_page = pdf.pages[0]
            text = first_page.extract_text()
            
            # Extract company name and big player info
            if 'CUAN' in text:
                metadata['saham'] = 'CUAN'
            elif 'BBRI' in text:
                metadata['saham'] = 'BBRI'
            elif 'ASII' in text:
                metadata['saham'] = 'ASII'
            elif 'BMRI' in text:
                metadata['saham'] = 'BMRI'
            else:
                # Try to extract from "Nama Perusahaan Tbk"
                import re
                match = re.search(r'Nama Perusahaan Tbk\s*:\s*([A-Z]+)', text)
                if match:
                    saham_code = match.group(1).split('-')[0].strip()
                    metadata['saham'] = saham_code[:4]
                else:
                    metadata['saham'] = 'UNKNOWN'
            
            # Extract big player name
            if 'PRAJOGO PANGESTU' in text:
                metadata['big_player'] = 'PRAJOGO PANGESTU'
            else:
                import re
                match = re.search(r'Nama \(sesuai SID\)\s*:\s*([^\n]+)', text)
                if match:
                    metadata['big_player'] = match.group(1).strip()
                else:
                    metadata['big_player'] = 'Unknown'
            
            # Extract transactions from all pages
            for page_idx, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                
                if not tables:
                    continue
                
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Check if this is a transaction table
                    headers_text = ' '.join(str(h).lower() for h in table[0] if h)
                    
                    if 'jumlah saham' not in headers_text and 'harga' not in headers_text:
                        continue
                    
                    # Process transaction rows
                    for row_idx in range(1, len(table)):
                        row = table[row_idx]
                        
                        if not any(cell for cell in row if cell):
                            continue
                        
                        try:
                            transaction = parse_transaction_row(row, metadata)
                            if transaction:
                                transactions.append(transaction)
                        except Exception as e:
                            print(f"Warning: Could not parse row: {e}")
        
        return transactions
    
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return []


def parse_transaction_row(row, metadata):
    """Parse a single transaction row"""
    if len(row) < 8:
        return None
    
    try:
        import re
        
        # Clean cell data
        def clean_cell(cell):
            if cell is None:
                return ''
            return str(cell).strip()
        
        def parse_number(text):
            if not text:
                return 0
            text = text.replace(' ', '').replace('.', '').replace(',', '.')
            try:
                return float(text)
            except:
                return 0
        
        def parse_date(text):
            if not text:
                return ''
            
            text = text.lower()
            months = {
                'jan': 1, 'peb': 2, 'feb': 2, 'mar': 3, 'apr': 4, 'mei': 5, 'jun': 6,
                'jul': 7, 'agu': 8, 'aug': 8, 'sep': 9, 'okt': 10, 'oct': 10, 'nov': 11, 'des': 12, 'dec': 12
            }
            
            patterns = [
                r'(\d{1,2})-(\w+)-(\d{4})',
                r'(\d{2})/(\d{2})/(\d{4})',
                r'(\d{4})-(\d{2})-(\d{2})',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    try:
                        d, m, y = match.groups()
                        if m.isdigit():
                            month = int(m)
                        else:
                            month = months.get(m[:3], 1)
                        return f"{y}-{month:02d}-{int(d):02d}"
                    except:
                        pass
            
            return text
        
        # Extract values - adjust indices based on PDF structure
        transaction_type = clean_cell(row[0])  # Penjualan/Pembelian
        
        # Find the price and date columns
        jumlah_saham = parse_number(clean_cell(row[6]))
        harga = parse_number(clean_cell(row[8]))
        tanggal = parse_date(clean_cell(row[9]))
        
        if not all([transaction_type, jumlah_saham, harga, tanggal]):
            return None
        
        transaction = {
            'saham': metadata.get('saham', 'UNKNOWN'),
            'date': tanggal,
            'broker': 'Penjualan' if 'Penjualan' in transaction_type else 'Pembelian',
            'big_player': metadata.get('big_player', 'Unknown'),
            'jumlah_sebelum': 0,
            'change': -int(jumlah_saham) if 'Penjualan' in transaction_type else int(jumlah_saham),
            'jumlah_sesudah': 0,
            'harga': int(harga)
        }
        
        return transaction
    
    except Exception as e:
        print(f"Error parsing row: {e}")
        return None


def calculate_running_balance(transactions):
    """Calculate running balance for transactions"""
    if not transactions:
        return transactions
    
    df = pd.DataFrame(transactions)
    
    if df.empty:
        return transactions
    
    # Sort by date
    df = df.sort_values('date').reset_index(drop=True)
    
    # Group by saham to maintain separate balances
    initial_balances = {
        'CUAN': 93152298800,
        'BBRI': 50000000000,
        'ASII': 80000000000,
        'BMRI': 60000000000,
        'UNKNOWN': 50000000000
    }
    
    jumlah_sebelum = []
    current_balances = {}
    
    for idx, row in df.iterrows():
        saham = row['saham']
        
        if saham not in current_balances:
            current_balances[saham] = initial_balances.get(saham, 50000000000)
        
        jumlah_sebelum.append(current_balances[saham])
        current_balances[saham] = current_balances[saham] + row['change']
    
    df['jumlah_sebelum'] = jumlah_sebelum
    df['jumlah_sesudah'] = df['jumlah_sebelum'] + df['change']
    
    # Convert to integers
    for col in ['jumlah_sebelum', 'change', 'jumlah_sesudah', 'harga']:
        df[col] = df[col].astype(int)
    
    return df.to_dict('records')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/process', methods=['POST'])
def process_pdfs():
    """Process multiple PDF files and merge data"""
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'No files provided'})
    
    files = request.files.getlist('files')
    
    if not files or len(files) == 0:
        return jsonify({'success': False, 'error': 'No files selected'})
    
    all_transactions = []
    
    try:
        for file in files:
            if file.filename == '':
                continue
            
            if not allowed_file(file.filename):
                continue
            
            # Save file
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Extract transactions
            transactions = extract_transactions_from_pdf(filepath)
            all_transactions.extend(transactions)
            
            # Clean up
            try:
                os.remove(filepath)
            except:
                pass
        
        if not all_transactions:
            return jsonify({'success': False, 'error': 'No transactions found in PDFs'})
        
        # Calculate running balance
        all_transactions = calculate_running_balance(all_transactions)
        
        return jsonify({
            'success': True,
            'data': all_transactions,
            'count': len(all_transactions)
        })
    
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
