# PDF to Excel Converter - Saham Indonesia

Website untuk convert multiple PDF laporan kepemilikan saham (POJK format) ke Excel file yang sudah ter-merge.

## Features

✅ Upload 1-20 PDF sekaligus
✅ Auto-parse PDF dan extract data transaksi
✅ Merge semua data jadi 1 Excel
✅ Preview hasil sebelum download
✅ Gratis dan online 24/7

## Tech Stack

- **Frontend**: HTML, CSS, JavaScript
- **Backend**: Python Flask
- **PDF Parsing**: pdfplumber
- **Excel Export**: openpyxl, pandas
- **Deployment**: Vercel / Railway / Render

## Local Development

### Prerequisites
- Python 3.9+
- pip

### Setup

1. Clone repository
```bash
git clone https://github.com/finwellid-wq/pdf-saham-converter.git
cd pdf-saham-converter
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Run Flask app
```bash
python app.py
```

4. Open browser
```
http://localhost:5000
```

## Deployment

### Option 1: Vercel (Recommended)
1. Push code ke GitHub
2. Connect repo ke Vercel
3. Deploy automatically

### Option 2: Railway
1. Push code ke GitHub
2. Connect repo ke Railway
3. Select Python
4. Deploy

### Option 3: Render
1. Push code ke GitHub
2. Create new Web Service di Render
3. Connect repository
4. Deploy

## How It Works

1. User upload 1-20 PDF files
2. Flask backend receive files
3. pdfplumber parse each PDF
4. Extract transaction data
5. Merge all data ke 1 list
6. Calculate running balance
7. Return data to frontend
8. Frontend download as Excel

## File Structure

```
pdf-saham-converter/
├── app.py                 # Flask backend
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Frontend HTML
├── static/               # Static files (optional)
├── README.md            # Documentation
└── .gitignore          # Git ignore file
```

## API Endpoints

### GET /
- Returns main page

### POST /api/process
- Upload PDF files and process
- Returns JSON dengan merged data

### GET /health
- Health check

## Configuration

### Environment Variables
```
FLASK_ENV=production
FLASK_DEBUG=False
```

## Support

Untuk pertanyaan atau issues, create issue di GitHub atau contact: finwell.id@gmail.com

## License

MIT License
