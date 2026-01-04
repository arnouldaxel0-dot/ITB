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

# --- 1. CONNEXION GITHUB ---
try:
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
    REPO_NAME = st.secrets.get("REPO_NAME", "")
    if GITHUB_TOKEN and REPO_NAME:
        # Utilisation de la nouvelle methode d'auth recommandee par les logs
        from github import Auth
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)
    else:
        st.error("Erreur : Configuration GITHUB_TOKEN ou REPO_NAME manquante.")
except Exception as e:
    st.error(f"Erreur GitHub : {e}")

# --- 2. CONFIGURATION ---
BASE_DIR = "CHANTIERS_ITB77"
COLS_BETON = ["Fournisseur", "Designation", "Type de Beton", "Volume (m3)"]
COLS_ACIER = ["Fournisseur", "Type d Acier", "Designation", "Poids (kg)"]

st.set_page_config(page_title="ITB77 PRO", layout="wide")

# --- 3. FONCTIONS ---
def lire_excel_github(path):
    try:
        content = repo.get_contents(path)
        return pd.read_excel(io.BytesIO(content.decoded_content), sheet_name=None), content.sha
    except: return None, None

def sauvegarder_excel_github(file_dict, path, sha=None):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet, df in file_dict.items():
            df.to_excel(writer, sheet_name=sheet, index=False)
    content_bytes = output.getvalue()
    if sha: repo.update_file(path, "Update", content_bytes, sha)
    else: repo.create_file(path, "Create", content_bytes)

def lister_chantiers():
    try:
        contents = repo.get_contents(BASE_DIR)
        return sorted([c.name for c in contents if c.type == "dir"])
    except: return []

def analyser_ia(uploaded_file, api_key, prompt):
    file_ext = uploaded_file.name.lower()
    if file_ext.endswith('.heic'):
        heif_file = pillow_heif.read_heif(uploaded_file)
        image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        img_bytes = buffer.getvalue()
    else: img_bytes = uploaded_file.getvalue()
    
    b64 = base64.b64encode(img_bytes).decode('utf-8')
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        "temperature": 0
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload).json()
    txt = r['choices'][0]['message']['content'].strip()
    if txt.startswith("```"): txt = txt.split("```")[1].replace("json", "").strip()
    return pd.DataFrame(json.loads(txt))

# --- 4. INTERFACE ---
if 'page' not in st.session_state: st.session_state.page = "Accueil"
if 'relecture' not in st.session_state: st.session_state.relecture = None

# Barre latérale : Clé unique
st.sidebar.title("Configuration")
api_k = st.sidebar.text_input("Cle OpenAI", type="password", key="main_openai_key")

st.markdown('<h1 style="color:#E67E22; text-align:center;">GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    c1, c2 = st.columns([6, 4])
    with c1:
        st.subheader("Mes Chantiers")
        for c in lister_chantiers():
            if st.button(f"🏢 {c}", key=f"sel_{c}", width='stretch'):
                st.session_state.page = c
                st.rerun()
    with c2:
        st.subheader("Nouveau")
        n = st.text_input("Nom du projet")
        if st.button("Creer Projet") and n:
            p = f"{BASE_DIR}/{n}/{n}.xlsx"
            d = {"Beton": pd.DataFrame(columns=COLS_BETON), "Acier": pd.DataFrame(columns=COLS_ACIER)}
            sauvegarder_excel_github(d, p)
            st.session_state.page = n
            st.rerun()

else:
    nom_c = st.session_state.page
    st.header(f"Chantier : {nom_c}")
    if st.button("⬅ Retour"):
        st.session_state.page = "Accueil"
        st.session_state.relecture = None
        st.rerun()

    path_f = f"{BASE_DIR}/{nom_c}/{nom_c}.xlsx"
    sheets, sha = lire_excel_github(path_f)
    
    if sheets:
        tab1, tab2 = st.tabs(["💧 Beton", "🏗 Acier"])
        
        # --- ONGLET BETON ---
        with tab1:
            up_b = st.file_uploader("Bon Beton", type=['jpg','png','heic'], key="file_b")
            if up_b and api_k and st.session_state.relecture is None:
                if st.button("Scanner Beton", type="primary", key="btn_b"):
                    with st.spinner("Analyse IA..."):
                        res = analyser_ia(up_b, api_k, f"Extrais beton JSON. Colonnes: {COLS_BETON}")
                        st.session_state.relecture = res.reindex(columns=COLS_BETON)
                        st.rerun()
            if st.session_state.relecture is not None:
                st.write("Verifiez les donnees :")
                df_m = st.data_editor(st.session_state.relecture, key="edit_b")
                if st.button("Valider et Enregistrer", key="save_b"):
                    sheets["Beton"] = pd.concat([sheets["Beton"], df_m], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.rerun()
            st.divider()
            st.dataframe(sheets["Beton"], width='stretch')

        # --- ONGLET ACIER ---
        with tab2:
            up_a = st.file_uploader("Bon Acier", type=['jpg','png','heic'], key="file_a")
            if up_a and api_k and st.session_state.relecture is None:
                if st.button("Scanner Acier", type="primary", key="btn_a"):
                    with st.spinner("Analyse IA..."):
                        res = analyser_ia(up_a, api_k, f"Extrais acier JSON. Colonnes: {COLS_ACIER}")
                        st.session_state.relecture = res.reindex(columns=COLS_ACIER)
                        st.rerun()
            if st.session_state.relecture is not None:
                st.write("Verifiez les donnees :")
                df_m = st.data_editor(st.session_state.relecture, key="edit_a")
                if st.button("Valider et Enregistrer", key="save_a"):
                    sheets["Acier"] = pd.concat([sheets["Acier"], df_m], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.rerun()
            st.divider()
            st.dataframe(sheets["Acier"], width='stretch')
