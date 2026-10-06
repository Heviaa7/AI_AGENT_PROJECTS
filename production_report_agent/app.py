import io, json, re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Production Report Agent", page_icon="📊", layout="wide")

STANDARD = ["Batch_ID","Product_ID","Lini_Produksi","Qty_Rencana","Qty_Hasil","Qty_Defect","Status_Batch"]
REQUIRED = ["Batch_ID","Qty_Rencana","Qty_Hasil","Qty_Defect"]

ALIASES = {
"Batch_ID":["batch_id","batch id","id batch","nomor batch","no batch","kode batch"],
"Product_ID":["product_id","product id","id produk","kode produk","product code"],
"Lini_Produksi":["lini_produksi","lini produksi","nama lini","jalur produksi","line produksi","production line"],
"Qty_Rencana":["qty_rencana","qty rencana","target produksi","jumlah target","rencana produksi","planned quantity"],
"Qty_Hasil":["qty_hasil","qty hasil","hasil produksi","output aktual","produksi aktual","actual output"],
"Qty_Defect":["qty_defect","qty defect","jumlah cacat","produk cacat","jumlah produk rusak","defect quantity"],
"Status_Batch":["status_batch","status batch","status produksi","status"]
}

def norm(x):
    x = re.sub(r"[_\-/]+", " ", str(x).strip().lower())
    return re.sub(r"\s+", " ", x)

def deterministic_mapping(df):
    index = {}
    for standard, aliases in ALIASES.items():
        for a in [standard] + aliases:
            index[norm(a)] = standard
    mapping, used = {}, {}
    for col in df.columns:
        target = index.get(norm(col))
        if target:
            if target in used:
                raise ValueError(f"Lebih dari satu kolom cocok untuk {target}: {used[target]} dan {col}")
            mapping[col] = target
            used[target] = col
    return mapping

def gemini_mapping(df):
    from google import genai
    key = st.secrets.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY belum ada di Streamlit Secrets.")
    client = genai.Client(api_key=key)
    prompt = f"""Map uploaded spreadsheet columns to these standard fields:\n{STANDARD}\nUploaded columns:\n{list(map(str, df.columns))}\nReturn ONLY JSON object: uploaded_column -> standard field or null.\nDo not invent columns. Do not map two columns to the same standard field."""
    r = client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt)
    raw = re.sub(r"^```json\s*|\s*```$", "", r.text.strip())
    obj = json.loads(raw)
    result, used = {}, set()
    for source, target in obj.items():
        if source in df.columns and target in STANDARD and target not in used:
            result[source] = target
            used.add(target)
    return result

def apply_mapping(df, mapping):
    used, clean = set(), {}
    for source, target in mapping.items():
        if source in df.columns and target in STANDARD:
            if target in used:
                raise ValueError(f"Target {target} dipakai lebih dari sekali.")
            clean[source] = target
            used.add(target)
    return df.rename(columns=clean), clean

def calculate(df):
    x = df.copy()
    for c in ["Qty_Rencana","Qty_Hasil","Qty_Defect"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    if "Status_Batch" in x.columns:
        s = x["Status_Batch"].astype(str).str.strip().str.lower()
        completed = s.isin(["selesai","completed","complete","done","finished"])
        if completed.any():
            x = x.loc[completed].copy()
    x = x.dropna(subset=["Qty_Rencana","Qty_Hasil","Qty_Defect"])
    x = x[x["Qty_Rencana"] > 0].copy()
    if x.empty:
        raise ValueError("Tidak ada batch valid untuk dihitung.")
    x["Selisih_Pasang"] = x["Qty_Hasil"] - x["Qty_Rencana"]
    x["Pencapaian_Persen"] = x["Qty_Hasil"] / x["Qty_Rencana"] * 100
    x["Defect_Rate_Hitung"] = x["Qty_Defect"] / x["Qty_Hasil"].replace(0, pd.NA) * 100
    target, hasil, defect = x["Qty_Rencana"].sum(), x["Qty_Hasil"].sum(), x["Qty_Defect"].sum()
    kpi = {"Total Batch": len(x), "Total Rencana": target, "Total Hasil": hasil, "Total Cacat": defect, "Pencapaian (%)": hasil/target*100, "Defect Rate (%)": defect/hasil*100 if hasil else 0}
    if "Lini_Produksi" in x.columns:
        line = x.groupby("Lini_Produksi", dropna=False).agg(Total_Batch=("Batch_ID","count"), Total_Rencana=("Qty_Rencana","sum"), Total_Hasil=("Qty_Hasil","sum"), Total_Cacat=("Qty_Defect","sum")).reset_index()
        line["Pencapaian_%"] = line["Total_Hasil"] / line["Total_Rencana"] * 100
        line["Defect_Rate_%"] = line["Total_Cacat"] / line["Total_Hasil"].replace(0,pd.NA) * 100
    else:
        line = pd.DataFrame()
    return x, kpi, line

def ai_analysis(kpi, line):
    from google import genai
    key = st.secrets.get("GEMINI_API_KEY")
    if not key:
        return "AI belum aktif. Tambahkan GEMINI_API_KEY pada Secrets."
    client = genai.Client(api_key=key)
    prompt = f"""Analisis data produksi pabrik sepatu berikut secara singkat dan praktis.\nKPI: {json.dumps(kpi, default=str, ensure_ascii=False)}\nPer lini: {json.dumps(line.to_dict('records'), default=str, ensure_ascii=False)}\nBerikan: Ringkasan kondisi, Temuan utama, Area perhatian, Rekomendasi.\nJangan mengarang data."""
    return client.models.generate_content(model="gemini-3.1-flash-lite", contents=prompt).text

st.title("📊 Production Report Agent")
st.caption("Excel → Mapping → KPI → AI Insight → Report")
file = st.file_uploader("Upload Excel produksi", type=["xlsx","xls"])
if not file:
    st.info("Upload file Excel untuk memulai.")
    st.stop()

data = file.getvalue()
sheets = pd.ExcelFile(io.BytesIO(data)).sheet_names
sheet = st.selectbox("Pilih sheet produksi", sheets)
raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet)

st.subheader("1. Preview")
st.dataframe(raw.head(10), use_container_width=True)
st.caption(f"{len(raw):,} baris × {len(raw.columns)} kolom")

st.subheader("2. Mapping kolom")
auto = deterministic_mapping(raw)
if auto:
    st.write("Mapping otomatis:")
    st.json(auto)
missing = [c for c in REQUIRED if c not in set(auto.values())]
if missing:
    st.warning("Kolom wajib belum lengkap: " + ", ".join(missing))
    if st.button("🤖 Minta Gemini mengusulkan mapping"):
        try:
            st.session_state["proposal"] = gemini_mapping(raw)
            st.rerun()
        except Exception as e:
            st.error(f"Gemini gagal: {e}")
proposal = st.session_state.get("proposal", {})
if proposal:
    st.info("Periksa usulan Gemini sebelum diterapkan.")
    edited = {}
    options = [""] + STANDARD
    for col in raw.columns:
        default = proposal.get(col, "")
        choice = st.selectbox(f"{col} →", options, index=options.index(default) if default in options else 0, key="map_"+str(col))
        if choice:
            edited[col] = choice
    if st.button("✅ Konfirmasi mapping"):
        try:
            mapped, _ = apply_mapping(raw, edited)
            st.session_state["confirmed_df"] = mapped
            st.session_state["proposal"] = {}
            st.rerun()
        except Exception as e:
            st.error(str(e))

mapped = st.session_state.get("confirmed_df")
if mapped is None:
    mapped, _ = apply_mapping(raw, auto)
missing = [c for c in REQUIRED if c not in mapped.columns]
if missing:
    st.error("Belum bisa menghitung KPI. Masih kurang: " + ", ".join(missing))
    st.stop()

st.success("Mapping siap diproses.")
st.subheader("3. KPI Produksi")
try:
    result, kpi, line = calculate(mapped)
except Exception as e:
    st.error(str(e))
    st.stop()
cards = st.columns(6)
for card, (label, value) in zip(cards, kpi.items()):
    card.metric(label, f"{value:.2f}%" if "%" in label else f"{value:,.0f}")

st.subheader("4. Grafik")
if not line.empty:
    st.bar_chart(line.set_index("Lini_Produksi")[["Total_Rencana","Total_Hasil"]])
    st.line_chart(line.set_index("Lini_Produksi")[["Defect_Rate_%"]])
else:
    st.info("Lini_Produksi tidak tersedia.")

st.subheader("5. Detail")
st.dataframe(result, use_container_width=True)
st.subheader("6. Analisis AI")
if st.button("✨ Buat analisis"):
    with st.spinner("Gemini menganalisis..."):
        st.session_state["analysis"] = ai_analysis(kpi, line)
if st.session_state.get("analysis"):
    st.markdown(st.session_state["analysis"])
