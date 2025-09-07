from flask import Flask, request, send_from_directory, jsonify
from flask_cors import CORS
import smtplib
import os
from datetime import datetime
import json
import base64
import zipfile
import io
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

app = Flask(__name__)
CORS(app)

# Configuration Email pour ZeenDoc
EMAIL_DESTINATAIRE = os.environ.get('EMAIL_DESTINATAIRE', 'eloise.csmt@gmail.com')
ZEENDOC_EMAIL = os.environ.get('ZEENDOC_EMAIL', 'repos@zeendoc.com')  # Adresse ZeenDoc

# Configuration SMTP (maintenant obligatoire)
SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')

# Configuration pour la gestion des fichiers lourds
LIMITE_EMAIL_MB = int(os.environ.get('LIMITE_EMAIL_MB', '20'))
DELAI_ENTRE_ENVOIS = int(os.environ.get('DELAI_ENTRE_ENVOIS', '30'))
MAX_EMAILS_PAR_DEMANDE = int(os.environ.get('MAX_EMAILS_PAR_DEMANDE', '5'))

# Servir les fichiers statiques (HTML, CSS)
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/styles.css')
def css():
    return send_from_directory('.', 'styles.css')

# Route pour les demandes de gestion (original)
@app.route('/envoyer-demande', methods=['POST'])
def envoyer_demande():
    try:
        # Vérification de la configuration SMTP
        if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD]):
            return jsonify({
                "status": "error", 
                "message": "Configuration SMTP incomplète. Veuillez configurer SMTP_SERVER, SMTP_USERNAME et SMTP_PASSWORD."
            }), 500
        
        # Récupérer les données du formulaire
        data = request.form.to_dict()
        files = request.files
        
        # Construire le sujet
        type_demande = data.get('type', 'Demande')
        nom = data.get('nom', '')
        prenom = data.get('prenom', '')
        date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
        
        sujet_principal = f"Demande {type_demande.title()} - {nom} {prenom} - {date_demande}"
        sujet_zeendoc = f"[ZEENDOC] Documents - {nom} {prenom} - {type_demande.title()}"
        
        # Construire le corps du mail principal
        corps_principal = generer_corps_email(data)
        
        # Préparer les fichiers pour ZeenDoc
        fichiers_pieces = []
        if files and any(file.filename for file in files.values() if file):
            fichiers_pieces = preparer_fichiers_zeendoc(files, nom, prenom, type_demande)
        
        # Envoi automatique des deux emails
        envoi_auto_reussi = False
        resultats_detailles = {}
        
        try:
            print("📧 Début des envois automatiques...")
            
            # 1. Email PRINCIPAL avec ZIP si nécessaire
            print("📧 Envoi email principal...")
            envoi_principal = envoyer_email_principal_auto(
                sujet_principal, 
                corps_principal, 
                fichiers_pieces,
                data
            )
            
            # 2. Emails ZEENDOC multiples avec fichiers originaux
            print("📁 Envoi vers ZeenDoc...")
            resultats_zeendoc = []
            if fichiers_pieces:
                corps_zeendoc = generer_corps_zeendoc(data, fichiers_pieces)
                resultats_zeendoc = envoyer_emails_zeendoc_multiples(
                    sujet_zeendoc, 
                    corps_zeendoc, 
                    fichiers_pieces
                )
            
            # Vérification globale
            zeendoc_reussi = all(r.get('succes', False) for r in resultats_zeendoc) if resultats_zeendoc else True
            envoi_auto_reussi = envoi_principal and zeendoc_reussi
            
            resultats_detailles = {
                'email_principal': envoi_principal,
                'zeendoc_parties': resultats_zeendoc,
                'zeendoc_reussi': zeendoc_reussi,
                'total_emails_zeendoc': len(resultats_zeendoc)
            }
            
            print(f"✅ Envois terminés - Principal: {envoi_principal}, ZeenDoc: {zeendoc_reussi}")
            
        except Exception as e:
            print(f"❌ Erreur envoi automatique: {str(e)}")
            return jsonify({
                "status": "error", 
                "message": f"Erreur lors de l'envoi automatique: {str(e)}"
            }), 500
        
        return jsonify({
            "status": "success", 
            "message": "Demande envoyée avec succès!",
            "fichiers_count": len(fichiers_pieces),
            "envoi_auto": envoi_auto_reussi,
            "details_envoi": resultats_detailles,
            "fichiers_info": [f["nom"] for f in fichiers_pieces]
        })
        
    except Exception as e:
        print(f"Erreur générale: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors du traitement: {str(e)}"}), 500

# Route pour les demandes d'ingénierie (nouvelle)
@app.route('/envoyer-demande-ingenierie', methods=['POST'])
def envoyer_demande_ingenierie():
    try:
        # Vérification de la configuration SMTP
        if not all([SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD]):
            return jsonify({
                "status": "error", 
                "message": "Configuration SMTP incomplète. Veuillez configurer SMTP_SERVER, SMTP_USERNAME et SMTP_PASSWORD."
            }), 500
        
        # Récupérer les données du formulaire
        data = request.form.to_dict()
        files = request.files
        
        # Construire les sujets
        nom_conseiller = data.get('nomConseiller', 'Conseiller')
        secteur_conseiller = data.get('secteurConseiller', 'Secteur')
        contact1_nom = data.get('nomContact1', '')
        contact1_prenom = data.get('prenomContact1', '')
        contact2_nom = data.get('nomContact2', '')
        contact2_prenom = data.get('prenomContact2', '')
        date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
        
        # Construire le nom du client
        client_principal = f"{contact1_nom} {contact1_prenom}"
        if contact2_nom and contact2_prenom:
            client_principal += f" & {contact2_nom} {contact2_prenom}"
        
        sujet_principal = f"Demande Ingénierie - {client_principal} - {nom_conseiller} - {date_demande}"
        sujet_zeendoc = f"[ZEENDOC] Ingénierie - {client_principal} - {nom_conseiller}"
        
        # Construire le corps du mail principal
        corps_principal = generer_corps_email_ingenierie(data)
        
        # Préparer les fichiers pour ZeenDoc
        fichiers_pieces = []
        if files and any(file.filename for file in files.values() if file):
            fichiers_pieces = preparer_fichiers_zeendoc_ingenierie(files, contact1_nom, contact1_prenom, nom_conseiller, secteur_conseiller)
        
        # Envoi automatique des deux emails
        envoi_auto_reussi = False
        resultats_detailles = {}
        
        try:
            print("📧 Début des envois automatiques d'ingénierie...")
            
            # 1. Email PRINCIPAL avec ZIP si nécessaire
            print("📧 Envoi email principal...")
            envoi_principal = envoyer_email_principal_auto(
                sujet_principal, 
                corps_principal, 
                fichiers_pieces,
                data,
                type_demande="ingenierie"
            )
            
            # 2. Emails ZEENDOC multiples avec fichiers originaux
            print("📁 Envoi vers ZeenDoc...")
            resultats_zeendoc = []
            if fichiers_pieces:
                corps_zeendoc = generer_corps_zeendoc_ingenierie(data, fichiers_pieces)
                resultats_zeendoc = envoyer_emails_zeendoc_multiples(
                    sujet_zeendoc, 
                    corps_zeendoc, 
                    fichiers_pieces
                )
            
            # Vérification globale
            zeendoc_reussi = all(r.get('succes', False) for r in resultats_zeendoc) if resultats_zeendoc else True
            envoi_auto_reussi = envoi_principal and zeendoc_reussi
            
            resultats_detailles = {
                'email_principal': envoi_principal,
                'zeendoc_parties': resultats_zeendoc,
                'zeendoc_reussi': zeendoc_reussi,
                'total_emails_zeendoc': len(resultats_zeendoc)
            }
            
            print(f"✅ Envois ingénierie terminés - Principal: {envoi_principal}, ZeenDoc: {zeendoc_reussi}")
            
        except Exception as e:
            print(f"❌ Erreur envoi automatique ingénierie: {str(e)}")
            return jsonify({
                "status": "error", 
                "message": f"Erreur lors de l'envoi automatique: {str(e)}"
            }), 500
        
        return jsonify({
            "status": "success", 
            "message": "Demande d'ingénierie envoyée avec succès!",
            "fichiers_count": len(fichiers_pieces),
            "envoi_auto": envoi_auto_reussi,
            "details_envoi": resultats_detailles,
            "fichiers_info": [f["nom"] for f in fichiers_pieces]
        })
        
    except Exception as e:
        print(f"Erreur générale ingénierie: {str(e)}")
        return jsonify({"status": "error", "message": f"Erreur lors du traitement: {str(e)}"}), 500

def envoyer_email_principal_auto(sujet, corps, fichiers_pieces, data, type_demande="standard"):
    """Email principal avec compression ZIP si trop lourd"""
    
    try:
        if not fichiers_pieces:
            # Pas de fichiers, envoi simple
            return envoyer_email_smtp(
                destinataire=EMAIL_DESTINATAIRE,
                sujet=sujet,
                corps=corps,
                fichiers=[]
            )
        
        # Calculer la taille totale
        taille_totale = sum(f['taille'] for f in fichiers_pieces)
        limite_bytes = LIMITE_EMAIL_MB * 1024 * 1024
        
        # Décider si on compresse
        if taille_totale > limite_bytes:
            print(f"📦 Compression ZIP nécessaire: {format_file_size(taille_totale)} > {LIMITE_EMAIL_MB}MB")
            fichiers_a_envoyer = creer_archive_zip(fichiers_pieces, data, type_demande)
            corps_modifie = corps + f"""

=== PIÈCES JOINTES ===
📦 Fichiers compressés en archive ZIP (taille originale: {format_file_size(taille_totale)})
📄 {len(fichiers_pieces)} document(s) dans l'archive
💾 Taille compressée: {format_file_size(fichiers_a_envoyer[0]['taille'])}

ℹ️  Les documents originaux sont envoyés séparément vers ZeenDoc pour traitement.
"""
        else:
            print(f"📄 Envoi fichiers originaux: {format_file_size(taille_totale)} < {LIMITE_EMAIL_MB}MB")
            fichiers_a_envoyer = fichiers_pieces
            corps_modifie = corps
        
        return envoyer_email_smtp(
            destinataire=EMAIL_DESTINATAIRE,
            sujet=sujet,
            corps=corps_modifie,
            fichiers=fichiers_a_envoyer
        )
        
    except Exception as e:
        print(f"❌ Erreur envoi email principal: {str(e)}")
        return False

def creer_archive_zip(fichiers_pieces, data, type_demande="standard"):
    """Crée une archive ZIP avec tous les fichiers"""
    
    try:
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            for fichier in fichiers_pieces:
                # Organiser par catégorie dans le ZIP
                chemin_dans_zip = f"{fichier['categorie']}/{fichier['nom']}"
                zip_file.writestr(chemin_dans_zip, fichier['contenu'])
        
        zip_buffer.seek(0)
        contenu_zip = zip_buffer.getvalue()
        
        # Générer nom du ZIP selon le type
        if type_demande == "ingenierie":
            nom_conseiller = data.get('nomConseiller', 'Conseiller').replace(' ', '_')
            contact1_nom = data.get('nomContact1', 'Client')
            contact1_prenom = data.get('prenomContact1', '')
            nom_zip = f"Documents_INGENIERIE_{contact1_nom.upper()}_{contact1_prenom}_{nom_conseiller}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        else:
            nom = data.get('nom', 'Client')
            prenom = data.get('prenom', '')
            type_demande_clean = data.get('type', 'Demande')
            nom_zip = f"Documents_{type_demande_clean.upper()}_{nom.upper()}_{prenom}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        print(f"📦 Archive ZIP créée: {nom_zip} ({format_file_size(len(contenu_zip))})")
        
        return [{
            'nom': nom_zip,
            'contenu': contenu_zip,
            'type_mime': 'application/zip',
            'taille': len(contenu_zip),
            'categorie': 'Archive complète'
        }]
        
    except Exception as e:
        print(f"❌ Erreur création ZIP: {str(e)}")
        return fichiers_pieces  # Retourner les fichiers originaux en cas d'erreur

def diviser_fichiers_par_taille(fichiers_pieces, limite_mb=None):
    """Divise les fichiers en plusieurs groupes selon la taille"""
    
    if limite_mb is None:
        limite_mb = LIMITE_EMAIL_MB
    
    limite_bytes = limite_mb * 1024 * 1024
    groupes = []
    groupe_actuel = []
    taille_actuelle = 0
    
    for fichier in fichiers_pieces:
        taille_fichier = fichier['taille']
        
        # Si le fichier seul dépasse la limite
        if taille_fichier > limite_bytes:
            # Envoyer le groupe actuel s'il n'est pas vide
            if groupe_actuel:
                groupes.append(groupe_actuel)
                groupe_actuel = []
                taille_actuelle = 0
            
            # Fichier seul dans son propre groupe
            groupes.append([fichier])
            print(f"⚠️  Fichier volumineux isolé: {fichier['nom']} ({format_file_size(taille_fichier)})")
            continue
        
        # Si ajouter ce fichier dépasse la limite
        if taille_actuelle + taille_fichier > limite_bytes:
            # Finaliser le groupe actuel
            if groupe_actuel:
                groupes.append(groupe_actuel)
            
            # Commencer un nouveau groupe
            groupe_actuel = [fichier]
            taille_actuelle = taille_fichier
        else:
            # Ajouter au groupe actuel
            groupe_actuel.append(fichier)
            taille_actuelle += taille_fichier
    
    # Ajouter le dernier groupe
    if groupe_actuel:
        groupes.append(groupe_actuel)
    
    return groupes

def envoyer_emails_zeendoc_multiples(sujet_base, corps_base, fichiers_pieces):
    """ZeenDoc: Emails multiples pour préserver la qualité"""
    
    if not fichiers_pieces:
        return []
    
    groupes_fichiers = diviser_fichiers_par_taille(fichiers_pieces)
    total_groupes = len(groupes_fichiers)
    
    if total_groupes > MAX_EMAILS_PAR_DEMANDE:
        print(f"⚠️  Trop de groupes ({total_groupes}), limité à {MAX_EMAILS_PAR_DEMANDE}")
        groupes_fichiers = groupes_fichiers[:MAX_EMAILS_PAR_DEMANDE]
        total_groupes = len(groupes_fichiers)
    
    print(f"📧 Division ZeenDoc: {len(fichiers_pieces)} fichiers → {total_groupes} email(s)")
    
    resultats = []
    
    for index, groupe in enumerate(groupes_fichiers, 1):
        try:
            # Sujet avec numérotation
            if total_groupes > 1:
                sujet_numerote = f"{sujet_base} - Partie {index}/{total_groupes}"
            else:
                sujet_numerote = sujet_base
            
            # Corps adapté pour ZeenDoc
            corps_numerote = generer_corps_zeendoc_multiple(
                corps_base, groupe, index, total_groupes, fichiers_pieces
            )
            
            taille_groupe = sum(f['taille'] for f in groupe)
            print(f"📤 Envoi partie {index}/{total_groupes} vers ZeenDoc: {len(groupe)} fichier(s) ({format_file_size(taille_groupe)})")
            
            # Envoi vers ZeenDoc
            succes = envoyer_email_smtp(
                destinataire=ZEENDOC_EMAIL,
                cc=EMAIL_DESTINATAIRE,  # Copie pour suivi
                sujet=sujet_numerote,
                corps=corps_numerote,
                fichiers=groupe
            )
            
            resultats.append({
                'partie': f"{index}/{total_groupes}",
                'fichiers_count': len(groupe),
                'succes': succes,
                'taille_totale': taille_groupe,
                'fichiers': [f['nom'] for f in groupe]
            })
            
            if succes:
                print(f"✅ Partie {index}/{total_groupes} envoyée avec succès")
            else:
                print(f"❌ Échec envoi partie {index}/{total_groupes}")
            
            # Délai entre envois (sauf dernier)
            if index < total_groupes and succes:
                print(f"⏱️  Attente {DELAI_ENTRE_ENVOIS}s avant envoi suivant...")
                time.sleep(DELAI_ENTRE_ENVOIS)
                
        except Exception as e:
            print(f"❌ Erreur envoi partie {index}/{total_groupes}: {str(e)}")
            resultats.append({
                'partie': f"{index}/{total_groupes}",
                'succes': False,
                'erreur': str(e)
            })
    
    return resultats

def envoyer_email_smtp(destinataire, sujet, corps, fichiers, cc=None):
    """Fonction SMTP générique pour tous les envois"""
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USERNAME
        msg['To'] = destinataire
        if cc:
            msg['Cc'] = cc
        msg['Subject'] = sujet
        
        # Corps du message
        msg.attach(MIMEText(corps, 'plain', 'utf-8'))
        
        # Pièces jointes
        for fichier in fichiers:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(fichier['contenu'])
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{fichier["nom"]}"'
            )
            msg.attach(part)
        
        # Envoi SMTP
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            
            destinataires = [destinataire]
            if cc:
                destinataires.append(cc)
            
            server.send_message(msg, to_addrs=destinataires)
            return True
            
    except Exception as e:
        print(f"❌ Erreur SMTP: {str(e)}")
        return False

def generer_corps_zeendoc_multiple(corps_base, fichiers_groupe, index, total, fichiers_complets):
    """Génère le corps pour un email multiple"""
    
    if total == 1:
        return corps_base
    
    # En-tête spécial pour les envois multiples
    entete_multiple = f"""=== ENVOI MULTIPLE - PARTIE {index}/{total} ===
⚠️  ATTENTION: Cet envoi fait partie d'un lot de {total} emails
📦 Cette partie contient {len(fichiers_groupe)} document(s) sur {len(fichiers_complets)} au total
⏱️  Délai entre envois: {DELAI_ENTRE_ENVOIS} secondes pour éviter la saturation

"""
    
    # Ajouter la liste des fichiers de cette partie
    fichiers_section = "=== FICHIERS DE CETTE PARTIE ===\n"
    
    par_categorie = {}
    for fichier in fichiers_groupe:
        cat = fichier['categorie']
        if cat not in par_categorie:
            par_categorie[cat] = []
        par_categorie[cat].append(fichier)
    
    for categorie, fichiers in par_categorie.items():
        fichiers_section += f"\n📁 {categorie.upper()}:\n"
        for fichier in fichiers:
            taille_fmt = format_file_size(fichier['taille'])
            fichiers_section += f"  • {fichier['nom']} ({taille_fmt})\n"
    
    # Informations sur l'envoi complet
    recap_section = f"""

=== RÉCAPITULATIF COMPLET ===
Total des documents: {len(fichiers_complets)}
Nombre d'emails: {total}
Partie actuelle: {index}/{total}
"""
    
    return entete_multiple + fichiers_section + recap_section + "\n" + corps_base

# ===== FONCTIONS POUR LES DEMANDES STANDARD (inchangées) =====

def preparer_fichiers_zeendoc(files, nom, prenom, type_demande):
    """Prépare les fichiers pour l'envoi vers ZeenDoc - demandes standard"""
    
    fichiers_pieces = []
    
    for key, file in files.items():
        if file and file.filename:
            try:
                # Lire le contenu du fichier
                file_content = file.read()
                file.seek(0)  # Remettre le curseur au début
                
                # Générer un nom de fichier standardisé
                nom_standardise = generer_nom_fichier_zeendoc(
                    file.filename, 
                    nom, 
                    prenom, 
                    type_demande,
                    key
                )
                
                fichiers_pieces.append({
                    'nom': nom_standardise,
                    'nom_original': file.filename,
                    'contenu': file_content,
                    'type_mime': file.content_type or 'application/octet-stream',
                    'taille': len(file_content),
                    'categorie': obtenir_categorie_document(key)
                })
                
            except Exception as e:
                print(f"Erreur préparation fichier {file.filename}: {str(e)}")
                continue
    
    return fichiers_pieces

def generer_nom_fichier_zeendoc(nom_fichier, nom, prenom, type_demande, doc_id):
    """Génère un nom de fichier standardisé pour ZeenDoc - demandes standard"""
    
    # Extraire l'extension
    extension = ""
    if '.' in nom_fichier:
        extension = nom_fichier.split('.')[-1].lower()
    
    # Mapper les IDs de documents vers des noms courts
    mapping_docs = {
        'majProfil_doc': 'MAJ_Profil',
        'etudeSignee_doc': 'Etude_Signee',
        'cniValide_doc': 'CNI',
        'justifDom_doc': 'Justif_Domicile',
        'ribJour_doc': 'RIB',
        'justifProvenance_doc': 'Justif_Provenance',
        'justifDomImpot_doc': 'Justif_Dom_Impot',
        'clauseBeneficiaire_doc': 'Clause_Beneficiaire',
        'majProfilRachat_doc': 'MAJ_Profil',
        'ribJourRachat_doc': 'RIB',
        'majProfilArbitrage_doc': 'MAJ_Profil',
        'ficheRenseignement_doc': 'Fiche_Renseignement',
        'profilClientSigne_doc': 'Profil_Client',
        'cartoClientSigne_doc': 'Cartographie',
        'lettreMiseRelation_doc': 'Lettre_Relation',
        'filSigne_doc': 'FIL',
        'justifDomCreation_doc': 'Justif_Domicile',
        'cniValideCreation_doc': 'CNI'
    }
    
    doc_type = mapping_docs.get(doc_id, 'Document')
    
    # Format: TYPE_DEMANDE_NOM_Prenom_TypeDocument_YYYYMMDD.ext
    date_str = datetime.now().strftime('%Y%m%d')
    nom_final = f"{type_demande.upper()}_{nom.upper()}_{prenom}_{doc_type}_{date_str}"
    
    if extension:
        nom_final += f".{extension}"
    
    return nom_final

def obtenir_categorie_document(doc_id):
    """Retourne la catégorie du document pour ZeenDoc - demandes standard"""
    
    categories = {
        'majProfil_doc': 'Profil Client',
        'etudeSignee_doc': 'Etudes',
        'cniValide_doc': 'Identité',
        'justifDom_doc': 'Justificatifs',
        'ribJour_doc': 'Bancaire',
        'justifProvenance_doc': 'Justificatifs',
        'justifDomImpot_doc': 'Justificatifs',
        'clauseBeneficiaire_doc': 'Bénéficiaires',
        'majProfilRachat_doc': 'Profil Client',
        'ribJourRachat_doc': 'Bancaire',
        'majProfilArbitrage_doc': 'Profil Client',
        'ficheRenseignement_doc': 'Profil Client',
        'profilClientSigne_doc': 'Profil Client',
        'cartoClientSigne_doc': 'Cartographie',
        'lettreMiseRelation_doc': 'Relation Client',
        'filSigne_doc': 'Documents Légaux',
        'justifDomCreation_doc': 'Justificatifs',
        'cniValideCreation_doc': 'Identité'
    }
    
    return categories.get(doc_id, 'Général')

def generer_corps_zeendoc(data, fichiers_pieces):
    """Génère le corps de l'email pour ZeenDoc - demandes standard"""
    
    type_demande = data.get('type', 'Non spécifié').upper()
    nom = data.get('nom', '')
    prenom = data.get('prenom', '')
    date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
    
    corps = f"""=== DÉPÔT AUTOMATIQUE ZEENDOC ===
Type de demande: {type_demande}
Client: {nom} {prenom}
Date: {date_demande}
Nombre de pièces: {len(fichiers_pieces)}

=== CLASSIFICATION DES DOCUMENTS ===
"""

    # Grouper par catégorie
    par_categorie = {}
    for fichier in fichiers_pieces:
        cat = fichier['categorie']
        if cat not in par_categorie:
            par_categorie[cat] = []
        par_categorie[cat].append(fichier)
    
    for categorie, fichiers in par_categorie.items():
        corps += f"\n📁 {categorie.upper()}:\n"
        for fichier in fichiers:
            taille_fmt = format_file_size(fichier['taille'])
            corps += f"  • {fichier['nom']} ({taille_fmt})\n"
    
    corps += f"""

=== INFORMATIONS TECHNIQUES ===
Format de nommage: TYPE_NOM_Prenom_TypeDoc_YYYYMMDD.ext
Origine: Formulaire automatisé de gestion des demandes
Horodatage: {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}

=== INSTRUCTIONS ZEENDOC ===
Ces documents sont à classer automatiquement dans le dossier client:
- Nom du dossier: {nom.upper()} {prenom}
- Type de demande: {type_demande}
- Référence: {type_demande}_{nom.upper()}_{prenom}_{datetime.now().strftime('%Y%m%d')}

Merci de confirmer la réception et le classement.
"""
    
    return corps

def generer_corps_email(data):
    """Génère le contenu formaté de l'email principal - demandes standard"""
    
    type_demande = data.get('type', 'Non spécifié').upper()
    
    corps = f"""=== DEMANDE DE {type_demande} ===
Date: {data.get('dateDemande', 'Non spécifiée')}
Client: {data.get('nom', '')} {data.get('prenom', '')}
Nouveau client: {data.get('nouveauClient', 'Non spécifié')}
Urgence: {data.get('urgence', 'Normal')}
Origine: {data.get('origine', 'Non spécifiée')}
Mode signature: {data.get('modeSignature', 'Non spécifié')}
Prochain RDV: {data.get('dateRdv', 'Non programmé')}

"""

    # Informations spécifiques selon le type
    if data.get('type') == 'versement':
        corps += f"""=== INFORMATIONS FINANCIÈRES ===
Type de versement: {data.get('typeVersement', 'Non spécifié')}
Montant: {data.get('montantVersement', 'Non spécifié')} €
Allocation: {data.get('allocationVersement', 'Non spécifiée')}
Frais: {data.get('fraisVersement', 'Non spécifiés')}%

=== PROVENANCE ET TRAÇABILITÉ ===
Provenance: {data.get('provenanceFonds', 'Non spécifiée')}
Chemin: {data.get('cheminArgent', 'Non spécifié')}
Justificatif transit: {data.get('justifCompteTransit', 'Non spécifié')}

=== BÉNÉFICIAIRES ===
Type clause: {data.get('clauseBeneficiaireType', 'Non spécifié')}
Spécification: {data.get('clauseBeneficiaireSpec', 'Non spécifiée')}

"""

    elif data.get('type') == 'rachat':
        corps += f"""=== INFORMATIONS FINANCIÈRES ===
Type de rachat: {data.get('typeRachat', 'Non spécifié')}
Montant: {data.get('montantRachat', 'Non spécifié')} €
Fiscalité: {data.get('fiscaliteRachat', 'Non spécifiée')}
Motif: {data.get('motifRachat', 'Non spécifié')}

=== SUPPORTS ET RÉALLOCATION ===
Support à désinvestir: {data.get('supportDesinvestir', 'Non spécifié')}
Pourcentage à réalouer: {data.get('pourcentageReallouer', 'Non spécifié')}%
Nouveau support: {data.get('nouveauSupport', 'Non spécifié')}

"""

    elif data.get('type') == 'arbitrage':
        corps += f"""=== ALLOCATION FINANCIÈRE ===
Montant: {data.get('allocationArbitrage', 'Non spécifié')} €

"""

    corps += f"""

=== DOCUMENTS JOINTS ===
📎 Les pièces justificatives ont été envoyées automatiquement vers ZeenDoc
📧 Adresse de dépôt: {ZEENDOC_EMAIL}
📁 Référence dossier: {data.get('type', '').upper()}_{data.get('nom', '').upper()}_{data.get('prenom', '')}_{datetime.now().strftime('%Y%m%d')}

---
Demande générée et envoyée automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')}
Demandeur: {data.get('demandeur', 'Non spécifié')}
Secteur: {data.get('secteurDemandeur', 'Non spécifié')}
"""
    
    return corps

# ===== FONCTIONS POUR LES DEMANDES D'INGÉNIERIE =====

def preparer_fichiers_email_principal(files):
    """Prépare les fichiers pour l'email principal uniquement (sans nommage ZeenDoc)"""
    
    fichiers_pieces = []
    
    for key, file in files.items():
        if file and file.filename:
            try:
                # Lire le contenu du fichier
                file_content = file.read()
                file.seek(0)  # Remettre le curseur au début
                
                fichiers_pieces.append({
                    'nom': file.filename,  # Garder le nom original
                    'nom_original': file.filename,
                    'contenu': file_content,
                    'type_mime': file.content_type or 'application/octet-stream',
                    'taille': len(file_content),
                    'categorie': 'Documents'  # Catégorie générique
                })
                
            except Exception as e:
                print(f"Erreur préparation fichier email principal {file.filename}: {str(e)}")
                continue
    
    return fichiers_pieces

def preparer_fichiers_zeendoc_ingenierie(files, nom, prenom, conseiller, secteur):
    """Prépare les fichiers pour l'envoi vers ZeenDoc - version ingénierie"""
    
    fichiers_pieces = []
    
    for key, file in files.items():
        if file and file.filename:
            try:
                # Lire le contenu du fichier
                file_content = file.read()
                file.seek(0)  # Remettre le curseur au début
                
                # Générer un nom de fichier standardisé pour ingénierie
                nom_standardise = generer_nom_fichier_zeendoc_ingenierie(
                    file.filename, 
                    nom, 
                    prenom, 
                    conseiller,
                    secteur,
                    key
                )
                
                fichiers_pieces.append({
                    'nom': nom_standardise,
                    'nom_original': file.filename,
                    'contenu': file_content,
                    'type_mime': file.content_type or 'application/octet-stream',
                    'taille': len(file_content),
                    'categorie': obtenir_categorie_document_ingenierie(key)
                })
                
            except Exception as e:
                print(f"Erreur préparation fichier ingénierie {file.filename}: {str(e)}")
                continue
    
    return fichiers_pieces

def generer_nom_fichier_zeendoc_ingenierie(nom_fichier, nom, prenom, conseiller, secteur, doc_id):
    """Génère un nom de fichier standardisé pour ZeenDoc - version ingénierie"""
    
    # Extraire l'extension
    extension = ""
    if '.' in nom_fichier:
        extension = nom_fichier.split('.')[-1].lower()
    
    # Mapper les IDs de documents vers des noms courts
    mapping_docs = {
        'ficheRenseignement': 'Fiche_Renseignement',
        'avisImposition': 'Avis_Imposition',
        'bulletinsSalaire': 'Bulletins_Salaire',
        'infosRetraite': 'Infos_Retraite',
        'relevesPlacement': 'Releves_Placement',
        'cniLivret': 'CNI_Livret',
        'tableauAmortissement': 'Tableau_Amortissement',
        'autresDocuments': 'Autres_Documents'
    }
    
    doc_type = mapping_docs.get(doc_id, 'Document')
    
    # Format: INGENIERIE_NOM_Prenom_TypeDocument_Conseiller_Secteur_YYYYMMDD.ext
    date_str = datetime.now().strftime('%Y%m%d')
    conseiller_clean = conseiller.replace(' ', '_')
    secteur_clean = secteur.replace(' ', '_')
    nom_final = f"INGENIERIE_{nom.upper()}_{prenom}_{doc_type}_{conseiller_clean}_{secteur_clean}_{date_str}"
    
    if extension:
        nom_final += f".{extension}"
    
    return nom_final

def obtenir_categorie_document_ingenierie(doc_id):
    """Retourne la catégorie du document pour ZeenDoc - version ingénierie"""
    
    categories = {
        'ficheRenseignement': 'Profil Client',
        'avisImposition': 'Fiscalite',
        'bulletinsSalaire': 'Revenus',
        'infosRetraite': 'Retraite',
        'relevesPlacement': 'Placements',
        'profilRisques': 'Profil Client',
        'cniLivret': 'Identite',
        'tableauAmortissement': 'Credits',
        'autresDocuments': 'Autres'
    }
    
    return categories.get(doc_id, 'General')

def generer_corps_zeendoc_ingenierie(data, fichiers_pieces):
    """Génère le corps de l'email pour ZeenDoc - version ingénierie"""
    
    nom_conseiller = data.get('nomConseiller', 'Non specifie')
    secteur_conseiller = data.get('secteurConseiller', 'Non specifie')
    contact1_nom = data.get('nomContact1', '')
    contact1_prenom = data.get('prenomContact1', '')
    contact2_nom = data.get('nomContact2', '')
    contact2_prenom = data.get('prenomContact2', '')
    date_demande = data.get('dateDemande', datetime.now().strftime('%d/%m/%Y'))
    
    # Construire le nom du client
    client_principal = f"{contact1_nom} {contact1_prenom}"
    if contact2_nom and contact2_prenom:
        client_principal += f" & {contact2_nom} {contact2_prenom}"
    
    corps = f"""=== DEPOT AUTOMATIQUE ZEENDOC - INGENIERIE ===
Type: Demande d'ingenierie patrimoniale
Client(s): {client_principal}
Conseiller: {nom_conseiller} ({secteur_conseiller})
Date: {date_demande}
Nombre de pieces: {len(fichiers_pieces)}

=== CLASSIFICATION DES DOCUMENTS ===
"""

    # Grouper par catégorie
    par_categorie = {}
    for fichier in fichiers_pieces:
        cat = fichier['categorie']
        if cat not in par_categorie:
            par_categorie[cat] = []
        par_categorie[cat].append(fichier)
    
    for categorie, fichiers in par_categorie.items():
        corps += f"\n📁 {categorie.upper()}:\n"
        for fichier in fichiers:
            taille_fmt = format_file_size(fichier['taille'])
            corps += f"  • {fichier['nom']} ({taille_fmt})\n"
    
    corps += f"""

=== INFORMATIONS TECHNIQUES ===
Format de nommage: NOM_Prenom_TypeDoc_Conseiller_YYYYMMDD.ext
Origine: Formulaire automatise de demande d'ingenierie
Horodatage: {datetime.now().strftime('%d/%m/%Y a %H:%M:%S')}

=== INSTRUCTIONS ZEENDOC ===
Ces documents sont a classer automatiquement dans le dossier client:
- Nom du dossier: {client_principal}
- Type de demande: INGENIERIE PATRIMONIALE
- Reference: INGENIERIE_{contact1_nom.upper()}_{contact1_prenom}_{datetime.now().strftime('%Y%m%d')}
- Conseiller responsable: {nom_conseiller} ({secteur_conseiller})

Merci de confirmer la reception et le classement.
"""
    
    return corps

def generer_corps_email_ingenierie(data):
    """Génère le contenu formaté de l'email principal - version ingénierie"""
    
    nom_conseiller = data.get('nomConseiller', 'Non specifie')
    secteur_conseiller = data.get('secteurConseiller', 'Non specifie')
    contact1_nom = data.get('nomContact1', '')
    contact1_prenom = data.get('prenomContact1', '')
    contact2_nom = data.get('nomContact2', '')
    contact2_prenom = data.get('prenomContact2', '')
    
    # Construire le nom du client
    client_principal = f"{contact1_nom} {contact1_prenom}"
    if contact2_nom and contact2_prenom:
        client_principal += f" & {contact2_nom} {contact2_prenom}"
    
    corps = f"""=== DEMANDE D'INGENIERIE PATRIMONIALE ===
Date: {data.get('dateDemande', 'Non specifiee')}
Conseiller: {nom_conseiller} ({secteur_conseiller})
Client(s): {client_principal}
Typologie: {data.get('typologieContact', 'Non specifie')}
Urgence: {data.get('urgence', 'Normal')}
Origine du contact: {data.get('origineContact', 'Non specifiee')}
Prochain RDV: {data.get('dateRdv', 'Non programme')}

=== SITUATION FAMILIALE ===
Situation: {data.get('situationFamiliale', 'Non specifiee')}
Regime matrimonial: {data.get('regimeMatrimonial', 'Non specifie')}

"""

    # Objectifs patrimoniaux
    objectifs_communs = data.get('objectifs_communs', 'true') == 'true'
    
    if objectifs_communs:
        objectifs_data = data.get('objectifs_selected', '[]')
        try:
            import json
            objectifs = json.loads(objectifs_data)
            corps += "=== OBJECTIFS PATRIMONIAUX (COMMUNS) ===\n"
            for obj in objectifs:
                corps += f"- {obj}\n"
        except:
            corps += "=== OBJECTIFS PATRIMONIAUX ===\nNon specifies\n"
    else:
        try:
            import json
            objectifs1_data = data.get('objectifs_contact1', '[]')
            objectifs2_data = data.get('objectifs_contact2', '[]')
            objectifs1 = json.loads(objectifs1_data)
            objectifs2 = json.loads(objectifs2_data)
            
            corps += f"=== OBJECTIFS PATRIMONIAUX - {contact1_prenom} {contact1_nom} ===\n"
            for obj in objectifs1:
                corps += f"- {obj}\n"
            
            if contact2_nom and contact2_prenom:
                corps += f"\n=== OBJECTIFS PATRIMONIAUX - {contact2_prenom} {contact2_nom} ===\n"
                for obj in objectifs2:
                    corps += f"- {obj}\n"
        except:
            corps += "=== OBJECTIFS PATRIMONIAUX ===\nNon specifies\n"
    
    # Types de demande
    try:
        import json
        types_demande_data = data.get('types_demande_selected', '[]')
        types_demande = json.loads(types_demande_data)
        corps += "\n=== TYPES DE DEMANDE ===\n"
        for type_dem in types_demande:
            corps += f"- {type_dem}\n"
            
        # Précision pour "Autre"
        if 'Autre' in types_demande and data.get('autreDemandePrecision'):
            corps += f"Precision: {data.get('autreDemandePrecision')}\n"
    except:
        corps += "\n=== TYPES DE DEMANDE ===\nNon specifies\n"
    
    # Précisions sur la demande
    if data.get('precisionsDemande'):
        corps += f"""
=== PRECISIONS SUR LA DEMANDE ===
{data.get('precisionsDemande')}
"""
    
    corps += f"""

=== DOCUMENTS JOINTS ===
📎 Les pieces justificatives ont ete envoyees automatiquement vers ZeenDoc
📧 Adresse de depot: {ZEENDOC_EMAIL}
📁 Reference dossier: INGENIERIE_{contact1_nom.upper()}_{contact1_prenom}_{datetime.now().strftime('%Y%m%d')}

---
Demande generee et envoyee automatiquement le {datetime.now().strftime('%d/%m/%Y a %H:%M')}
Conseiller: {nom_conseiller} ({secteur_conseiller})
"""
    
    return corps

def format_file_size(bytes_size):
    """Formate la taille des fichiers de manière lisible"""
    
    if bytes_size == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(bytes_size, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_size / p, 2)
    return f"{s} {size_names[i]}"

if __name__ == '__main__':
    # En production sur Render, utiliser le port fourni par la plateforme
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
