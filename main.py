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

# --- CONFIGURATION GITHUB ---
try:
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
    REPO_NAME = st.secrets.get("REPO_NAME", "")
    
    if GITHUB_TOKEN and REPO_NAME:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
    else:
        st.error("Erreur : GITHUB_TOKEN ou REPO_NAME absent des Secrets.")
except Exception as e:
    st.error(f"Erreur de configuration : {e}")

# --- CONFIGURATION PROJET ---
BASE_DIR = "CHANTIERS_ITB77"
COLS_BETON = ["Fournisseur", "Designation", "Type de Beton", "Volume (m3)"]
COLS_ACIER = ["Fournisseur", "Type d Acier", "Designation", "Poids (kg)"]

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
        repo.update_file(path, "MAJ chantier", content_bytes, sha)
    else:
        repo.create_file(path, "Creation chantier", content_bytes)

def lister_chantiers_github():
    try:
        contents = repo.get_contents(BASE_DIR)
        return sorted([c.name for c in contents if c.type == "dir"])
    except:
        return []

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
    if content.startswith("```"):
        content = content.split("```")[1].replace("json", "").strip()
    return pd.DataFrame(json.loads(content))

# --- INTERFACE ---
if 'page' not in st.session_state: st.session_state.page = "Accueil"
if 'relecture' not in st.session_state: st.session_state.relecture = None

# CLE API UNIQUE DANS LA SIDEBAR (Evite l'erreur Duplicate ID)
api_k = st.sidebar.text_input("Cle OpenAI", type="password")

st.markdown('<h1 style="color:#E67E22; text-align:center;">GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    col1, col2 = st.columns([6, 4])
    with col1:
        st.subheader("Chantiers")
        chantiers = lister_chantiers_github()
        for c in chantiers:
            if st.button(f"Chantier {c}", key=f"btn_{c}", use_container_width=True):
                st.session_state.page = c
                st.rerun()
    with col2:
        st.subheader("Nouveau Projet")
        nom = st.text_input("Nom")
        if st.button("Creer") and nom:
            path = f"{BASE_DIR}/{nom}/{nom}.xlsx"
            data = {"Beton": pd.DataFrame(columns=COLS_BETON), "Acier": pd.DataFrame(columns=COLS_ACIER)}
            sauvegarder_excel_github(data, path)
            st.session_state.page = nom
            st.rerun()
else:
    nom_c = st.session_state.page
    st.header(f"Projet : {nom_c}")
    if st.button("Retour"):
        st.session_state.page = "Accueil"
        st.session_state.relecture = None
        st.rerun()

    path_file = f"{BASE_DIR}/{nom_c}/{nom_c}.xlsx"
    all_sheets, sha = lire_excel_github(path_file)
    
    if all_sheets:
        t_beton, t_acier = st.tabs(["Beton", "Acier"])
        
        def zone_scan(onglet, colonnes, prompt):
            up = st.file_uploader(f"Photo {onglet}", type=['jpg','png','heic'], key=f"up_{onglet}")
            
            if up and api_k and st.session_state.relecture is None:
                if st.button(f"Scanner {onglet}", key=f"btn_scan_{onglet}"):
                    with st.spinner("Analyse..."):
                        res = analyser_image(up, api_k, prompt + f" Colonnes: {colonnes}")
                        st.session_state.relecture = res.reindex(columns=colonnes)
                        st.rerun()
            
            if st.session_state.relecture is not None:
                st.write("Verifiez les donnees :")
                df_m = st.data_editor(st.session_state.relecture, key=f"editor_{onglet}")
                if st.button("Enregistrer", key=f"save_{onglet}"):
                    all_sheets[onglet] = pd.concat([all_sheets[onglet], df_m], ignore_index=True)
                    sauvegarder_excel_github(all_sheets, path_file, sha)
                    st.session_state.relecture = None
                    st.rerun()
            
            st.divider()
            st.dataframe(all_sheets[onglet], use_container_width=True)

        with t_beton: zone_scan("Beton", COLS_BETON, "Donnees beton JSON.")
        with t_acier: zone_scan("Acier", COLS_ACIER, "Donnees acier JSON.")
    else:
        st.error("Impossible de charger le fichier.")
