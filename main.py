import streamlit as st
import pandas as pd
import base64
import requests
import json
import io
import unicodedata
from github import Github, Auth
from PIL import Image
import pillow_heif
from datetime import datetime
from fpdf import FPDF
import xlsxwriter
import google.generativeai as genai

# --- 1. CONFIGURATION GITHUB ET OPENAI (Via Secrets) ---
try:
    GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
    REPO_NAME = st.secrets.get("REPO_NAME", "")
    GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")
    # Récupération du mot de passe Admin
    ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123") 
    
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
COLS_ETUDE_ACIER = ["Designation", "Acier HA", "Acier TS", "Zone"]

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
    {"Designation": "Plancher Haut", "Zone": "INFRA"},
    {"Designation": "Voile", "Zone": "SUPER"},
    {"Designation": "Poteau", "Zone": "SUPER"},
    {"Designation": "Poutre", "Zone": "SUPER"},
    {"Designation": "Dalle", "Zone": "SUPER"},
    {"Designation": "Acrotère", "Zone": "SUPER"},
    {"Designation": "Édicule", "Zone": "SUPER"},
    {"Designation": "Plancher Haut", "Zone": "SUPER"},
    {"Designation": "Balcons", "Zone": "SUPER"},
    {"Designation": "Divers", "Zone": "SUPER"},
]

st.set_page_config(page_title="Suivi béton", layout="wide")

# --- AJOUT CSS GLOBAL (COULEURS & MOBILE) ---
st.markdown("""
<style>
    /* 1. Fond du site */
    .stApp {
        background-color: #FFEBD1;
    }
    
    /* 2. Textes en gras, Titres (h1, h2, h3) */
    h1, h2, h3, h4, h5, h6, strong, b {
        color: #001724 !important;
    }
    
    /* 3. Boutons (Primaires et Secondaires) */
    div.stButton > button {
        background-color: #FF7A00 !important;
        color: white !important;
        border: none !important;
    }
    div.stButton > button:hover {
        background-color: #E66A00 !important;
        color: white !important;
    }
    
    /* 4. Onglets (Tabs) */
    .stTabs [data-baseweb="tab"] {
        color: #001724; 
    }
    .stTabs [data-baseweb="tab-highlight"] {
        background-color: #15676D !important;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: #15676D !important;
        font-weight: bold;
    }

    /* 5. Sidebar (Optionnel pour harmoniser) */
    [data-testid="stSidebar"] {
        background-color: #FFF5E6; 
    }

    /* Gestion Mobile */
    @media (max-width: 640px) {
        .mobile-hide {
            display: none !important;
            height: 0px !important;
            margin: 0px !important;
        }
    }
</style>
""", unsafe_allow_html=True)

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

def recuperer_fichier_github(path):
    try:
        content = repo.get_contents(path)
        return content.decoded_content
    except: return None

def sauvegarder_scan_github(uploaded_file, nom_chantier, type_doc):
    try:
        now = datetime.now()
        date_str = now.strftime("%d-%m-%Y") 
        heure_str = now.strftime("%H-%M-%S")
        ext = uploaded_file.name.split('.')[-1].lower()
        nom_clean = remove_accents(nom_chantier).replace(" ", "_")
        new_filename = f"{date_str} -- {nom_clean} -- {heure_str}.{ext}"
        folder_type = "SCANS_BETON" if "eton" in type_doc else "SCANS_ACIER"
        path_github = f"{BASE_DIR}/{nom_chantier}/{folder_type}/{new_filename}"
        repo.create_file(path_github, f"Ajout scan {type_doc}", uploaded_file.getvalue())
        return True
    except Exception as e:
        print(f"Erreur sauvegarde scan: {e}")
        return False

def analyser_ia(uploaded_file, api_key, prompt):
    if not api_key:
        st.error("La clé Google API est manquante.")
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        st.error(f"Erreur config Gemini: {e}")
        return pd.DataFrame()
    try:
        file_ext = uploaded_file.name.lower()
        if file_ext.endswith('.heic'):
            heif_file = pillow_heif.read_heif(uploaded_file)
            image = Image.frombytes(heif_file.mode, heif_file.size, heif_file.data, "raw")
        else:
            image = Image.open(uploaded_file)
    except Exception as e:
        st.error(f"Erreur lecture image : {e}")
        return pd.DataFrame()
    prompt_complet = (
        f"{prompt}. "
        "Ajoute une colonne 'Doute' (boolean) : mets true si incertain, sinon false. "
        "Retourne UNIQUEMENT une liste JSON brute compatible Python, sans balises markdown ```json ou ```."
    )
    try:
        response = model.generate_content([prompt_complet, image])
        txt = response.text.strip()
        if txt.startswith("```json"): txt = txt.split("```json")[1]
        if txt.startswith("```"): txt = txt.split("```")[1]
        if txt.endswith("```"): txt = txt[:-3]
        data = json.loads(txt)
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Erreur analyse IA : {e}")
        return pd.DataFrame()

def remove_accents(input_str):
    if not isinstance(input_str, str): return str(input_str)
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def detecter_zone_automatique(texte):
    texte = remove_accents(str(texte).lower().strip())
    mots_infra = ["r-", "s-sol", "sous-sol", "fondation", "radier", "pieux", "semelle", "longrine", "infra", "gros beton"]
    for mot in mots_infra:
        if mot in texte:
            return "INFRA"
    return "SUPER"

def appliquer_correction_u(df, colonnes_a_verifier):
    for col in colonnes_a_verifier:
        if col in df.columns:
            for i in range(1, len(df)):
                valeur_actuelle = str(df.at[i, col]).strip()
                declencheurs = ["u", "U", '"']
                if valeur_actuelle in declencheurs:
                    df.at[i, col] = df.at[i-1, col]
    return df

def verifier_correspondance_budget(df_scan, df_budget, col_scan="Designation"):
    library = [remove_accents(str(x).strip().lower()) for x in df_budget["Designation"].unique()]
    if "Doute" not in df_scan.columns:
        df_scan["Doute"] = False
    termes_inconnus = []
    for index, row in df_scan.iterrows():
        valeur_scan = remove_accents(str(row.get(col_scan, "")).strip().lower())
        valeur_scan_sing = valeur_scan[:-1] if valeur_scan.endswith('s') else valeur_scan
        match_found = False
        for ref in library:
            ref_sing = ref[:-1] if ref.endswith('s') else ref
            if valeur_scan == ref or valeur_scan_sing == ref_sing:
                match_found = True
                break
        if not match_found:
            df_scan.at[index, "Doute"] = True
            termes_inconnus.append(row.get(col_scan, "Inconnu"))
    return df_scan, termes_inconnus

def generer_excel_stylise(dfs_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        for sheet_name, df in dfs_dict.items():
            if df.empty: continue
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            (max_row, max_col) = df.shape
            column_settings = [{'header': column} for column in df.columns]
            worksheet.add_table(0, 0, max_row, max_col - 1, {'columns': column_settings, 'style': 'TableStyleMedium2', 'name': f"Table_{remove_accents(sheet_name).replace(' ', '_')}"})
            for i, col in enumerate(df.columns):
                max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, max_len)
    return output.getvalue()

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'RECAPITULATIF CHANTIER', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generer_pdf_recap(df_target, nom_chantier):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Chantier : {nom_chantier}", 0, 1, 'L')
    pdf.cell(0, 10, f"Date : {datetime.now().strftime('%d/%m/%Y')}", 0, 1, 'L')
    pdf.ln(5)
    for zone in ["INFRA", "SUPER"]:
        pdf.set_font("Arial", 'B', 14)
        pdf.set_fill_color(230, 126, 34)
        pdf.cell(0, 10, f"{zone}STRUCTURE", 0, 1, 'L', fill=False)
        pdf.ln(2)
        df_zone = df_target[df_target["Zone"] == zone]
        df_active = df_zone[(df_zone["Prevu (m3)"] > 0) | (df_zone["Volume Reel"] > 0) | (df_zone.get("Etude (m3)", 0) > 0)]
        if df_active.empty:
            pdf.set_font("Arial", 'I', 10)
            pdf.cell(0, 10, "Aucune donnée.", 0, 1)
        else:
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(50, 8, "Désignation", 1)
            pdf.cell(30, 8, "Budget", 1, 0, 'C')
            pdf.cell(30, 8, "Conso", 1, 0, 'C')
            pdf.cell(30, 8, "Etude", 1, 0, 'C')
            pdf.cell(30, 8, "Reste", 1, 0, 'C')
            pdf.cell(20, 8, "%", 1, 1, 'C')
            pdf.set_font("Arial", size=10)
            for _, row in df_active.iterrows():
                nom = str(row['Designation']).encode('latin-1', 'replace').decode('latin-1')
                prev = row['Prevu (m3)']
                reel = row['Volume Reel']
                etude = row.get('Etude (m3)', 0.0)
                delta = prev - reel 
                pct = (reel / prev * 100) if prev > 0 else 0.0
                pdf.cell(50, 8, nom, 1)
                pdf.cell(30, 8, f"{prev:.1f}", 1, 0, 'C')
                pdf.cell(30, 8, f"{reel:.1f}", 1, 0, 'C')
                pdf.cell(30, 8, f"{etude:.1f}", 1, 0, 'C')
                if delta < 0:
                    pdf.set_text_color(255, 0, 0)
                else:
                    pdf.set_text_color(0, 0, 0)
                pdf.cell(30, 8, f"{delta:.1f}", 1, 0, 'C')
                pdf.cell(20, 8, f"{pct:.0f}%", 1, 1, 'C')
                pdf.set_text_color(0, 0, 0)
        pdf.ln(5)
    return pdf.output(dest='S').encode('latin-1')

# --- 4. INTERFACE ---
if 'page' not in st.session_state: st.session_state.page = "Accueil"
if 'relecture' not in st.session_state: st.session_state.relecture = None
if 'termes_inconnus' not in st.session_state: st.session_state.termes_inconnus = []
if 'is_admin' not in st.session_state: st.session_state.is_admin = False

# --- BARRE LATERALE (CONNEXION ADMIN) ---
with st.sidebar:
    # CORRECTION ICI : URL BRUTE, SANS MARKDOWN
    st.image("[https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python_logo_notext.svg/110px-Python_logo_notext.svg.png](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python_logo_notext.svg/110px-Python_logo_notext.svg.png)", width=50) 
    st.write("### Menu")
    with st.expander("🔐 Administration"):
        pwd_input = st.text_input("Mot de passe", type="password", key="admin_pwd")
        if pwd_input:
            if pwd_input == ADMIN_PASSWORD:
                st.session_state.is_admin = True
                st.success("Mode Admin activé")
            else:
                st.session_state.is_admin = False
                st.error("Mot de passe incorrect")
        else:
            st.session_state.is_admin = False

st.markdown('<h1 style="color:#FF7A00; text-align:center;">GESTION ITB77</h1>', unsafe_allow_html=True)

if st.session_state.page == "Accueil":
    col_titre, col_suivi, col_refresh = st.columns([6, 2, 2])
    with col_titre: st.subheader("Mes Projets")
    with col_suivi:
        pdf_suivi = recuperer_fichier_github("Suivi béton ITB.pdf")
        if pdf_suivi:
            st.download_button("📄 Feuille de suivi", pdf_suivi, "Suivi_beton_ITB.pdf", "application/pdf", key="dl_suivi_home", use_container_width=True)
        else:
            st.warning("PDF introuvable")
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
                d = {
                    "Beton": pd.DataFrame(columns=COLS_BETON), 
                    "Acier": pd.DataFrame(columns=COLS_ACIER), 
                    "Previsionnel": pd.DataFrame(columns=COLS_PREV),
                    "Etude_Beton": pd.DataFrame(columns=["Designation", "Etude (m3)", "Zone"]),
                    "Etude_Acier": pd.DataFrame(columns=COLS_ETUDE_ACIER)
                }
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
        # --- GESTION DES ONGLETS AVEC ADMIN ---
        onglets = ["Récapitulatif", "Béton", "Acier", "Prévisionnel", "Étude"]
        if st.session_state.is_admin:
            onglets.append("⚙️ Admin")
            
        all_tabs = st.tabs(onglets)
        
        # On récupère les onglets standards
        tab_recap, tab_beton, tab_acier, tab_prev, tab_etude = all_tabs[:5]
        
        df_beton = sheets.get("Beton", pd.DataFrame(columns=COLS_BETON))
        if df_beton.empty: df_beton = pd.DataFrame(columns=COLS_BETON)
        
        df_acier = sheets.get("Acier", pd.DataFrame(columns=COLS_ACIER))
        if df_acier.empty: df_acier = pd.DataFrame(columns=COLS_ACIER)

        df_prev = sheets.get("Previsionnel", pd.DataFrame(columns=COLS_PREV))
        if not df_prev.empty and "Zone" not in df_prev.columns:
            df_prev["Zone"] = "INFRA"
        if df_prev.empty: df_prev = pd.DataFrame(columns=COLS_PREV)

        df_etude_beton = sheets.get("Etude_Beton", pd.DataFrame(columns=["Designation", "Etude (m3)", "Zone"]))
        df_etude_acier = sheets.get("Etude_Acier", pd.DataFrame(columns=COLS_ETUDE_ACIER))

        # --- CALCUL DU RECAP ---
        df_recap_final = pd.DataFrame()
        if not df_prev.empty:
            df_calc = df_beton.copy()
            df_calc["Volume (m3)"] = pd.to_numeric(df_calc["Volume (m3)"], errors='coerce').fillna(0)
            
            df_target = df_prev.copy()
            df_target["Prevu (m3)"] = pd.to_numeric(df_target["Prevu (m3)"], errors='coerce').fillna(0)
            if "Zone" not in df_target.columns: df_target["Zone"] = "INFRA"
            df_target["Zone"] = df_target["Zone"].fillna("INFRA")
            df_target["Volume Reel"] = 0.0
            
            df_etude_val = df_etude_beton.copy()
            if not df_etude_val.empty and "Etude (m3)" in df_etude_val.columns:
                df_etude_val["Etude (m3)"] = pd.to_numeric(df_etude_val["Etude (m3)"], errors='coerce').fillna(0)
            else:
                df_etude_val["Etude (m3)"] = 0.0
            
            fondation_details = {}

            for _, row_reel in df_calc.iterrows():
                nom_reel = str(row_reel["Designation"]).strip()
                type_reel = str(row_reel.get("Type de Beton", "")).strip()
                vol_reel = row_reel["Volume (m3)"]
                texte_pour_zone = nom_reel + " " + type_reel
                zone_du_bon = detecter_zone_automatique(texte_pour_zone)
                nom_reel_clean = remove_accents(nom_reel.lower())
                type_reel_clean = remove_accents(type_reel.lower())
                for idx_prev, row_prev in df_target.iterrows():
                    nom_budget_raw = str(row_prev["Designation"]).strip()
                    mot_cle_budget = remove_accents(nom_budget_raw.lower())
                    zone_budget = row_prev["Zone"]
                    if zone_du_bon == zone_budget:
                        if mot_cle_budget in nom_reel_clean or mot_cle_budget in type_reel_clean:
                            df_target.at[idx_prev, "Volume Reel"] += vol_reel
                            if mot_cle_budget == "fondation":
                                type_beton_reel = row_reel.get("Type de Beton", "Non spécifié")
                                if type_beton_reel not in fondation_details:
                                    fondation_details[type_beton_reel] = 0.0
                                fondation_details[type_beton_reel] += vol_reel
                            break 
            
            df_target = pd.merge(df_target, df_etude_val[["Designation", "Zone", "Etude (m3)"]], on=["Designation", "Zone"], how="left").fillna(0)
            df_target["Reste (m3)"] = df_target["Prevu (m3)"] - df_target["Volume Reel"]
            df_target["Avancement (%)"] = df_target.apply(lambda x: (x["Volume Reel"] / x["Prevu (m3)"] * 100) if x["Prevu (m3)"] > 0 else 0, axis=1)
            df_recap_final = df_target

        # --- 1. RÉCAPITULATIF ---
        with tab_recap:
            col_titre_recap, col_dl_recap = st.columns([8.5, 1.5])
            with col_titre_recap:
                st.subheader("Bilan consolidé par Zone et Famille")
            
            with col_dl_recap:
                c_pdf, c_xls = st.columns(2)
                with c_pdf:
                    pdf_bytes = generer_pdf_recap(df_recap_final, nom_c)
                    st.download_button("📥 PDF", pdf_bytes, f"Recap_{nom_c}.pdf", "application/pdf", use_container_width=True)
                with c_xls:
                    data_export = {
                        "Récapitulatif": df_recap_final,
                        "Béton": df_beton,
                        "Acier": df_acier,
                        "Prévisionnel": df_prev,
                        "Étude Béton": df_etude_beton,
                        "Étude Acier": df_etude_acier
                    }
                    xls_bytes = generer_excel_stylise(data_export)
                    st.download_button("📥 Excel", xls_bytes, f"Donnees_{nom_c}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            for zone_name in ["INFRA", "SUPER"]:
                st.markdown(f"## 🏗️ {zone_name}STRUCTURE")
                df_zone = df_recap_final[df_recap_final["Zone"] == zone_name]
                df_zone_active = df_zone[(df_zone["Prevu (m3)"] > 0) | (df_zone["Volume Reel"] > 0) | (df_zone.get("Etude (m3)", 0) > 0)]
                
                if not df_zone_active.empty:
                    for _, row in df_zone_active.iterrows():
                        st.markdown(f"<div style='font-size: 15px; font-weight: bold; color: #E67E22; margin-bottom: 3px;'>{row['Designation']}</div>", unsafe_allow_html=True)
                        
                        # --- MODIFICATION LAYOUT (ESPACES RÉDUITS AU CENTRE) ---
                        col_left, col_void, col_sep, col_right = st.columns([6.5, 0.2, 0.3, 3])
                        
                        prevu = row['Prevu (m3)']
                        reel = row['Volume Reel']
                        etude_val = row.get('Etude (m3)', 0.0)
                        
                        # Diff = Reel - Prevu
                        diff = reel - prevu
                        
                        pct = (reel / prevu * 100) if prevu > 0 else 0.0
                        
                        with col_left:
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Budget", f"{prevu:.2f} m³")
                            c2.metric("Consommé", f"{reel:.2f} m³")
                            c3.metric("Étude", f"{etude_val:.2f} m³")
                        
                        with col_void:
                            st.markdown('<div class="mobile-hide" style="height: 10px;"></div>', unsafe_allow_html=True)
                        
                        with col_sep:
                            st.markdown("""<div class="mobile-hide" style="border-left: 4px solid #E67E22; height: 60px; margin-left: 50%;"></div>""", unsafe_allow_html=True)
                        
                        str_extra_pct = "" 
                        if diff > 0:
                            color_reste = "#FF4B4B" # Rouge
                            color_pct = "#FF4B4B"
                            pct_extra = (diff / prevu * 100) if prevu > 0 else 0.0
                            str_extra_pct = f" <span style='font-size:0.7em'>(+{pct_extra:.1f}%)</span>"
                        else:
                            color_reste = "inherit" # Couleur standard
                            color_pct = "inherit"
                        
                        with col_right:
                            st.markdown("""<div style="text-align: center; font-size: 12px; font-weight: bold; margin-bottom: 2px;">Écart Conso / Prévi</div><div style="border-top: 3px solid #1E90FF; margin-bottom: 10px;"></div>""", unsafe_allow_html=True)
                            
                            # --- 2 COLONNES : RESTE A GAUCHE, AVANCEMENT A DROITE ---
                            c4, c5 = st.columns(2)
                            
                            # C4 : RESTE
                            html_reste = f"""<div style="font-family: 'Source Sans Pro', sans-serif;"><div style="font-size: 14px; color: rgba(250, 250, 250, 0.6);">Reste</div><div style="font-size: 20px; font-weight: 600; color: {color_reste};">{diff:+.2f} m³</div></div>"""
                            c4.markdown(html_reste, unsafe_allow_html=True)
                            
                            # C5 : AVANCEMENT (AVEC LE % AJOUTÉ EN BOUT DE LIGNE)
                            html_pct = f"""<div style="font-family: 'Source Sans Pro', sans-serif;"><div style="font-size: 14px; color: rgba(250, 250, 250, 0.6);">Avancement</div><div style="font-size: 20px; font-weight: 600; color: {color_pct};">{pct:.1f} %{str_extra_pct}</div></div>"""
                            c5.markdown(html_pct, unsafe_allow_html=True)
                        
                        st.markdown("<hr style='margin: 3px 0; border: none; border-top: 1px solid #444;'>", unsafe_allow_html=True)
                else:
                    st.info(f"Aucun élément actif en {zone_name}.")
                st.write("") 
        
        # --- 2. BÉTON ---
        with tab_beton:
            up_b = st.file_uploader("Scan Bon Beton", type=['jpg','png','heic'], key="up_b")
            if up_b and st.session_state.relecture is None:
                if st.button("Envoyer Bon", key="btn_b", type="primary"):
                    with st.spinner("IA en cours..."):
                        res = analyser_ia(up_b, GOOGLE_API_KEY, f"Donnees beton JSON. Colonnes: {COLS_BETON}")
                        cols_temp = ["Doute"] + COLS_BETON 
                        res = res.reindex(columns=cols_temp)
                        res = appliquer_correction_u(res, ["Designation", "Type de Beton"])
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
                    # SAUVEGARDE PHOTO SUR GITHUB
                    if up_b is not None:
                        sauvegarder_scan_github(up_b, nom_c, "Béton")
                        
                    df_clean = df_m.drop(columns=["Doute"], errors="ignore")
                    sheets["Beton"] = pd.concat([df_beton, df_clean], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.session_state.termes_inconnus = []
                    st.rerun()
            st.divider()
            st.dataframe(df_beton, width='stretch')

        # --- 3. ACIER ---
        with tab_acier:
            up_a = st.file_uploader("Bon acier", type=['jpg','png','heic'], key="up_a")
            if up_a and st.session_state.relecture is None:
                if st.button("Envoyer Bon", key="btn_a", type="primary"):
                    with st.spinner("IA en cours..."):
                        res = analyser_ia(up_a, GOOGLE_API_KEY, f"Donnees acier JSON. Colonnes: {COLS_ACIER}")
                        cols_temp = ["Doute"] + COLS_ACIER
                        res = res.reindex(columns=cols_temp)
                        res = appliquer_correction_u(res, ["Designation"])
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
                    # SAUVEGARDE PHOTO SUR GITHUB
                    if up_a is not None:
                        sauvegarder_scan_github(up_a, nom_c, "Acier")
                        
                    df_clean = df_m.drop(columns=["Doute"], errors="ignore")
                    sheets["Acier"] = pd.concat([df_acier, df_clean], ignore_index=True)
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.session_state.relecture = None
                    st.session_state.termes_inconnus = []
                    st.rerun()
            st.divider()
            st.dataframe(df_acier, width='stretch')

        # --- 4. PRÉVISIONNEL ---
        with tab_prev:
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
                    df_infra, key="edit_infra", use_container_width=True, disabled=["Designation", "Zone"], hide_index=True,
                    column_config={"Designation": st.column_config.TextColumn("Elément", width="medium"), "Zone": None, "Prevu (m3)": st.column_config.NumberColumn("Quantité (m3)", width="small", required=True)}
                )

                st.markdown("### SUPER")
                df_super = df_prev[df_prev["Zone"] == "SUPER"].sort_values(by="Designation")
                edited_super = st.data_editor(
                    df_super, key="edit_super", use_container_width=True, disabled=["Designation", "Zone"], hide_index=True,
                    column_config={"Designation": st.column_config.TextColumn("Elément", width="medium"), "Zone": None, "Prevu (m3)": st.column_config.NumberColumn("Quantité (m3)", width="small", required=True)}
                )

                if st.button("Enregistrer les Quantités", key="save_std_list", type="primary"):
                    df_others = df_prev[~df_prev["Zone"].isin(["INFRA", "SUPER"])]
                    df_final_prev = pd.concat([edited_infra, edited_super, df_others], ignore_index=True)
                    sheets["Previsionnel"] = df_final_prev
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.success("Budget mis à jour !")
                    st.rerun()

        # --- 5. ÉTUDE ---
        with tab_etude:
            col_b, col_a = st.columns(2)
            with col_b:
                st.markdown("### 🧱 Étude Béton")
                st.caption("Reprise des désignations du Prévisionnel")
                df_merge_beton = pd.merge(
                    df_prev[["Designation", "Zone"]], 
                    df_etude_beton, 
                    on=["Designation", "Zone"], 
                    how="left"
                ).fillna(0.0)
                edited_etude_beton = st.data_editor(
                    df_merge_beton,
                    key="edit_etude_beton",
                    use_container_width=True,
                    disabled=["Designation", "Zone"],
                    hide_index=True,
                    column_config={
                        "Designation": st.column_config.TextColumn("Désignation", width="medium"),
                        "Zone": st.column_config.TextColumn("Zone", width="small"),
                        "Etude (m3)": st.column_config.NumberColumn("Quantité (m3)", required=True)
                    }
                )
                if st.button("Sauvegarder Étude Béton", key="save_etude_beton"):
                    sheets["Etude_Beton"] = edited_etude_beton
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.success("Données Béton sauvegardées")

            with col_a:
                st.markdown("### ⛓️ Étude Acier")
                edited_etude_acier = st.data_editor(
                    df_etude_acier,
                    key="edit_etude_acier",
                    num_rows="dynamic",
                    use_container_width=True,
                    column_config={
                        "Designation": st.column_config.TextColumn("Désignation", width="medium"),
                        "Acier HA": st.column_config.NumberColumn("Acier HA (kg)", required=True),
                        "Acier TS": st.column_config.NumberColumn("Acier TS (kg)", required=True),
                        "Zone": st.column_config.SelectboxColumn("Zone", options=["INFRA", "SUPER"], width="small")
                    }
                )
                with st.form("ajout_etude_acier"):
                    st.write("Ajouter une ligne Acier")
                    c_form1, c_form2 = st.columns(2)
                    new_des_a = c_form1.text_input("Désignation")
                    new_zone_a = c_form2.radio("Zone", ["INFRA", "SUPER"], horizontal=True)
                    c_form3, c_form4 = st.columns(2)
                    new_ha = c_form3.number_input("Poids HA (kg)", step=1.0)
                    new_ts = c_form4.number_input("Poids TS (kg)", step=1.0)
                    if st.form_submit_button("Ajouter (+)") and new_des_a:
                        new_row_a = pd.DataFrame([{
                            "Designation": new_des_a, 
                            "Acier HA": new_ha, 
                            "Acier TS": new_ts, 
                            "Zone": new_zone_a
                        }])
                        df_etude_acier = pd.concat([edited_etude_acier, new_row_a], ignore_index=True)
                        sheets["Etude_Acier"] = df_etude_acier
                        sauvegarder_excel_github(sheets, path_f, sha)
                        st.rerun()
                if st.button("Sauvegarder Tableau Acier", key="save_etude_acier_global"):
                    sheets["Etude_Acier"] = edited_etude_acier
                    sauvegarder_excel_github(sheets, path_f, sha)
                    st.success("Données Acier sauvegardées")
        
        # --- 6. ADMIN (ONGLET CACHÉ) ---
        if st.session_state.is_admin:
            with all_tabs[5]:
                st.header("⚙️ Administration & Configurations")
                tab_pointage, tab_aco = st.tabs(["Pointages", "ACO"])

                with tab_pointage:
                    st.subheader("📸 Gestion des Pointages")
                    
                    path_pointages = f"{BASE_DIR}/{nom_c}/POINTAGES"
                    dossiers_existants = []
                    try:
                        contents = repo.get_contents(path_pointages)
                        dossiers_existants = [c.name for c in contents if c.type == "dir"]
                    except:
                        pass

                    # Nom du mois actuel
                    mois_map = {1:"Janvier", 2:"Fevrier", 3:"Mars", 4:"Avril", 5:"Mai", 6:"Juin", 7:"Juillet", 8:"Aout", 9:"Septembre", 10:"Octobre", 11:"Novembre", 12:"Decembre"}
                    now = datetime.now()
                    nom_dossier_actuel = f"{mois_map[now.month]}-{now.year}"

                    # --- LAYOUT ADMIN : COLONNE GAUCHE (MENU) / COLONNE DROITE (CONTENU) ---
                    col_nav, col_content = st.columns([1, 4]) 

                    with col_nav:
                        st.markdown("### 📂 Menu")
                        if st.button(f"➕ {nom_dossier_actuel}", use_container_width=True):
                            try:
                                repo.create_file(f"{path_pointages}/{nom_dossier_actuel}/.init", "Init", "")
                                st.success(f"Dossier {nom_dossier_actuel} créé !")
                                st.rerun()
                            except:
                                st.warning("Dossier existe déjà.")
                        
                        st.write("---")
                        
                        if not dossiers_existants:
                            st.info("Aucun dossier.")
                            choix_dossier = None
                        else:
                            # Liste sous forme de radio (agit comme un menu)
                            # On inverse pour avoir le plus récent en haut souvent
                            choix_dossier = st.radio("Mois :", options=dossiers_existants, label_visibility="collapsed")

                    with col_content:
                        if choix_dossier:
                            st.markdown(f"### 📁 {choix_dossier}")
                            path_img_folder = f"{path_pointages}/{choix_dossier}"
                            
                            # Upload
                            img_up = st.file_uploader("Ajouter une photo", type=['png', 'jpg', 'jpeg'])
                            if img_up:
                                if st.button("Sauvegarder la photo"):
                                    file_path = f"{path_img_folder}/{img_up.name}"
                                    try:
                                        repo.create_file(file_path, f"Add img {img_up.name}", img_up.getvalue())
                                        st.success("Photo envoyée !")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Erreur: {e}")

                            # Affichage Liste Fichiers (SANS IMAGE - JUSTE NOM ET BOUTONS)
                            st.divider()
                            st.write(f"Fichiers dans {choix_dossier} :")
                            try:
                                imgs = repo.get_contents(path_img_folder)
                                valid_imgs = [i for i in imgs if i.name.lower().endswith(('.png', '.jpg', '.jpeg', '.heic'))]
                                
                                if not valid_imgs:
                                    st.info("Aucun fichier.")
                                else:
                                    for img in valid_imgs:
                                        # On utilise des colonnes pour pousser à droite
                                        # Filename (Gros) | Download (Moyen) | Delete (Moyen)
                                        c1, c2, c3 = st.columns([6, 2, 2])
                                        
                                        with c1:
                                            # On aligne verticalement le texte pour qu'il soit au niveau des boutons
                                            st.markdown(f"<div style='padding-top: 5px;'>📄 <b>{img.name}</b></div>", unsafe_allow_html=True)
                                        
                                        with c2:
                                            st.download_button(
                                                label="⬇️",
                                                data=img.decoded_content,
                                                file_name=img.name,
                                                key=f"dl_{img.sha}",
                                                use_container_width=True # Prend toute la largeur de la petite colonne
                                            )
                                        
                                        with c3:
                                            if st.button("🗑️", key=f"del_{img.sha}", use_container_width=True):
                                                try:
                                                    repo.delete_file(img.path, f"Delete {img.name}", img.sha)
                                                    st.toast(f"Fichier {img.name} supprimé !")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Erreur suppression : {e}")

                            except:
                                st.info("Dossier vide ou erreur.")
                        else:
                            st.info("👈 Sélectionnez ou créez un dossier à gauche.")

                with tab_aco:
                    st.write("En attente...")
                
    else:
        st.error("Fichier introuvable.")
