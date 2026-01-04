import streamlit as st
import pandas as pd
import base64
import requests
import json
import io
from github import Github, Auth
from PIL import Image
import pillow_heif
from datetime import datetime

# --- 1. CONFIGURATION GITHUB ET OPENAI (Via Secrets) ---
try:
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
    REPO_NAME = st.secrets.get("REPO_NAME", "")
    OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")
    
    if GITHUB_TOKEN and REPO_NAME:
        auth = Auth.Token(GITHUB_TOKEN)
        g = Github(auth=auth)
        repo = g.get_repo(REPO_NAME)
    else:
        st.error("Configuration GitHub manquante dans les Secrets.")
except Exception as e:
    st.error(f"Erreur de configuration : {e}")

# --- 2. CONFIGURATION PROJET ---
BASE_DIR = "CHANTIERS_ITB77"
COLS_BETON = ["Fournisseur", "Designation", "Type de Beton", "Volume (m3)"]
COLS_ACIER = ["Fournisseur", "Type d Acier", "Designation", "Poids (kg)"]
COLS_PREV = ["Designation", "Prevu (m3)", "Zone"]

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
    if not api_key:
        st.error("La cle OpenAI est manquante.")
        return None
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

st.markdown('<h1 style="color:#E67E22; text-align:center;">GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    col_titre, col_refresh = st.columns([8, 2])
    with col_titre: st.subheader("Mes Projets")
    with col_refresh:
        if st.button("🔄 Actualiser", width='stretch'): st.rerun()

    c1, c2 = st.columns([6, 4])
    with c1:
        for c in lister_chantiers():
            if st.button(f"🏢 {c}", key=f"sel_{c}", width='stretch'):
                st.session_state.page = c
                st.rerun()
    with c2:
        st.subheader("Nouveau")
        n = st.text_input("Nom du chantier", key="new_name_sync")
        if st.button("Creer Chantier") and n:
            p = f"{BASE_DIR}/{n}/{n}.xlsx"
            try:
                temp = repo.get_contents("template_itb77.xlsx")
                repo.create_file(p, f"Init {n}", temp.decoded_content)
            except:
                d = {"Beton": pd.DataFrame(columns=COLS_BETON), "Acier": pd.DataFrame(columns=COLS_ACIER), "Previsionnel": pd.DataFrame(columns=COLS_PREV)}
                sauvegarder_excel_github(d, p)
            st.success(f"Chantier {n} créé !")
            st.session_state.page = n
            st.rerun()

else:
    nom_c = st.session_state.page
    st.header(f"📍 {nom_c}")
    if st.button("⬅ Retour"):
        st.session_state.page = "Accueil"
        st.session_state.relecture = None
        st.rerun()

    path_f = f"{BASE_DIR}/{nom_c}/{nom_c}.xlsx"
    sheets, sha = lire_excel_github(path_f)
    
    if sheets is not None:
        tab1, tab2, tab3, tab4 = st.tabs(["Beton", "Acier", "Prévisionnel", "Récapitulatif"])
        
        df_beton = sheets.get("Beton", pd.DataFrame(columns=COLS_BETON))
        if df_beton.empty: df_beton = pd.DataFrame(columns=COLS_BETON)
        
        df_acier = sheets.get("Acier", pd.DataFrame(columns=COLS_ACIER))
        if df_acier.empty: df_acier = pd.DataFrame(columns=COLS_ACIER)

        df_prev = sheets.get("Previsionnel", pd.DataFrame(columns=COLS_PREV))
        if not df_prev.empty and "Zone" not in df_prev.columns:
            df_prev["Zone"] = "INFRA"
        if df_prev.empty: df_prev = pd.DataFrame(columns=COLS_PREV)
        
        with tab1:
            up_b = st.file_uploader("Scan Bon Beton", type=['jpg','png','heic'], key="up_b")
            if up_b and st.session_state.relecture is None:
                if st.button("Envoyer Bon", key="btn_b", type="primary"):
                    with st.spinner("IA en cours..."):
                        res = analyser_ia(up_b, OPENAI_API_KEY, f"Donnees beton JSON. Colonnes: {COLS_BETON}")
                        st.session_state.relecture = res.reindex(columns=COLS_BETON)
                        st.rerun()
            if st.session_state.relecture is not None:
                df_m = st.data_editor(st.session_state.relecture, key="edit_b")
                if st.button("Valider et Sauvegarder", key="save_b"):
                    sheets["Beton"] = pd.concat([df_beton, df_m], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.rerun()
            st.divider()
            st.dataframe(df_beton, width='stretch')

        with tab2:
            up_a = st.file_uploader("Bon acier", type=['jpg','png','heic'], key="up_a")
            if up_a and st.session_state.relecture is None:
                if st.button("Envoyer Bon", key="btn_a", type="primary"):
                    with st.spinner("IA en cours..."):
                        res = analyser_ia(up_a, OPENAI_API_KEY, f"Donnees acier JSON. Colonnes: {COLS_ACIER}")
                        st.session_state.relecture = res.reindex(columns=COLS_ACIER)
                        st.rerun()
            if st.session_state.relecture is not None:
                df_m = st.data_editor(st.session_state.relecture, key="edit_a")
                if st.button("Valider et Sauvegarder", key="save_a"):
                    sheets["Acier"] = pd.concat([df_acier, df_m], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.rerun()
            st.divider()
            st.dataframe(df_acier, width='stretch')

        with tab3:
            col_half, col_void = st.columns([1, 1])
            with col_half:
                st.subheader("Ajouter un budget")
                with st.form("ajout_prev"):
                    new_des = st.text_input("Désignation générique (ex: Voiles, Dalles)")
                    new_vol = st.number_input("Volume Prévu (m3)", step=1.0)
                    new_zone = st.radio("Zone", ["INFRA", "SUPER"], horizontal=True)
                    submitted = st.form_submit_button("Ajouter (+)")
                    if submitted and new_des:
                        new_row = pd.DataFrame([{"Designation": new_des, "Prevu (m3)": new_vol, "Zone": new_zone}])
                        sheets["Previsionnel"] = pd.concat([df_prev, new_row], ignore_index=True)
                        sauvegarder_excel_github(sheets, path_f, sha)
                        st.rerun()
                st.divider()
                st.write("**Budget Existant :**")
                df_prev_edit = st.data_editor(df_prev, num_rows="dynamic", key="edit_prev", use_container_width=True)
                if st.button("Sauvegarder Tableau", key="save_prev_tbl"):
                    sheets["Previsionnel"] = df_prev_edit
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.rerun()

        with tab4:
            st.subheader("Bilan consolidé par Famille")
            if not df_prev.empty:
                # 1. On prépare les données réelles
                df_calc = df_beton.copy()
                df_calc["Volume (m3)"] = pd.to_numeric(df_calc["Volume (m3)"], errors='coerce').fillna(0)
                
                # 2. On prépare le prévisionnel
                df_target = df_prev.copy()
                df_target["Prevu (m3)"] = pd.to_numeric(df_target["Prevu (m3)"], errors='coerce').fillna(0)
                
                # 3. ALGORITHME DE REGROUPEMENT INTELLIGENT
                # On crée une nouvelle colonne 'Volume Reel' dans le tableau prévisionnel
                df_target["Volume Reel"] = 0.0
                
                # Pour chaque ligne de bon de livraison (Réel)
                # On regarde à quelle catégorie du Prévisionnel elle appartient
                for idx_reel, row_reel in df_calc.iterrows():
                    nom_reel = str(row_reel["Designation"]).lower()
                    volume = row_reel["Volume (m3)"]
                    match_found = False
                    
                    # On parcourt les catégories du prévisionnel pour trouver un mot clé correspondant
                    for idx_prev, row_prev in df_target.iterrows():
                        mot_cle = str(row_prev["Designation"]).lower()
                        # Si le mot clé (ex: "voile") est dans la désignation réelle (ex: "voile rdc bat A")
                        # OU si la désignation est identique
                        if mot_cle in nom_reel: 
                            df_target.at[idx_prev, "Volume Reel"] += volume
                            match_found = True
                            break
                    
                    # (Optionnel) Si aucun match, on pourrait l'ajouter dans une catégorie "Autre"
                
                # 4. AFFICHAGE PAR ZONE
                for zone_name in ["INFRA", "SUPER"]:
                    st.markdown(f"## 🏗️ {zone_name}STRUCTURE")
                    
                    # On ne garde que les lignes de cette zone
                    df_zone = df_target[df_target["Zone"] == zone_name]
                    
                    if not df_zone.empty:
                        for _, row in df_zone.iterrows():
                            # Affichage Propre
                            st.markdown(f"### {row['Designation']}") # Ex: "VOILES"
                            
                            c1, c2, c3 = st.columns(3)
                            prevu = row['Prevu (m3)']
                            reel = row['Volume Reel']
                            delta = prevu - reel
                            
                            c1.metric("Budget", f"{prevu:.2f} m³")
                            c2.metric("Consommé (Cumul)", f"{reel:.2f} m³")
                            
                            # Couleur : Vert si on a du rab, Rouge si on a dépassé
                            c3.metric("Reste / Écart", f"{delta:.2f} m³", delta=f"{delta:.2f} m³", delta_color="normal")
                            st.divider()
                    else:
                        st.info(f"Aucun budget défini en {zone_name}.")
                    st.write("") 
            else:
                st.warning("Veuillez définir vos catégories (Voiles, Dalles...) dans l'onglet Prévisionnel.")
                
    else:
        st.error("Fichier introuvable.")
