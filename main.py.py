import streamlit as st
import pandas as pd
import base64
import requests
import json
import io
from github import Github
from PIL import Image
import pillow_heif
from datetime import datetime

# --- CONFIGURATION GITHUB (Via Streamlit Secrets) ---
# Ces infos seront à remplir dans l'interface de Streamlit Cloud
try:
    GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
    REPO_NAME = st.secrets["REPO_NAME"]  # Format: "ton-pseudo/ton-depot"
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
except:
    st.error(⚠️ Configuration GitHub manquante dans les Secrets.")

# --- CONFIGURATION PROJET ---
BASE_DIR = "CHANTIERS_ITB77"
COLS_BETON = ["Fournisseur", "Désignation", "Type de Béton", "Volume (m3)"]
COLS_ACIER = ["Fournisseur", "Type d'Acier", "Désignation", "Poids (kg)"]

st.set_page_config(page_title="Scan Pro ITB77", layout="wide")

# --- FONCTIONS GITHUB ---

def lire_excel_github(path):
    try:
        content = repo.get_contents(path)
        return pd.read_excel(io.BytesIO(content.decoded_content), sheet_name=None), content.sha
    except:
        return None, None

def sauvegarder_excel_github(file_dict, path, sha=None):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet, df in file_dict.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
    
    content_bytes = output.getvalue()
    if sha:
        repo.update_file(path, f"Mise à jour {path}", content_bytes, sha)
    else:
        repo.create_file(path, f"Création {path}", content_bytes)

def lister_chantiers_github():
    try:
        contents = repo.get_contents(BASE_DIR)
        return sorted([c.name for c in contents if c.type == "dir"])
    except: return []

# --- LOGIQUE IA ---
def analyser_image(uploaded_file, api_key, prompt):
    file_ext = uploaded_file.name.lower()
    if file_ext.endswith('.heic'):
        heif_file = pillow_heif.read_heif(uploaded_file)
        image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()
    else:
        img_bytes = uploaded_file.getvalue()

    base64_img = base64.b64encode(img_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
        ]}],
        "temperature": 0
    }
    resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload).json()
    content = resp['choices'][0]['message']['content'].strip()
    if content.startswith("```"): content = content.split("```")[1].replace("json", "").strip()
    return pd.DataFrame(json.loads(content))

# --- INTERFACE ---
if 'page' not in st.session_state: st.session_state.page = "Accueil"
if 'relecture' not in st.session_state: st.session_state.relecture = None

st.markdown('<h1 style="color:#E67E22; text-align:center;">🏗️ GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    col1, col2 = st.columns([6, 4])
    
    with col1:
        st.subheader("📂 Chantiers")
        chantiers = lister_chantiers_github()
        for c in chantiers:
            if st.button(f"🏢 {c}", use_container_width=True):
                st.session_state.page = c
                st.rerun()
    
    with col2:
        st.subheader("+ Nouveau Chantier")
        nom = st.text_input("Nom")
        if st.button("Créer") and nom:
            path = f"{BASE_DIR}/{nom}/{nom}.xlsx"
            empty_data = {"Béton": pd.DataFrame(columns=COLS_BETON), "Acier": pd.DataFrame(columns=COLS_ACIER)}
            sauvegarder_excel_github(empty_data, path)
            st.session_state.page = nom
            st.rerun()

else:
    # PAGE CHANTIER
    nom_c = st.session_state.page
    st.header(f"📍 {nom_c}")
    if st.button("⬅️ Retour"): st.session_state.page = "Accueil"; st.rerun()

    path_file = f"{BASE_DIR}/{nom_c}/{nom_c}.xlsx"
    all_sheets, sha = lire_excel_github(path_file)
    
    t_beton, t_acier = st.tabs(["Béton", "Acier"])

    def zone_scan(onglet, colonnes, prompt):
        st.subheader(f"Scan {onglet}")
        up = st.file_uploader(f"Photo {onglet}", type=['jpg','png','heic'], key=f"up{onglet}")
        api_k = st.sidebar.text_input("Clé OpenAI", type="password")
        
        if up and api_k and st.session_state.relecture is None:
            if st.button(f"Analyser {onglet}"):
                df_res = analyser_image(up, api_k, prompt + f" Colonnes: {colonnes}")
                st.session_state.relecture = df_res.reindex(columns=colonnes)
                st.rerun()
        
        if st.session_state.relecture is not None:
            df_m = st.data_editor(st.session_state.relecture, num_rows="dynamic")
            if st.button("Enregistrer sur GitHub"):
                all_sheets[onglet] = pd.concat([all_sheets[onglet], df_m], ignore_index=True)
                sauvegarder_excel_github(all_sheets, path_file, sha)
                st.session_state.relecture = None
                st.success("Enregistré !")
                st.rerun()
            if st.button("Annuler"): st.session_state.relecture = None; st.rerun()

        st.divider()
        st.dataframe(all_sheets[onglet], use_container_width=True)

    with t_beton:
        zone_scan("Béton", COLS_BETON, "Extrais les données de béton en JSON.")
    with t_acier:
        zone_scan("Acier", COLS_ACIER, "Extrais les données d'acier en JSON.")