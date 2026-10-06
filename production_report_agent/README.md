# Production Report Agent

Streamlit app untuk upload Excel produksi, mapping kolom, menghitung KPI, membuat grafik, dan menghasilkan insight dengan Gemini.

## Local
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Gemini
Buat `.streamlit/secrets.toml`:
```toml
GEMINI_API_KEY = "YOUR_KEY"
```
Jangan commit secrets.toml ke GitHub.
