# PRISMA

PRISMA aide une PME a verifier un dossier de reponse a un appel d'offres.
L'application extrait les exigences d'un DAO, cherche les preuves dans les pieces fournies et produit des verdicts, un score et un plan d'action.

## Installation

Python 3.10 ou plus recent est recommande.

```bash
python -m pip install -r requirements.txt
```

Avec l'environnement virtuel du projet sous Windows :

```bash
.venv\\Scripts\\activate
```

Copier `.env.example` vers `.env`, puis renseigner `NVIDIA_API_KEY`.

Pour activer le stockage chiffré des documents, générer une clé Fernet et la renseigner dans `PRISMA_STORAGE_KEY` :

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

La clé doit rester secrète et être sauvegardée : les documents chiffrés ne sont pas récupérables sans elle.

## Lancer l'application

```bash
streamlit run app.py
```

Pour tester l'interface sans clé NVIDIA ni appel réseau :

```bash
PRISMA_DEMO_MODE=1 streamlit run app.py
```

Puis cliquer sur `Charger les données de démonstration` dans la barre latérale. Le dossier affiché est fictif.

## Déploiement de démonstration

Le projet peut être publié gratuitement avec Streamlit Community Cloud :

1. Pousser cette branche sur GitHub.
2. Ouvrir `share.streamlit.io` et choisir le dépôt `EdenHavila/prisma`.
3. Sélectionner la branche `feature-update` et le fichier `app.py`.
4. Dans `Settings > Secrets`, ajouter :

```toml
PRISMA_DEMO_MODE = "1"
```

Ce mode permet de tester l'interface sans clé NVIDIA et sans appel réseau. Pour activer l'analyse IA, remplacer ensuite par `PRISMA_DEMO_MODE = "0"` et ajouter `NVIDIA_API_KEY` ainsi que `PRISMA_STORAGE_KEY` dans les Secrets.

La base SQLite et les documents locaux ne sont pas un stockage permanent sur une instance gratuite. Cette version convient donc à une démonstration, pas à la conservation de dossiers clients.

Les documents sont envoyes a l'API NVIDIA pour l'analyse. Ne pas utiliser de donnees confidentielles reelles sans mettre en place un stockage et une securite adaptes.

## Comptes, rapports et documents

L'application demande un compte utilisateur. Les mots de passe sont hachés avec PBKDF2-SHA256.
Les utilisateurs et les rapports sont conservés dans SQLite (`.prisma/prisma.db` par défaut).
Les documents importés sont chiffrés avec Fernet avant leur écriture dans `.prisma/documents`.
Un rapport PDF est disponible depuis l'onglet des résultats.

Pour un déploiement réel, protéger les fichiers `.prisma`, limiter les permissions du processus et fournir `PRISMA_STORAGE_KEY` via le gestionnaire de secrets de l'hébergeur.

## Tests locaux

Les tests ne necessitent pas de cle API :

```bash
python -m unittest discover -v
```

Le test d'integration API est volontairement separe :

```bash
python test_api.py
```

## Configuration

- `NVIDIA_API_KEY` : cle obligatoire.
- `NVIDIA_BASE_URL` : endpoint compatible OpenAI.
- `LLM_MODEL`, `EMB_MODEL`, `VISION_MODEL` : modeles utilises.
- `VISION_FALLBACKS` : modeles de secours pour l'OCR.
- `MAX_FILE_SIZE_MB` : taille maximale d'un fichier importe, 25 Mo par defaut.
