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

# LISTE STANDARD POUR INITIALISATION
STANDARD_ITEMS = [
    {"Designation": "Pieux / Micropieu", "Zone": "INFRA"},
    {"Designation": "Fondation", "Zone": "INFRA"},
    {"Designation": "Semelle", "Zone": "INFRA"},
    {"Designation": "Longrine", "Zone": "INFRA"},
    {"Designation": "Voile", "Zone": "INFRA"},
    {"Designation": "Poteau", "Zone": "INFRA"},
    {"Designation": "Poutre", "Zone": "INFRA"},
    {"Designation": "Dalle", "Zone": "INFRA"},
    {"Designation": "Voile", "Zone": "SUPER"},
    {"Designation": "Poteau", "Zone": "SUPER"},
    {"Designation": "Poutre", "Zone": "SUPER"},
    {"Designation": "Dalle", "Zone": "SUPER"},
    {"Designation": "Acrotère", "Zone": "SUPER"},
    {"Designation": "Édicule", "Zone": "SUPER"},
]

st.set_page_config(page_title="Suivi béton", layout="wide")

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
    
    prompt_complet = prompt + ". Ajoute une colonne 'Doute' (boolean) : mets true si le texte est difficile à lire, flou ou si tu n'es pas sûr d'un mot. Sinon false."
    
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt_complet}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        "temperature": 0
    }
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload).json()
    try:
        usage = r.get('usage', {})
        cout = (usage.get('prompt_tokens', 0) * 0.0000025) + (usage.get('completion_tokens', 0) * 0.000010)
        st.toast(f"💰 Coût : {cout:.4f} $")
    except: pass

    try:
        txt = r['choices'][0]['message']['content'].strip()
        if txt.startswith("```"): txt = txt.split("```")[1].replace("json", "").strip()
        return pd.DataFrame(json.loads(txt))
    except:
        return pd.DataFrame()

def detecter_zone_automatique(texte):
    texte = str(texte).lower().strip()
    mots_infra = ["r-", "s-sol", "sous-sol", "fondation", "radier", "pieux", "semelle", "longrine", "infra"]
    for mot in mots_infra:
        if mot in texte:
            return "INFRA"
    return "SUPER"

# --- MODIFICATION : AJOUT DU PARAMETRE col_scan ---
def verifier_correspondance_budget(df_scan, df_budget, col_scan="Designation"):
    """
    Compare la colonne spécifiée (col_scan) du scan avec la bibliothèque du budget.
    Coche la case 'Doute' si aucune correspondance n'est trouvée.
    """
    library = df_budget["Designation"].astype(str).str.strip().str.lower().unique().tolist()
    
    if "Doute" not in df_scan.columns:
        df_scan["Doute"] = False

    termes_inconnus = []

    for index, row in df_scan.iterrows():
        # ON UTILISE LA COLONNE SPECIFIEE ICI (ex: "Type de Beton")
        valeur_scan = str(row.get(col_scan, "")).strip().lower()
        valeur_scan_sing = valeur_scan[:-1] if valeur_scan.endswith('s') else valeur_scan
        
        match_found = False
        
        for ref in library:
            ref_sing = ref[:-1] if ref.endswith('s') else ref
            if valeur_scan == ref or valeur_scan_sing == ref_sing:
                match_found = True
                break
        
        if not match_found:
            df_scan.at[index, "Doute"] = True
            # On ajoute le terme de la colonne scannée à la liste des inconnus
            termes_inconnus.append(row.get(col_scan, "Inconnu"))
            
    return df_scan, termes_inconnus

# --- 4. INTERFACE ---
if 'page' not in st.session_state: st.session_state.page = "Accueil"
if 'relecture' not in st.session_state: st.session_state.relecture = None
if 'termes_inconnus' not in st.session_state: st.session_state.termes_inconnus = []

st.markdown('<h1 style="color:#E67E22; text-align:center;">GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    col_titre, col_refresh = st.columns([8, 2])
    with col_titre: st.subheader("Mes Projets")
    with col_refresh:
        if st.button("🔄 Actualiser", width='stretch', key="refresh_home"): st.rerun()

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
    
    col_titre_c, col_act_c, col_ret_c = st.columns([6, 2, 2])
    with col_titre_c:
        st.header(f"📍 {nom_c}")
    with col_act_c:
        if st.button("🔄 Actualiser", key="refresh_site", width='stretch'):
            st.rerun()
    with col_ret_c:
        if st.button("⬅ Retour", key="back_home", width='stretch'):
            st.session_state.page = "Accueil"
            st.session_state.relecture = None
            st.session_state.termes_inconnus = []
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
                        cols_temp = ["Doute"] + COLS_BETON 
                        res = res.reindex(columns=cols_temp)
                        
                        # --- MODIFICATION ICI : Appel avec "Type de Beton" ---
                        res, inconnus = verifier_correspondance_budget(res, df_prev, col_scan="Type de Beton")
                        st.session_state.termes_inconnus = inconnus
                        # -----------------------------------------------------
                        
                        st.session_state.relecture = res
                        st.rerun()
                        
            if st.session_state.relecture is not None:
                if st.session_state.termes_inconnus:
                    st.warning(f"⚠️ Termes inconnus détectés (Type de Béton) : {', '.join(set(st.session_state.termes_inconnus))}. Veuillez corriger les lignes cochées.")
                else:
                    st.info("Vérifiez les lignes.")

                df_m = st.data_editor(
                    st.session_state.relecture, 
                    key="edit_b",
                    disabled=["Doute"],
                    use_container_width=True,
                    column_config={
                        "Doute": st.column_config.CheckboxColumn("⚠️", default=False, width="small"),
                        "Fournisseur": st.column_config.TextColumn("Fournisseur", width="medium"),
                        "Designation": st.column_config.TextColumn("Désignation", width="large"),
                        "Type de Beton": st.column_config.TextColumn("Type de Beton", width="medium"),
                        "Volume (m3)": st.column_config.NumberColumn("Volume (m3)", width="medium"),
                    }
                )
                if st.button("Valider et Sauvegarder", key="save_b"):
                    df_clean = df_m.drop(columns=["Doute"], errors="ignore")
                    sheets["Beton"] = pd.concat([df_beton, df_clean], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.session_state.termes_inconnus = []
                    st.rerun()
            st.divider()
            st.dataframe(df_beton, width='stretch')

        with tab2:
            up_a = st.file_uploader("Bon acier", type=['jpg','png','heic'], key="up_a")
            if up_a and st.session_state.relecture is None:
                if st.button("Envoyer Bon", key="btn_a", type="primary"):
                    with st.spinner("IA en cours..."):
                        res = analyser_ia(up_a, OPENAI_API_KEY, f"Donnees acier JSON. Colonnes: {COLS_ACIER}")
                        cols_temp = ["Doute"] + COLS_ACIER
                        res = res.reindex(columns=cols_temp)
                        
                        # Ici on garde "Designation" par défaut car "Type de Beton" n'existe pas pour l'acier
                        res, inconnus = verifier_correspondance_budget(res, df_prev, col_scan="Designation")
                        st.session_state.termes_inconnus = inconnus

                        st.session_state.relecture = res
                        st.rerun()
            if st.session_state.relecture is not None:
                if st.session_state.termes_inconnus:
                    st.warning(f"⚠️ Termes inconnus détectés : {', '.join(set(st.session_state.termes_inconnus))}. Veuillez corriger les lignes cochées.")
                else:
                    st.info("Vérifiez les lignes.")
                    
                df_m = st.data_editor(
                    st.session_state.relecture, 
                    key="edit_a",
                    disabled=["Doute"],
                    use_container_width=True,
                    column_config={
                        "Doute": st.column_config.CheckboxColumn("⚠️", default=False, width="small"),
                        "Fournisseur": st.column_config.TextColumn("Fournisseur", width="medium"),
                        "Designation": st.column_config.TextColumn("Désignation", width="large"),
                        "Poids (kg)": st.column_config.NumberColumn("Poids (kg)", width="medium"),
                    }
                )
                if st.button("Valider et Sauvegarder", key="save_a"):
                    df_clean = df_m.drop(columns=["Doute"], errors="ignore")
                    sheets["Acier"] = pd.concat([df_acier, df_clean], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.session_state.termes_inconnus = []
                    st.rerun()
            st.divider()
            st.dataframe(df_acier, width='stretch')

        with tab3:
            col_custom, col_standard = st.columns([1, 1])
            
            with col_custom:
                st.subheader("Ajout Personnalisé")
                with st.form("ajout_prev"):
                    st.caption("Pour ajouter un élément hors liste standard.")
                    new_des = st.text_input("Désignation")
                    new_vol = st.number_input("Volume Prévu (m3)", step=1.0)
                    new_zone = st.radio("Zone", ["INFRA", "SUPER"], horizontal=True)
                    submitted = st.form_submit_button("Ajouter (+)")
                    
                    if submitted and new_des:
                        new_row = pd.DataFrame([{"Designation": new_des, "Prevu (m3)": new_vol, "Zone": new_zone}])
                        sheets["Previsionnel"] = pd.concat([df_prev, new_row], ignore_index=True)
                        sauvegarder_excel_github(sheets, path_f, sha)
                        st.rerun()

            with col_standard:
                st.subheader("Grille de Saisie Standard")
                
                if not df_prev.empty:
                    df_prev["_key"] = df_prev["Designation"].astype(str) + "_" + df_prev["Zone"].astype(str)
                    existing_keys = df_prev["_key"].tolist()
                    
                    rows_to_add = []
                    for item in STANDARD_ITEMS:
                        key = item["Designation"] + "_" + item["Zone"]
                        if key not in existing_keys:
                            rows_to_add.append({"Designation": item["Designation"], "Prevu (m3)": 0.0, "Zone": item["Zone"]})
                    
                    if rows_to_add:
                        new_standard_df = pd.DataFrame(rows_to_add)
                        df_prev = pd.concat([df_prev, new_standard_df], ignore_index=True)
                        if "_key" in df_prev.columns: df_prev = df_prev.drop(columns=["_key"])
                        sheets["Previsionnel"] = df_prev
                        sauvegarder_excel_github(sheets, path_f, sha)
                        st.rerun()
                    
                    if "_key" in df_prev.columns: df_prev = df_prev.drop(columns=["_key"])

                else:
                    df_prev = pd.DataFrame(STANDARD_ITEMS)
                    df_prev["Prevu (m3)"] = 0.0
                    sheets["Previsionnel"] = df_prev
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.rerun()

                st.markdown("### INFRA")
                df_infra = df_prev[df_prev["Zone"] == "INFRA"].sort_values(by="Designation")
                
                edited_infra = st.data_editor(
                    df_infra,
                    key="edit_infra",
                    use_container_width=True,
                    disabled=["Designation", "Zone"], 
                    hide_index=True,
                    column_config={
                        "Designation": st.column_config.TextColumn("Elément", width="medium"),
                        "Zone": None, 
                        "Prevu (m3)": st.column_config.NumberColumn("Quantité (m3)", width="small", required=True),
                    }
                )

                st.markdown("### SUPER")
                df_super = df_prev[df_prev["Zone"] == "SUPER"].sort_values(by="Designation")
                
                edited_super = st.data_editor(
                    df_super,
                    key="edit_super",
                    use_container_width=True,
                    disabled=["Designation", "Zone"], 
                    hide_index=True,
                    column_config={
                        "Designation": st.column_config.TextColumn("Elément", width="medium"),
                        "Zone": None, 
                        "Prevu (m3)": st.column_config.NumberColumn("Quantité (m3)", width="small", required=True),
                    }
                )

                if st.button("Enregistrer les Quantités", key="save_std_list", type="primary"):
                    df_others = df_prev[~df_prev["Zone"].isin(["INFRA", "SUPER"])]
                    df_final_prev = pd.concat([edited_infra, edited_super, df_others], ignore_index=True)
                    sheets["Previsionnel"] = df_final_prev
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.success("Budget mis à jour !")
                    st.rerun()

        with tab4:
            st.subheader("Bilan consolidé par Zone et Famille")
            if not df_prev.empty:
                df_calc = df_beton.copy()
                df_calc["Volume (m3)"] = pd.to_numeric(df_calc["Volume (m3)"], errors='coerce').fillna(0)
                df_calc["Designation"] = df_calc["Designation"].astype(str).str.strip()

                df_target = df_prev.copy()
                df_target["Prevu (m3)"] = pd.to_numeric(df_target["Prevu (m3)"], errors='coerce').fillna(0)
                if "Zone" not in df_target.columns: df_target["Zone"] = "INFRA"
                df_target["Zone"] = df_target["Zone"].fillna("INFRA")
                
                df_target["Volume Reel"] = 0.0
                
                for _, row_reel in df_calc.iterrows():
                    nom_reel = row_reel["Designation"] 
                    vol_reel = row_reel["Volume (m3)"]
                    zone_du_bon = detecter_zone_automatique(nom_reel)
                    
                    for idx_prev, row_prev in df_target.iterrows():
                        mot_cle_budget = str(row_prev["Designation"]).lower().strip()
                        zone_budget = row_prev["Zone"]
                        
                        if zone_du_bon == zone_budget:
                            if mot_cle_budget in nom_reel.lower():
                                df_target.at[idx_prev, "Volume Reel"] += vol_reel
                                break 
                
                for zone_name in ["INFRA", "SUPER"]:
                    st.markdown(f"## 🏗️ {zone_name}STRUCTURE")
                    df_zone = df_target[df_target["Zone"] == zone_name]
                    df_zone_active = df_zone[(df_zone["Prevu (m3)"] > 0) | (df_zone["Volume Reel"] > 0)]
                    
                    if not df_zone_active.empty:
                        for _, row in df_zone_active.iterrows():
                            st.markdown(f"<div style='font-size: 15px; font-weight: bold; color: #E67E22; margin-bottom: 3px;'>{row['Designation']}</div>", unsafe_allow_html=True)
                            
                            c1, c2, c3 = st.columns(3)
                            prevu = row['Prevu (m3)']
                            reel = row['Volume Reel']
                            delta = prevu - reel
                            
                            c1.metric("Budget", f"{prevu:.2f} m³")
                            c2.metric("Consommé", f"{reel:.2f} m³")
                            c3.metric("Reste", f"{delta:.2f} m³", delta=f"{delta:.2f} m³", delta_color="normal")
                            
                            st.markdown("<hr style='margin: 3px 0; border: none; border-top: 1px solid #444;'>", unsafe_allow_html=True)
                    else:
                        st.info(f"Aucun élément actif en {zone_name}.")
                    st.write("") 
            else:
                st.warning("Initialisation du budget en cours...")
                
    else:
        st.error("Fichier introuvable.")
